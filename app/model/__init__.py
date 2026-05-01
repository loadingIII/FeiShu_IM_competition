import enum
import time
import asyncio
from typing import Optional, Dict, Any
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core_workflow"))
from state.state import IMState


class WorkflowStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class WorkflowInstance:
    """单个工作流实例"""

    def __init__(self, workflow_id: str, initial_state: IMState):
        self.workflow_id = workflow_id
        self.state: IMState = initial_state
        self.status = WorkflowStatus.PENDING
        self.error: Optional[str] = None
        self.result: Optional[dict] = None
        self.created_at = time.time()
        self.updated_at = time.time()
        self._task: Optional[asyncio.Task] = None

    def to_dict(self) -> dict:
        """序列化为 API 可返回的摘要信息"""
        from app.service.confirmation import confirmation_service

        now = time.time()
        elapsed = now - self.created_at

        terminal_states = {WorkflowStatus.ERROR, WorkflowStatus.CANCELLED, WorkflowStatus.COMPLETED}
        is_terminal = self.status in terminal_states

        if is_terminal:
            status = self.status.value
        else:
            pending = confirmation_service.get_pending(self.workflow_id)
            status = WorkflowStatus.AWAITING_CONFIRMATION.value if pending else self.status.value

        info = {
            "workflow_id": self.workflow_id,
            "status": status,
            "created_at": self.created_at,
            "elapsed_seconds": round(elapsed, 1),
            "current_scene": self.state.get("current_scene", ""),
        }

        if self.error:
            info["error"] = self.error

        if not is_terminal:
            pending = confirmation_service.get_pending(self.workflow_id)
            if pending:
                info["pending_confirmation"] = {
                    "type": pending.confirm_type,
                    "display_data": pending.display_data,
                }

        if self.status == WorkflowStatus.COMPLETED and self.result:
            delivery = self.result.get("delivery")
            if delivery:
                info["delivery"] = delivery

        return info


class ConfirmationRequest:
    """封装一次确认请求的上下文"""

    def __init__(self, workflow_id: str, confirm_type: str, display_data: dict, formatted_text: str):
        self.workflow_id = workflow_id
        self.confirm_type = confirm_type
        self.display_data = display_data
        self.formatted_text = formatted_text
