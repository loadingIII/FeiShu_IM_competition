from state.state import IMState


async def plan_node(state: IMState) -> IMState:
    """场景B：任务规划"""
    state["current_scene"] = "plan_node"
    state["messages"].append("[plan_node] 开始任务规划")

    # Step B1: LLM任务拆解
    # TODO: 调用豆包LLM生成任务计划
    intent = state["intent"]
    branches = []

    if intent["intent_type"] in ["meeting_summary", "weekly_report"]:
        branches = [
            {
                "scene": "C",
                "action": "生成会议纪要文档",
                "description": "从群聊记录中提取要点，生成结构化文档",
                "trigger": True,
                "need_outline_confirm": True
            },
            {
                "scene": "D",
                "action": "生成汇报PPT",
                "description": "基于会议内容生成精炼的演示文稿",
                "trigger": True,
                "need_outline_confirm": False
            }
        ]
    elif intent["intent_type"] == "doc_generation":
        branches = [
            {
                "scene": "C",
                "action": "生成文档",
                "description": "根据需求生成结构化文档",
                "trigger": True,
                "need_outline_confirm": True
            }
        ]
    elif intent["intent_type"] == "ppt_generation":
        branches = [
            {
                "scene": "D",
                "action": "生成PPT",
                "description": "根据需求生成演示文稿",
                "trigger": True,
                "need_outline_confirm": False
            }
        ]

    task_plan = {
        "goal": f"完成{intent['topic']}相关任务",
        "branches": branches,
        "post_actions": [
            {"scene": "E", "action": "多端同步"},
            {"scene": "F", "action": "总结交付"}
        ]
    }

    # Step B2: 计划合理性校验
    # TODO: 校验计划结构完整性

    state["task_plan"] = task_plan
    state["need_confirm"] = True
    state["messages"].append("[plan_node] 任务规划完成，等待用户确认")
    return state
