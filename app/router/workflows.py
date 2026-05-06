from fastapi import APIRouter, HTTPException
from app.schema import (
    ConfirmAction,
    CreateWorkflowRequest,
    CreateWorkflowResponse,
    ConfirmRequest,
    ConfirmResponse,
    WorkflowInfo,
    WorkflowListResponse,
)
from app.service import workflow_manager, confirmation_service, ws_manager

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", response_model=CreateWorkflowResponse, status_code=201)
async def create_workflow(req: CreateWorkflowRequest):
    """启动一个新的工作流"""
    workflow_id = await workflow_manager.create_workflow(
        user_input=req.user_input,
        user_id=req.user_id,
        source=req.source,
        chat_id=req.chat_id,
    )
    return CreateWorkflowResponse(
        workflow_id=workflow_id,
        status="running",
        message="工作流已启动",
    )


@router.get("/{workflow_id}", response_model=WorkflowInfo)
async def get_workflow(workflow_id: str):
    """查询工作流状态"""
    instance = await workflow_manager.get_workflow(workflow_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"工作流 {workflow_id} 不存在")
    return instance.to_dict()


@router.post("/{workflow_id}/confirm", response_model=ConfirmResponse)
async def confirm_workflow(workflow_id: str, req: ConfirmRequest):
    """提交确认结果（确认执行/修改重试/取消任务）"""
    instance = await workflow_manager.get_workflow(workflow_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"工作流 {workflow_id} 不存在")

    if not confirmation_service.get_pending(workflow_id):
        raise HTTPException(status_code=400, detail="工作流当前无需确认")

    if req.action == ConfirmAction.confirm:
        confirmed, feedback, cancelled = True, "", False
    elif req.action == ConfirmAction.modify:
        if not req.feedback:
            raise HTTPException(status_code=422, detail="action=modify 时 feedback 不能为空")
        confirmed, feedback, cancelled = False, req.feedback, False
    else:
        confirmed, feedback, cancelled = False, "", True

    success = await workflow_manager.submit_confirmation(
        workflow_id=workflow_id,
        confirmed=confirmed,
        feedback=feedback,
    )
    if not success:
        raise HTTPException(status_code=409, detail="确认提交失败，请稍后重试")

    msg = {
        ConfirmAction.confirm: "已确认，继续执行",
        ConfirmAction.modify: "已提交修改意见，重新生成",
        ConfirmAction.cancel: "已取消",
    }[req.action]

    return ConfirmResponse(
        workflow_id=workflow_id,
        status="cancelled" if cancelled else "running",
        message=msg,
    )


@router.post("/{workflow_id}/cancel", response_model=ConfirmResponse)
async def cancel_workflow(workflow_id: str):
    """强制取消工作流"""
    success = await workflow_manager.cancel_workflow(workflow_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"工作流 {workflow_id} 不存在")

    return ConfirmResponse(
        workflow_id=workflow_id,
        status="cancelled",
        message="工作流已取消",
    )


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(limit: int = 20):
    """列出最近的工作流"""
    workflows = await workflow_manager.list_workflows(limit=limit)
    return WorkflowListResponse(total=len(workflows), workflows=workflows)
