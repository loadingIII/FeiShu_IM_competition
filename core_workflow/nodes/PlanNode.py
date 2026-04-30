import asyncio
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from nodes.agent.plan_agent import plan_agent
from state.state import IMState
from utils.logger_handler import logger


user_content_prompt = """根据以下意图分析结果，规划任务执行分支：
意图：{intent}
【用户修改意见】
####
{plan_feedback}
####

【之前的计划（供参考）】
####
{previous_plan}
####

请根据用户的修改意见，重新制定任务计划。注意避免之前计划中的问题，按照用户的要求进行调整。
"""
def extract_json(content: str) -> str:
    """从 LLM 返回内容中提取 JSON"""
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if json_match:
        return json_match.group(1).strip()
    return content.strip()


def build_planning_messages(state: IMState) -> list:
    """构建规划任务的消息列表"""
    chat_context = state["chat_context"]
    intent = state["intent"]
    
    messages = [
        SystemMessage(content=f"群聊历史信息摘要：{chat_context}"),
    ]
    
    # 检查是否有用户反馈（重新规划的情况）
    plan_feedback = state.get("plan_feedback")
    previous_plan = state.get("previous_plan")
    
    if plan_feedback and previous_plan:
        # 用户要求修改，需要包含反馈和之前的计划
        user_content = user_content_prompt.format(
            intent=intent,
            plan_feedback=plan_feedback,
            previous_plan=json.dumps(previous_plan, ensure_ascii=False, indent=2))

        logger.info(f"[plan_node] 重新规划，用户反馈: {plan_feedback}")
        state["messages"].append(f"[plan_node] 重新规划任务，用户反馈: {plan_feedback}")
    else:
        # 首次规划
        user_content = f"根据以下意图分析结果，规划任务执行分支：{intent}"
        logger.info("[plan_node] 首次任务规划")
        state["messages"].append("[plan_node] 首次任务规划")
    
    messages.append(HumanMessage(content=user_content))
    return messages


async def plan_node(state: IMState) -> IMState:
    """场景B：任务规划"""
    state["current_scene"] = "plan_node"
    
    # Step B1: LLM任务拆解
    messages = build_planning_messages(state)
    res = await plan_agent.ainvoke({"messages": messages})

    raw_content = res["messages"][-1].content
    json_content = extract_json(raw_content)
    task_plan = json.loads(json_content)

    # Step B2: 计划合理性校验
    # 由用户在确认环节人工检查任务计划的合理性

    state["task_plan"] = task_plan
    state["current_scene_before_confirm"] = "plan_node"  # 记录来源，用于ConfirmNode路由
    state["need_confirm"] = True
    
    # 清理反馈信息（避免影响下次规划）
    # 使用 pop 方法避免 TypedDict 删除警告
    state.pop("plan_feedback", None)
    state.pop("previous_plan", None)
    
    state["messages"].append("[plan_node] 任务规划完成，等待用户确认")
    return state


if __name__ == "__main__":
    state = IMState(
        workflow_id="wf_001",
        user_id="123",
        user_input="@Agent-Pilot根据今天的群消息,帮我生成一个总结文档",
        source="feishu_im",
        chat_id="oc_81881e331cd9d7f921771aa884b96742",
        messages=["[router_node] 开始意图识别","[router_node] 识别到意图：doc_creation"],
        intent={
                "intent_type": "doc_creation",
                "topic": "新功能开发计划总结文档",
                "key_points": ["核心功能规划（用户画像、推荐系统、可视化）","数据源说明与开发周期评估",
                               "计划调整说明（推荐系统延期至 4 周）","当前进度状态与后续待办事项"],
                "confidence": 0.95,
                "additional_info": {
                    "doc_type": "report"
                }
        },
        chat_context="【任务 / 主题】：新功能开发计划讨论（用户画像、推荐系统、可视化）\n\n【关键信息】：\n- 核心功能：用户画像分析、"
                     "智能推荐系统、数据可视化面板。\n- 数据源：用户注册信息、行为日志数据、第三方数据接口。\n- 开发周期：用户画像 2 周，"
                     "数据可视化 1 周。\n- 计划调整：智能推荐系统因算法调优耗时，由 3 周调整为 4 周。\n- 总工期：共计 7 周。\n\n"
                     "【当前状态】：需求文档已整理，开发周期评估完成，计划已更新确认。\n\n【待办事项】：\n- [ ] 李四更新推荐系统开发时间"
                     "为 4 周 \n- [ ] 按更新后计划执行开发 \n\n【用户偏好 / 约束】：\n- 推荐系统需预留充足时间进行算法调优。"
    )

    res = asyncio.run(plan_node(state))
    print(res)
