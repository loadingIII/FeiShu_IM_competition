"""
飞书机器人 Webhook 回调处理
处理飞书机器人推送的消息事件和卡片交互
"""
import json
import hmac
import hashlib
import base64
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Header
from app.service import workflow_manager
from app.service.feishu_message_service import feishu_message_service
from app.service.feishu_ws_manager import feishu_ws_manager
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
        chat_type = message.get("chat_type")
        sender_open_id = sender.get("sender_id", {}).get("open_id")

        # 只处理文本消息
        if msg_type == "text":
            text = content.get("text", "").strip()
            logger.info(f"[FeishuBot] 收到消息 from {sender_open_id}: {text}")

            # --- chat_type routing ---
            if chat_type == "group":
                mentions = message.get("mentions", [])
                bot_open_id = feishu_ws_manager.bot_open_id
                is_mentioned = any(
                    m.get("id", {}).get("open_id") == bot_open_id
                    for m in mentions
                )
                if not is_mentioned:
                    return {"code": 0, "msg": "ignored"}
            # --- END chat_type routing ---

            # 处理用户消息
            await handle_user_message(
                chat_id=chat_id,
                sender_open_id=sender_open_id,
                message=text
            )
    
    return {"code": 0, "msg": "success"}


async def handle_user_message(chat_id: str, sender_open_id: str, message: str):
    """处理用户发送的消息"""
    await workflow_manager.handle_message(
        user_input=message,
        user_id=sender_open_id,
        source="feishu_bot",
        chat_id=chat_id,
        sender_open_id=sender_open_id,
    )


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


@router.post("/card-callback")
async def feishu_card_callback(request: Request):
    """处理飞书卡片交互回调

    需要在飞书开发者后台配置卡片请求网址:
    https://open.feishu.cn/app/{app_id}/botconf
    """
    body = await request.json()
    logger.info(f"[FeishuBot] 卡片回调原始数据: {json.dumps(body, ensure_ascii=False, default=str)}")

    # URL 验证
    if body.get("type") == "url_verification":
        challenge = body.get("challenge")
        logger.info(f"[FeishuBot] 卡片回调 URL 验证, challenge: {challenge}")
        return {"challenge": challenge}

    try:
        action = body.get("action", {})
        action_value = action.get("value", {})
        action_name = action.get("name", "")
        form_value = action.get("form_value", {})
        open_chat_id = body.get("open_chat_id", "")
        open_message_id = body.get("open_message_id", "")

        action_type = action_value.get("action", "")
        workflow_id = action_value.get("workflow_id", "") or form_value.get("workflow_id", "")
        confirm_type = action_value.get("confirm_type", "") or form_value.get("confirm_type", "")

        # 从 form_value 提取修改内容
        feedback = ""
        if isinstance(form_value, dict):
            feedback = form_value.get("modify_content", "").strip()

        # form submit 不携带按钮 value，通过按钮 name 判断操作类型
        if not action_type:
            if action_name == "confirm_btn":
                action_type = "modify" if feedback else "confirm"
            elif action_name == "modify_btn":
                action_type = "modify"
            elif action_name == "cancel_btn":
                action_type = "cancel"

        # 兼容 Card DSL 2.0：通过按钮 name 判断
        if not action_type:
            if action_name == "confirm_btn":
                action_type = "modify" if feedback else "confirm"
            elif action_name == "modify_btn":
                action_type = "modify"
            elif action_name == "cancel_btn":
                action_type = "cancel"

        logger.info(
            f"[FeishuBot] 收到卡片交互: action={action_type}, action_name={action_name}, "
            f"workflow_id={workflow_id}, confirm_type={confirm_type}, "
            f"feedback_length={len(feedback)}"
        )

        if not workflow_id:
            # 尝试通过 message_id 查找
            pending = feishu_message_service.get_pending_confirmation_by_message_id(open_message_id)
            if pending:
                workflow_id = pending.get("workflow_id", "")
                confirm_type = pending.get("confirm_type", confirm_type)

        if not workflow_id:
            return {"toast": {"type": "error", "content": "无法识别工作流，请刷新后重试"}}

        # ---------- 确认操作 ----------
        if action_type == "confirm":
            try:
                success = await workflow_manager.submit_confirmation(
                    workflow_id=workflow_id, confirmed=True, feedback=""
                )
                if not success:
                    raise RuntimeError("确认提交失败")
                feishu_message_service.clear_pending_confirmation(workflow_id)
                card = feishu_message_service.build_action_result_card(
                    workflow_id, "confirm", confirm_type
                )
                return {
                    "toast": {"type": "success", "content": "✅ 已确认，正在继续执行..."},
                    "card": {"type": "raw", "data": card},
                }
            except Exception as e:
                logger.error(f"[FeishuBot] 确认操作失败: {e}")
                return {"toast": {"type": "error", "content": f"确认失败: {e}"}}

        # ---------- 取消操作 ----------
        elif action_type == "cancel":
            try:
                success = await workflow_manager.submit_confirmation(
                    workflow_id=workflow_id, confirmed=False, feedback=""
                )
                if not success:
                    raise RuntimeError("取消提交失败")
                feishu_message_service.clear_pending_confirmation(workflow_id)
                card = feishu_message_service.build_action_result_card(
                    workflow_id, "cancel", confirm_type
                )
                return {
                    "toast": {"type": "success", "content": "❌ 已取消任务"},
                    "card": {"type": "raw", "data": card},
                }
            except Exception as e:
                logger.error(f"[FeishuBot] 取消操作失败: {e}")
                return {"toast": {"type": "error", "content": f"取消失败: {e}"}}

        # ---------- 修改操作 ----------
        elif action_type in ("modify", "show_modify_input"):
            if not feedback:
                return {"toast": {"type": "warning", "content": "✏️ 请先在输入框填写修改内容，再点击【修改】提交"}}

            if len(feedback) > 5000:
                return {"toast": {"type": "warning", "content": "✏️ 修改内容不能超过 5000 个字符"}}

            import re
            suspicious_patterns = [
                (r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', "包含脚本标签"),
                (r'javascript:', "包含 JavaScript 协议"),
                (r'on\w+\s*=', "包含事件处理器"),
            ]
            for pattern, desc in suspicious_patterns:
                if re.search(pattern, feedback, re.IGNORECASE):
                    return {"toast": {"type": "warning", "content": f"✏️ 输入内容不安全: {desc}，请重新输入"}}

            try:
                success = await workflow_manager.submit_confirmation(
                    workflow_id=workflow_id, confirmed=False, feedback=feedback
                )
                if not success:
                    raise RuntimeError("修改提交失败")
                feishu_message_service.clear_pending_confirmation(workflow_id)
                display_feedback = feedback[:50] + ("..." if len(feedback) > 50 else "")
                card = feishu_message_service.build_action_result_card(
                    workflow_id, "modify", confirm_type, extra_info=feedback
                )
                return {
                    "toast": {"type": "success", "content": f"✏️ 已提交修改意见: {display_feedback}"},
                    "card": {"type": "raw", "data": card},
                }
            except Exception as e:
                logger.error(f"[FeishuBot] 修改操作失败: {e}")
                return {"toast": {"type": "error", "content": f"修改失败: {e}"}}

        return {"toast": {"type": "error", "content": "无效的操作请求"}}

    except Exception as e:
        logger.error(f"[FeishuBot] 处理卡片回调失败: {e}", exc_info=True)
        return {"toast": {"type": "error", "content": "处理失败，请稍后重试"}}
