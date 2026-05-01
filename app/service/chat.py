"""Chat 等待服务

工作流中的 chat_node 通过此服务等待用户消息，
API 端点通过此服务将用户输入传递给等待中的节点。
"""
import asyncio
from typing import Optional, Dict
from utils.logger_handler import logger


class ChatService:
    """管理聊天消息的异步等待/通知"""

    def __init__(self):
        self._events: Dict[str, asyncio.Event] = {}
        self._messages: Dict[str, str] = {}

    def set_waiting(self, workflow_id: str):
        """标记工作流正在等待用户输入"""
        self._events[workflow_id] = asyncio.Event()
        logger.info(f"[ChatService] 工作流 {workflow_id} 等待用户输入")

    async def wait_for_message(self, workflow_id: str, timeout: float = 300.0) -> str:
        """等待用户消息，返回消息文本"""
        event = self._events.get(workflow_id)
        if not event:
            raise ValueError(f"工作流 {workflow_id} 没有等待中的 chat")

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return ""

        msg = self._messages.pop(workflow_id, "")
        self._events.pop(workflow_id, None)
        return msg

    def submit_message(self, workflow_id: str, message: str):
        """提交用户消息，唤醒等待的 chat_node"""
        self._messages[workflow_id] = message
        event = self._events.get(workflow_id)
        if event:
            event.set()
            logger.info(f"[ChatService] 工作流 {workflow_id} 收到用户消息")

    def cancel_waiting(self, workflow_id: str):
        """取消等待（清理）"""
        self._messages.pop(workflow_id, None)
        event = self._events.pop(workflow_id, None)
        if event:
            event.set()


chat_service = ChatService()
