from state.state import IMState


async def delivery_node(state: IMState) -> IMState:
    """场景F：总结交付"""
    state["current_scene"] = "delivery_node"
    state["messages"].append("[delivery_node] 开始总结交付")

    # Step F1: 汇总产出物
    artifacts = []
    if state.get("doc_url"):
        artifacts.append({
            "type": "doc",
            "title": state["doc_content"]["title"] if state.get("doc_content") else "文档",
            "url": state["doc_url"]
        })
    if state.get("ppt_url"):
        artifacts.append({
            "type": "ppt",
            "title": state["ppt_content"]["title"] if state.get("ppt_content") else "PPT",
            "url": state["ppt_url"]
        })

    # 安全获取主题
    intent = state.get("intent", {})
    topic = intent.get("topic", "任务") if intent else "任务"
    
    # 安全获取任务计划
    task_plan = state.get("task_plan", {})
    branches = task_plan.get("branches", []) if task_plan else []
    
    delivery = {
        "summary": f"已完成{topic}相关任务",
        "artifacts": artifacts,
        "workflow_id": state.get("workflow_id", ""),
        "completed_branches": len(artifacts),
        "total_branches": len(branches)
    }
    state["delivery"] = delivery

    # Step F2: 推送通知
    # TODO: 推送飞书消息
    # Step F3: 归档记录
    # TODO: 持久化到数据库

    state["messages"].append("[delivery_node] 工作流完成，所有产出物已交付")
    return state
