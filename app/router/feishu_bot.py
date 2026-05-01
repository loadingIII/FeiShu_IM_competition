"""
飞书机器人 Webhook 回调处理
处理飞书机器人推送的消息事件
"""
import json
import hmac
import hashlib
import base64
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Header
from app.service import workflow_manager, chat_service
from utils.feishuUtils import feishu_api
from utils.logger_handler import logger

router = APIRouter(prefix="/feishu-bot", tags=["feishu-bot"])

# 从环境变量获取飞书应用凭证
import os
ENCRYPT_KEY = os.getenv("FEISHU_ENCRYPT_KEY", "")  # 事件订阅的 Encrypt Key
VERIFICATION_TOKEN = os.getenv("FEISHU_VERIFICATION_TOKEN", "")  # 验证 Token


async def verify_feishu_signature(request: Request, timestamp: str, nonce: str, signature: str) -> bool:
    """验证飞书请求签名（可选的安全校验）"""
    if not ENCRYPT_KEY:
        return True
    
    body = await request.body()
    # 飞书签名算法: base64(hmac-sha256(timestamp + nonce + encrypt_key + body))
    sign_str = f"{timestamp}{nonce}{ENCRYPT_KEY}{body.decode()}"
    expected_sign = base64.b64encode(
        hmac.new(ENCRYPT_KEY.encode(), sign_str.encode(), hashlib.sha256).digest()
    ).decode()
    return signature == expected_sign


@router.post("/webhook")
async def feishu_webhook(
    request: Request,
    x_lark_signature: str = Header(default="", alias="X-Lark-Signature"),
    x_lark_timestamp: str = Header(default="", alias="X-Lark-Timestamp"),
    x_lark_nonce: str = Header(default="", alias="X-Lark-Nonce"),
):
    """
    接收飞书机器人事件推送
    
    需要在飞书开发者后台配置事件订阅 URL:
    https://open.feishu.cn/app/{app_id}/botconf
    """
    body = await request.json()
    
    # 1. 处理 URL 验证（首次配置事件订阅时）
    if body.get("type") == "url_verification":
        challenge = body.get("challenge")
        logger.info(f"[FeishuBot] URL 验证请求, challenge: {challenge}")
        return {"challenge": challenge}
    
    # 2. 处理事件回调
    header = body.get("header", {})
    event_type = header.get("event_type")
    
    if event_type == "im.message.receive_v1":
        # 接收消息事件
        event = body.get("event", {})
        message = event.get("message", {})
        sender = event.get("sender", {})
        
        msg_type = message.get("message_type")
        content = json.loads(message.get("content", "{}"))
        chat_id = message.get("chat_id")
        sender_open_id = sender.get("sender_id", {}).get("open_id")
        
        # 只处理文本消息
        if msg_type == "text":
            text = content.get("text", "").strip()
            logger.info(f"[FeishuBot] 收到消息 from {sender_open_id}: {text}")
            
            # 处理用户消息
            await handle_user_message(
                chat_id=chat_id,
                sender_open_id=sender_open_id,
                message=text
            )
    
    return {"code": 0, "msg": "success"}


async def handle_user_message(chat_id: str, sender_open_id: str, message: str):
    """处理用户发送的消息"""
    
    # 获取或创建工作流
    workflow_id = await get_or_create_workflow(chat_id, sender_open_id)
    
    if workflow_id:
        # 将消息提交给工作流
        chat_service.submit_message(workflow_id, message)
        logger.info(f"[FeishuBot] 消息已提交到工作流 {workflow_id}")
    else:
        # 如果没有活跃工作流，创建新工作流
        workflow_id = await workflow_manager.create_workflow(
            user_input=message,
            user_id=sender_open_id,
            source="feishu_bot",
            chat_id=chat_id,
        )
        logger.info(f"[FeishuBot] 创建新工作流 {workflow_id}")


async def get_or_create_workflow(chat_id: str, user_id: str) -> str:
    """获取用户当前的活跃工作流，如果没有则返回 None"""
    # 这里可以实现工作流状态管理逻辑
    # 例如：检查用户是否有进行中的工作流
    workflows = await workflow_manager.list_workflows(limit=50)
    
    for wf in workflows:
        if (wf.get("user_id") == user_id and 
            wf.get("source") == "feishu_bot" and
            wf.get("status") in ["running", "waiting_input"]):
            return wf.get("workflow_id")
    
    return None


@router.post("/send-message")
async def send_message_to_chat(chat_id: str, message: str, msg_type: str = "text"):
    """
    主动发送消息到飞书群聊/私聊
    用于工作流节点向用户推送消息
    """
    token = await feishu_api.get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 构建消息内容
    if msg_type == "text":
        content = json.dumps({"text": message})
    elif msg_type == "interactive":
        # 卡片消息
        content = json.dumps(message)
    else:
        content = json.dumps({"text": message})
    
    payload = {
        "receive_id": chat_id,
        "msg_type": msg_type,
        "content": content
    }
    
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, params={"receive_id_type": "chat_id"}, json=payload)
        data = response.json()
        
        if data.get("code") == 0:
            logger.info(f"[FeishuBot] 消息发送成功 to {chat_id}")
            return {"success": True, "message_id": data["data"]["message_id"]}
        else:
            logger.error(f"[FeishuBot] 消息发送失败: {data}")
            return {"success": False, "error": data.get("msg")}
