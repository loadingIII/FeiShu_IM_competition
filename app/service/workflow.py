import uuid
import asyncio
import time
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core_workflow"))
from state.state import IMState
from graph.graph import build_workflow
from app.model import WorkflowInstance, WorkflowStatus
from app.crud import workflow_crud
from app.service.confirmation import confirmation_service
from app.service.websocket import ws_manager
from app.service.feishu_message_service import feishu_message_service
from utils.logger_handler import logger


NODE_TO_SCENE = {
    "router_node": "A",
    "plan_node": "B",
    "text_generate_node": "C",
    "generate_doc_content": "C",
    "ppt_generate_node": "D",
    "multi_terminal_node": "E",
    "delivery_node": "F",
}


def map_scene(node_name: str) -> str:
    return NODE_TO_SCENE.get(node_name, "")


class WorkflowManager:
    """工作流生命周期管理器"""

    def __init__(self):
        confirmation_service.enable_api_mode()

    async def create_workflow(
        self,
        user_input: str,
        user_id: str = "api_user",
        source: str = "h5",
        chat_id: str = "",
    ) -> str:
        """创建工作流实例并启动执行"""
        workflow_id = str(uuid.uuid4())

        initial_state: IMState = {
            "workflow_id": workflow_id,
            "user_id": user_id,
            "user_input": user_input,
            "source": source,
            "chat_id": chat_id,
            "intent": None,
            "chat_context": "",
            "task_plan": None,
            "doc_outline": None,
            "doc_outline_feedback": None,
            "doc_outline_confirmed": False,
            "doc_content": None,
            "doc_content_feedback": None,
            "doc_content_confirmed": False,
            "doc_url": "",
            "ppt_content": None,
            "ppt_url": "",
            "ppt_outline": None,
            "ppt_outline_feedback": None,
            "ppt_outline_confirmed": False,
            "ppt_content_feedback": None,
            "ppt_content_confirmed": False,
            "ppt_id": None,
            "delivery": None,
            "messages": [],
            "current_scene": "",
            "current_scene_before_confirm": None,
            "need_confirm": False,
            "confirmed": False,
            "cancelled": False,
            "confirm_type": None,
            "error": None,
            "plan_feedback": None,
            "previous_plan": None,
            "doc_generation_completed": False,
            "ppt_generation_completed": False,
            "chat_history": [],
            "chat_intent_detected": None,
        }

        instance = WorkflowInstance(workflow_id, initial_state)
        await workflow_crud.create(workflow_id, instance)

        instance._task = asyncio.create_task(self._run_workflow(instance))
        instance.status = WorkflowStatus.RUNNING

        logger.info(f"[WorkflowManager] 创建工作流 {workflow_id}: {user_input[:50]}")
        return workflow_id

    async def _run_workflow(self, instance: WorkflowInstance):
        """后台执行工作流，通过 WebSocket 广播实时状态"""
        workflow_id = instance.workflow_id
        prev_scene = ""
        start_time = time.time()

        try:
            workflow = build_workflow()

            await ws_manager.broadcast_workflow_created(workflow_id, {
                "id": workflow_id,
                "status": "running",
                "userIntent": instance.state.get("user_input", ""),
                "createdAt": int(instance.created_at * 1000),
            })

            async for event in workflow.astream(instance.state, stream_mode="values"):
                current_scene = event.get("current_scene", "")

                if current_scene and current_scene != prev_scene:
                    if prev_scene:
                        prev_scene_id = map_scene(prev_scene)
                        if prev_scene_id:
                            await ws_manager.broadcast_scene_completed(
                                workflow_id, prev_scene_id,
                                duration=int(time.time() - start_time),
                            )

                    scene_id = map_scene(current_scene)
                    if scene_id:
                        await ws_manager.broadcast_scene_started(workflow_id, scene_id)
                        start_time = time.time()

                    prev_scene = current_scene

                messages = event.get("messages", [])
                if messages:
                    last_msg = messages[-1] if isinstance(messages, list) else messages
                    if isinstance(last_msg, str):
                        level = "warn" if "失败" in last_msg or "错误" in last_msg else "info"
                        await ws_manager.broadcast_log(workflow_id, level, last_msg)

                instance.state = event

            result = instance.state
            chat_id = instance.state.get("chat_id", "")
            source = instance.state.get("source", "")

            if result.get("cancelled", False):
                instance.status = WorkflowStatus.CANCELLED
                await ws_manager.broadcast_workflow_cancelled(workflow_id)
                # 如果是飞书来源，发送取消通知
                if source == "feishu_bot" and chat_id:
                    await feishu_message_service.send_text_notification(
                        chat_id=chat_id,
                        message=f"❌ 工作流 {workflow_id[:8]}... 已取消"
                    )
            else:
                instance.status = WorkflowStatus.COMPLETED
                instance.result = result
                delivery = result.get("delivery")
                await ws_manager.broadcast_workflow_completed(workflow_id, delivery)

                # 如果是飞书来源，发送结果到飞书
                if source == "feishu_bot" and chat_id:
                    await feishu_message_service.send_workflow_result(
                        chat_id=chat_id,
                        workflow_id=workflow_id,
                        result=result
                    )

            logger.info(f"[WorkflowManager] 工作流 {workflow_id} 完成")

        except asyncio.CancelledError:
            instance.status = WorkflowStatus.CANCELLED
            instance.error = "工作流被取消"
            await ws_manager.broadcast_workflow_cancelled(workflow_id)
            logger.warning(f"[WorkflowManager] 工作流 {workflow_id} 被取消")
        except Exception as e:
            instance.status = WorkflowStatus.ERROR
            instance.error = str(e)
            await ws_manager.broadcast_workflow_failed(workflow_id, str(e))
            logger.error(f"[WorkflowManager] 工作流 {workflow_id} 异常: {e}")
            if "chat_context" in instance.state and isinstance(instance.state["chat_context"], Exception):
                instance.state["chat_context"] = ""
        finally:
            instance.updated_at = time.time()

    async def get_workflow(self, workflow_id: str) -> Optional[WorkflowInstance]:
        return await workflow_crud.get(workflow_id)

    async def submit_confirmation(
        self,
        workflow_id: str,
        confirmed: bool,
        feedback: str = "",
    ) -> bool:
        """提交确认结果"""
        instance = await self.get_workflow(workflow_id)
        if not instance:
            return False

        pending = confirmation_service.get_pending(workflow_id)
        if not pending:
            return False

        confirm_type = pending.confirm_type
        if not confirmed and feedback:
            key_map = {
                "task_plan": "plan_feedback",
                "doc_outline": "outline_feedback",
                "ppt_outline": "ppt_outline_feedback",
                "ppt_content": "ppt_content_feedback",
            }
            state_key = key_map.get(confirm_type, "plan_feedback")
            instance.state[state_key] = feedback
            instance.state["confirmed"] = False
            instance.state["cancelled"] = False
        elif confirmed:
            instance.state["confirmed"] = True
            instance.state["cancelled"] = False
        else:
            instance.state["confirmed"] = False
            instance.state["cancelled"] = True

        instance.state["need_confirm"] = False
        instance.status = WorkflowStatus.RUNNING
        instance.updated_at = time.time()

        confirmation_service.submit_confirmation(workflow_id, confirmed, feedback)

        action = "confirm" if confirmed else ("modify" if feedback else "cancel")
        await ws_manager.broadcast_confirm_result(workflow_id, action)

        logger.info(f"[WorkflowManager] 工作流 {workflow_id} 确认: confirmed={confirmed}")
        return True

    async def cancel_workflow(self, workflow_id: str) -> bool:
        """取消工作流"""
        instance = await self.get_workflow(workflow_id)
        if not instance:
            return False

        if instance._task and not instance._task.done():
            instance._task.cancel()

        confirmation_service.cancel_pending(workflow_id)
        instance.status = WorkflowStatus.CANCELLED
        instance.error = "用户手动取消"
        instance.updated_at = time.time()
        await ws_manager.broadcast_workflow_cancelled(workflow_id)
        logger.info(f"[WorkflowManager] 工作流 {workflow_id} 手动取消")
        return True

    async def list_workflows(self, limit: int = 20) -> list:
        """按创建时间倒序列出工作流"""
        instances = await workflow_crud.list_all(limit=limit)
        return [inst.to_dict() for inst in instances]


workflow_manager = WorkflowManager()
