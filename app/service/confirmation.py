import asyncio
from typing import Optional, Dict, Any
from app.model import ConfirmationRequest


class ConfirmationService:
    """异步确认服务：工作流等待确认时挂起，API 提交时唤醒"""

    def __init__(self):
        self._pending: Dict[str, ConfirmationRequest] = {}
        self._events: Dict[str, asyncio.Event] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self.api_mode: bool = False

    def enable_api_mode(self):
        """切换到 API 模式"""
        self.api_mode = True

    def set_pending(self, workflow_id: str, req: ConfirmationRequest):
        """注册一个待确认请求"""
        self._pending[workflow_id] = req
        self._events[workflow_id] = asyncio.Event()

    async def wait_for_confirmation(self, workflow_id: str, timeout: float = 300.0) -> dict:
        """等待用户确认，超时将自动确认"""
        event = self._events.get(workflow_id)
        if not event:
            raise ValueError(f"workflow {workflow_id} 没有待确认项")

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return {"confirmed": True, "feedback": "", "timeout": True}

        result = self._results.pop(workflow_id, {"confirmed": True, "feedback": "", "timeout": False})
        self._pending.pop(workflow_id, None)
        self._events.pop(workflow_id, None)
        return result

    def submit_confirmation(self, workflow_id: str, confirmed: bool, feedback: str = ""):
        """提交确认结果，唤醒等待的工作流"""
        self._results[workflow_id] = {"confirmed": confirmed, "feedback": feedback, "timeout": False}
        event = self._events.get(workflow_id)
        if event:
            event.set()

    def get_pending(self, workflow_id: str) -> Optional[ConfirmationRequest]:
        """查询当前待确认请求"""
        return self._pending.get(workflow_id)

    def cancel_pending(self, workflow_id: str):
        """取消等待（工作流异常时清理）"""
        self._pending.pop(workflow_id, None)
        self._results.pop(workflow_id, None)
        event = self._events.pop(workflow_id, None)
        if event:
            event.set()


confirmation_service = ConfirmationService()
