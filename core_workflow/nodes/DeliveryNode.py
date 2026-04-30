from state.state import IMState
from utils.feishuUtils import feishu_api
from utils.logger_handler import logger


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

    # Step F2: 推送飞书消息通知
    await _send_delivery_notification(state, artifacts, topic)
    
    # Step F3: 归档记录
    # TODO: 持久化到数据库

    state["messages"].append("[delivery_node] 工作流完成，所有产出物已交付")
    return state


async def _send_delivery_notification(state: IMState, artifacts: list, topic: str):
    """发送交付通知到飞书"""
    chat_id = state.get("chat_id")
    if not chat_id:
        logger.warning("[DeliveryNode] 缺少 chat_id，无法发送飞书通知")
        return
    
    try:
        # 构建通知消息
        message_lines = [f"✅ **{topic}** 任务已完成！\n"]
        
        for artifact in artifacts:
            artifact_type = "📄 文档" if artifact["type"] == "doc" else "📊 PPT"
            message_lines.append(f"{artifact_type}: [{artifact['title']}]({artifact['url']})")
        
        message_text = "\n".join(message_lines)
        
        # 发送文本消息
        await feishu_api.send_text_message(
            receive_id=chat_id,
            text=message_text,
            receive_id_type="chat_id"
        )
        logger.info(f"[DeliveryNode] 交付通知已发送到飞书群 {chat_id}")
        
    except Exception as e:
        logger.error(f"[DeliveryNode] 发送飞书通知失败: {e}")
