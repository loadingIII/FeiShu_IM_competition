"""闲聊节点

当用户意图不明确（clarification_needed / knowledge_qa / 低置信度）时，
进入此节点与用户进行自由对话，引导用户表达明确的工作需求。
"""
from langchain_core.messages import HumanMessage
from nodes.agent.llm.chat_llms import chat_llm
from nodes.agent.prompt.chat_prompt import chat_prompt
from state.state import IMState
from utils.logger_handler import logger


async def process_message(state: IMState, user_input: str) -> IMState:
    """处理单条用户消息，生成回复，检测意图"""
    chat_history = state.get("chat_history", []) or []

    # 记录用户消息到历史
    chat_history.append({"role": "user", "content": user_input})

    # 构建历史字符串
    history_lines = []
    for msg in chat_history[-10:-1]:
        role = "用户" if msg["role"] == "user" else "助手"
        history_lines.append(f"{role}: {msg['content']}")
    history_str = "\n".join(history_lines) or "暂无历史对话"

    prompt = chat_prompt.format(
        chat_history=history_str,
        user_message=user_input,
    )

    res = await chat_llm.ainvoke([HumanMessage(content=prompt)])
    reply = res.content.strip()

    # 检查意图标记 [INTENT_DETECTED:xxx]
    intent_marker = "[INTENT_DETECTED:"
    if intent_marker in reply:
        try:
            start = reply.index(intent_marker) + len(intent_marker)
            end = reply.index("]", start)
            detected = reply[start:end].strip().lower()
            state["chat_intent_detected"] = detected
            reply = reply.replace(f"{intent_marker}{reply[start:end]}]", "").strip()
            logger.info(f"[chat_node] 检测到意图: {detected}")
        except (ValueError, IndexError):
            state["chat_intent_detected"] = None
    else:
        state["chat_intent_detected"] = None

    # 记录助手回复
    chat_history.append({"role": "assistant", "content": reply})
    state["chat_history"] = chat_history

    # 广播回复到前端
    try:
        from app.service.websocket import ws_manager
        import time
        await ws_manager.broadcast_chat_message(state["workflow_id"], {
            "id": f"chat_{int(time.time() * 1000)}",
            "role": "assistant",
            "content": reply,
            "timestamp": int(time.time() * 1000),
        })
    except ImportError:
        pass

    return state


async def chat_node(state: IMState) -> IMState:
    """闲聊节点：处理用户消息并回复，不阻塞等待后续输入"""
    state["current_scene"] = "chat_node"
    state["messages"].append("[chat_node] 进入闲聊模式")

    # 获取用户输入
    user_input = state.get("user_input", "").strip()
    if not user_input:
        state["messages"].append("[chat_node] 无用户输入，退出")
        logger.info("[chat_node] 无用户输入，退出")
        return state

    # 清空避免重复处理
    state["user_input"] = ""

    logger.info(f"[chat_node] 处理消息: {user_input[:50]}")
    state["messages"].append("[chat_node] 处理消息")
    state = await process_message(state, user_input)

    # process_message 已经更新了 chat_intent_detected
    # 由 graph 的 route_after_chat 决定下一步路由
    return state
