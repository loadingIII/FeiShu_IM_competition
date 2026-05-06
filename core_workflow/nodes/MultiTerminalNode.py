from state.state import IMState
from utils.logger_handler import logger

try:
    from app.service.websocket import ws_manager
except ImportError:
    ws_manager = None


async def multi_terminal_node(state: IMState) -> IMState:
    """场景E：多端同步（汇合点）"""
    state["current_scene"] = "multi_terminal_node"
    state["messages"].append("[multi_terminal_node] 开始多端同步")

    workflow_id = state.get("workflow_id", "")

    # 广播最终状态到前端
    if ws_manager:
        try:
            await ws_manager.broadcast_to_workflow(workflow_id, {
                "type": "scene_progress",
                "scene": "E",
                "status": "completed",
                "data": {
                    "doc_url": state.get("doc_url"),
                    "ppt_url": state.get("ppt_url"),
                    "ppt_generation_completed": state.get("ppt_generation_completed"),
                    "delivery": state.get("delivery"),
                }
            })
            logger.info(f"[multi_terminal_node] 已广播最终状态: {workflow_id}")
        except Exception as e:
            logger.warning(f"[multi_terminal_node] 广播失败: {e}")

    state["messages"].append("[multi_terminal_node] 多端同步完成")
    return state
