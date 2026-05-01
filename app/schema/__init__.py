from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List


class ConfirmAction(str, Enum):
    confirm = "confirm"
    modify = "modify"
    cancel = "cancel"


class CreateWorkflowRequest(BaseModel):
    user_input: str = Field(..., description="用户输入文本", min_length=1, max_length=5000)
    user_id: str = Field("api_user", description="用户ID")
    source: str = Field("h5", description="请求来源: feishu_im / h5")
    chat_id: str = Field("", description="飞书群聊ID")


class CreateWorkflowResponse(BaseModel):
    workflow_id: str
    status: str
    message: str = "工作流已启动"


class ConfirmRequest(BaseModel):
    action: ConfirmAction = Field(..., description="确认操作: confirm(确认执行), modify(修改重试), cancel(取消)")
    feedback: str = Field("", description="修改意见（action=modify 时必填）")


class ConfirmResponse(BaseModel):
    workflow_id: str
    status: str
    message: str


class WorkflowInfo(BaseModel):
    workflow_id: str
    status: str
    created_at: float
    elapsed_seconds: float
    current_scene: str
    error: Optional[str] = None
    pending_confirmation: Optional[Dict[str, Any]] = None
    delivery: Optional[Dict[str, Any]] = None


class WorkflowListResponse(BaseModel):
    total: int
    workflows: List[WorkflowInfo]


class ErrorResponse(BaseModel):
    detail: str


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户发送的聊天消息", min_length=1, max_length=5000)


class ChatResponse(BaseModel):
    workflow_id: str
    message: str = "消息已接收"
