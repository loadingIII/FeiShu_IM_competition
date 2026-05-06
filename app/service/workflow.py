import uuid
import asyncio
import time
import sys
import json
from pathlib import Path
from typing import Optional, Dict

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core_workflow"))
from state.state import IMState
from graph.graph import build_workflow
from app.model import WorkflowInstance, WorkflowStatus
from app.crud import workflow_crud
from app.service.confirmation import confirmation_service
from app.service.websocket import ws_manager
from app.service.feishu_message_service import feishu_message_service
from utils.logger_handler import logger
from utils.feishuUtils import feishu_api
from nodes.agent.llm.router_llms import router_llm
from nodes.agent.chat_agent import chat_agent
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage


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
        self._chat_sessions: Dict[str, dict] = {}  # key: user标识, value: {chat_history, last_activity}

    async def handle_message(
        self,
        user_input: str,
        user_id: str,
        source: str,
        chat_id: str = "",
        sender_open_id: str = "",
    ) -> None:
        """统一消息入口：轻量意图判断，闲聊直接回复，任务才创建工作流"""
        try:
            # 1. 检查是否有正在进行的 workflow 需要确认
            active_wf = await self._find_active_workflow(user_id, source)
            if active_wf:
                pending = confirmation_service.get_pending(active_wf)
                if pending:
                    await self.submit_confirmation(
                        workflow_id=active_wf,
                        confirmed=False,
                        feedback=user_input,
                    )
                    logger.info(f"[handle_message] 修改意见已提交到工作流 {active_wf}")
                    return

            # 2. 轻量意图判断
            intent_result = await router_llm.ainvoke([HumanMessage(content=user_input)])
            intent_text = intent_result.content.strip()

            try:
                intent = json.loads(intent_text) if isinstance(intent_text, str) else intent_text
            except (json.JSONDecodeError, TypeError):
                intent = {"intent_type": "clarification_needed", "confidence": 0.3}

            intent_type = intent.get("intent_type", "clarification_needed")
            confidence = intent.get("confidence", 0.0)

            # 3. 闲聊/知识问答 → 直接用 chat_llm 回复
            if intent_type in ("clarification_needed", "knowledge_qa") or confidence < 0.5:
                await self._handle_chat(user_input, user_id, source, chat_id, sender_open_id)
                return

            # 4. 任务意图 → 创建工作流
            await self.create_workflow(
                user_input=user_input,
                user_id=user_id,
                source=source,
                chat_id=chat_id,
            )

        except Exception as e:
            logger.error(f"[handle_message] 处理消息失败: {e}", exc_info=True)

    async def _handle_chat(
        self,
        user_input: str,
        user_id: str,
        source: str,
        chat_id: str,
        sender_open_id: str,
    ) -> None:
        """处理闲聊消息：用 chat_llm 回复，检测意图标记"""
        session_key = f"{source}:{sender_open_id or user_id}"
        session = self._chat_sessions.get(session_key, {"chat_history": [], "last_activity": 0})
        chat_history = session["chat_history"]

        chat_history.append({"role": "user", "content": user_input})

        # 将 dict 历史转为 LangChain 消息对象
        langchain_messages = []
        for msg in chat_history[:-1]:
            if msg["role"] == "user":
                langchain_messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                langchain_messages.append(AIMessage(content=msg["content"]))

        # 构建完整消息：system指令 + 历史 + 当前输入
        system_prompt = """你是一个智能办公助手 Agent-Pilot 的闲聊 Agent。你的职责是与用户进行自然、友好的对话。

## 你的能力

1. **闲聊陪伴**：与用户聊天、回答问题、提供建议
2. **意图引导**：在对话中温和地引导用户表达工作需求
3. **可协助的工作类型**：
   - 生成飞书文档（doc_creation）
   - 制作演示文稿/PPT（ppt_creation）
   - 整理会议纪要（meeting_summary）

## 你的行为准则

1. 始终保持友好、热情的态度
2. 回复简洁自然，不要过于啰嗦
3. 如果用户表达了明确的工作需求（写文档、做PPT、整理纪要等），请在回复结尾添加标记 `[INTENT_DETECTED: 意图类型]`
4. 如果用户只是在闲聊，正常回复即可，不要强行引导
5. 如果用户需求模糊，可以适当询问以澄清"""

        messages = [SystemMessage(content=system_prompt)] + langchain_messages + [HumanMessage(content=user_input)]
        result = await chat_agent.ainvoke({"messages": messages})
        reply = result["messages"][-1].content.strip()

        # 检查意图标记 [INTENT_DETECTED:xxx]
        intent_marker = "[INTENT_DETECTED:"
        if intent_marker in reply:
            try:
                start = reply.index(intent_marker) + len(intent_marker)
                end = reply.index("]", start)
                detected = reply[start:end].strip().lower()
                reply = reply.replace(f"{intent_marker}{detected}]", "").strip()
                logger.info(f"[handle_message] 闲聊中检测到意图: {detected}")
                # 检测到任务意图 → 创建工作流
                await self.create_workflow(
                    user_input=user_input,
                    user_id=user_id,
                    source=source,
                    chat_id=chat_id,
                    chat_history=chat_history,
                )
                return
            except (ValueError, IndexError):
                pass

        # 记录回复
        chat_history.append({"role": "assistant", "content": reply})
        self._chat_sessions[session_key] = {
            "chat_history": chat_history[-20:],  # 保留最近20条
            "last_activity": time.time(),
        }

        # 发送文本消息
        if chat_id:
            try:
                await feishu_api.send_text_message(
                    receive_id=chat_id, text=reply, receive_id_type="chat_id"
                )
            except Exception as e:
                logger.warning(f"[handle_message] 发送闲聊回复失败: {e}")

    async def _find_active_workflow(self, user_id: str, source: str) -> Optional[str]:
        """查找用户当前活跃的工作流"""
        try:
            workflows = await self.list_workflows(limit=50)
            for wf in workflows:
                if (wf.get("user_id") == user_id and
                    wf.get("source") == source and
                    wf.get("status") in ["running", "waiting_input", "awaiting_confirmation"]):
                    return wf.get("workflow_id")
        except Exception as e:
            logger.error(f"[handle_message] 查找活跃工作流失败: {e}")
        return None

    async def create_workflow(
        self,
        user_input: str,
        user_id: str = "api_user",
        source: str = "h5",
        chat_id: str = "",
        chat_history: Optional[list] = None,
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
            "outline_feedback": None,
            "doc_content": None,
            "doc_url": "",
            "ppt_outline": None,
            "ppt_outline_feedback": None,
            "ppt_content": None,
            "ppt_content_feedback": None,
            "ppt_url": "",
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
            "chat_history": chat_history or [],
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
