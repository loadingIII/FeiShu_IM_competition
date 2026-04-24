import asyncio
import json

from langchain_core.messages import HumanMessage, SystemMessage

from nodes.agent.llm.summary_llms import context_chain
from state.state import IMState
from nodes.agent.router_agent import router_agent
from utils.feishuUtils import feishu_api





async def router_node(state: IMState) -> IMState:
    """场景A：意图捕捉"""
    state["current_scene"] = "router_node"
    state["messages"].append("[router_node] 开始意图识别")

    # Step A1: 文本预处理
    cleaned_text = state["user_input"].replace("@Agent-Pilot", "").strip()

    # Step A2: 上下文增强（仅飞书IM来源）
    chat_context = ""
    if state["source"] == "feishu_im" and state.get("chat_id"):
        try:
            # 拉取群聊最近50条消息
            history_messages = await feishu_api.get_group_history_messages(state["chat_id"])
            print(history_messages)
            if history_messages:
                # 对历史消息做摘要
                chat_context = await context_chain.ainvoke({"history_messages": history_messages})
        except Exception as e:
            state["messages"].append(f"[router_node] 拉取群聊历史失败: {str(e)}")

    # Step A3: LLM意图识别
    res = await router_agent.ainvoke(input={"messages": [
        HumanMessage(content=cleaned_text),
        SystemMessage(content=chat_context)
    ]})

    intent_content = res["messages"][-1].content
    try:
        if isinstance(intent_content, str):
            intent = json.loads(intent_content)
        else:
            intent = intent_content
    except (json.JSONDecodeError, TypeError):
        intent = {"intent_type": intent_content}

    state["intent"] = intent
    state["chat_context"] = chat_context
    state["messages"].append(f"[router_node] 识别到意图：{intent['intent_type']}")
    return state


if __name__ == "__main__":
    state = IMState(
        user_id="123",
        user_input="@Agent-Pilot帮我制作一下这个月的总结PPT",
        source="feishu_im",
        messages=[],
        chat_id="oc_81881e331cd9d7f921771aa884b96742"
    )
    res =asyncio.run(router_node(state))
    print(res)


