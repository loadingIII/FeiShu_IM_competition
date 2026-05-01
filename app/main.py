import json
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from app.router import workflow_router
from app.router import feishu_bot
from app.service import confirmation_service, ws_manager, workflow_manager, chat_service
from app.service.feishu_ws_manager import feishu_ws_manager
from utils.logger_handler import logger

description = """
Agent-Pilot AI 工作流 API

基于 LangGraph 构建的智能助手工作流，支持：
- **文档生成**：自动生成结构化文档并发布到飞书
- **PPT 生成**：自动生成专业演示文稿
- **组合任务**：同时生成文档和 PPT
- **飞书长连接**：支持 WebSocket 长连接接收飞书事件
"""


async def handle_feishu_message(chat_id: str, sender_open_id: str, message: str):
    """处理飞书长连接收到的消息"""
    logger.info(f"[FeishuWS] handle_feishu_message 被调用: chat_id={chat_id}, sender={sender_open_id}, message={message[:50]}...")
    try:
        # 获取或创建工作流
        workflow_id = await get_or_create_workflow(chat_id, sender_open_id)
        logger.info(f"[FeishuWS] get_or_create_workflow 返回: {workflow_id}")

        if workflow_id:
            # 检查工作流是否正在等待修改意见
            from app.service.confirmation import confirmation_service
            pending = confirmation_service.get_pending(workflow_id)
            if pending:
                # 工作流在等待确认，用户发送的消息视为修改意见
                logger.info(f"[FeishuWS] 工作流 {workflow_id} 有待确认项，将消息作为修改意见提交")
                await workflow_manager.submit_confirmation(
                    workflow_id=workflow_id,
                    confirmed=False,
                    feedback=message
                )
                logger.info(f"[FeishuWS] 修改意见已提交到工作流 {workflow_id}")
            else:
                # 将消息提交给工作流
                chat_service.submit_message(workflow_id, message)
                logger.info(f"[FeishuWS] 消息已提交到工作流 {workflow_id}")
        else:
            # 如果没有活跃工作流，创建新工作流
            logger.info(f"[FeishuWS] 没有活跃工作流，创建新工作流")
            workflow_id = await workflow_manager.create_workflow(
                user_input=message,
                user_id=sender_open_id,
                source="feishu_bot",
                chat_id=chat_id,
            )
            logger.info(f"[FeishuWS] 创建新工作流 {workflow_id}")
    except Exception as e:
        logger.error(f"[FeishuWS] 处理用户消息失败: {e}", exc_info=True)


async def handle_feishu_card_action(workflow_id: str, action: str, feedback: str = ""):
    """处理飞书卡片交互事件

    Args:
        workflow_id: 工作流 ID
        action: 操作类型 (confirm/modify/cancel)
        feedback: 修改意见

    Raises:
        ValueError: 当参数验证失败时
        RuntimeError: 当工作流状态异常时
    """
    try:
        if not workflow_id:
            raise ValueError("工作流 ID 不能为空")

        if action not in ("confirm", "modify", "cancel"):
            raise ValueError(f"无效的操作类型: {action}")

        if action == "confirm":
            success = await workflow_manager.submit_confirmation(
                workflow_id=workflow_id,
                confirmed=True,
                feedback=""
            )
            if not success:
                raise RuntimeError("确认提交失败，工作流可能不存在或已完成")
            logger.info(f"[FeishuWS] 用户确认工作流: {workflow_id}")

        elif action == "cancel":
            success = await workflow_manager.submit_confirmation(
                workflow_id=workflow_id,
                confirmed=False,
                feedback=""
            )
            if not success:
                raise RuntimeError("取消提交失败，工作流可能不存在或已完成")
            logger.info(f"[FeishuWS] 用户取消工作流: {workflow_id}")

        elif action == "modify":
            validated_feedback = _validate_modify_feedback(feedback)
            success = await workflow_manager.submit_confirmation(
                workflow_id=workflow_id,
                confirmed=False,
                feedback=validated_feedback
            )
            if not success:
                raise RuntimeError("修改提交失败，工作流可能不存在或已完成")
            logger.info(f"[FeishuWS] 用户要求修改工作流: {workflow_id}, feedback={validated_feedback[:50]}...")

    except ValueError as e:
        logger.warning(f"[FeishuWS] 卡片交互参数错误: {e}")
        raise
    except Exception as e:
        logger.error(f"[FeishuWS] 处理卡片交互失败: {e}")
        raise RuntimeError(f"处理失败: {e}") from e


def _validate_modify_feedback(feedback: str) -> str:
    """验证并清理修改意见输入

    Args:
        feedback: 用户输入的修改意见

    Returns:
        str: 清理后的修改意见

    Raises:
        ValueError: 当输入不合法时
    """
    if not feedback or not isinstance(feedback, str):
        raise ValueError("修改意见不能为空")

    feedback = feedback.strip()

    if len(feedback) < 1:
        raise ValueError("修改意见不能为空")

    if len(feedback) > 5000:
        raise ValueError("修改意见不能超过 5000 个字符")

    import re

    suspicious_patterns = [
        (r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', "包含脚本标签"),
        (r'javascript:', "包含 JavaScript 协议"),
        (r'on\w+\s*=', "包含事件处理器"),
        (r'data:text/html', "包含 Data URI"),
    ]

    for pattern, desc in suspicious_patterns:
        if re.search(pattern, feedback, re.IGNORECASE):
            raise ValueError(f"输入内容不安全: {desc}，请重新输入")

    return feedback


async def get_or_create_workflow(chat_id: str, user_id: str) -> str:
    """获取用户当前的活跃工作流，如果没有则返回 None"""
    try:
        workflows = await workflow_manager.list_workflows(limit=50)

        for wf in workflows:
            if (wf.get("user_id") == user_id and
                wf.get("source") == "feishu_bot" and
                wf.get("status") in ["running", "waiting_input", "awaiting_confirmation"]):
                return wf.get("workflow_id")
    except Exception as e:
        logger.error(f"[FeishuWS] 获取工作流失败: {e}")

    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时开启 API 模式和飞书长连接"""
    confirmation_service.enable_api_mode()
    logger.info("[FastAPI] Agent-Pilot API 已启动，确认服务切换为 API 模式")

    # 启动飞书长连接客户端（如果配置了环境变量）
    import os
    if os.getenv("FEISHU_APP_ID") and os.getenv("FEISHU_APP_SECRET"):
        feishu_ws_manager.set_message_callback(handle_feishu_message)
        feishu_ws_manager.set_card_callback(handle_feishu_card_action)
        feishu_ws_manager.start(asyncio.get_event_loop())
        logger.info("[FastAPI] 飞书长连接客户端已启动")
    else:
        logger.warning("[FastAPI] 未配置飞书应用凭证，长连接客户端未启动")

    yield

    # 关闭时停止长连接
    feishu_ws_manager.stop()
    logger.info("[FastAPI] 飞书长连接客户端已停止")


app = FastAPI(
    title="Agent-Pilot API",
    description=description,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflow_router)
app.include_router(feishu_bot.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "agent-pilot"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

            elif msg_type == "subscribe":
                workflow_id = msg.get("workflowId")
                if workflow_id:
                    await ws_manager.subscribe(websocket, workflow_id)
                    logger.info(f"[WebSocket] 订阅工作流: {workflow_id}")

            elif msg_type == "unsubscribe":
                workflow_id = msg.get("workflowId")
                if workflow_id:
                    await ws_manager.unsubscribe(websocket, workflow_id)

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"[WebSocket] 异常: {e}")
        ws_manager.disconnect(websocket)
