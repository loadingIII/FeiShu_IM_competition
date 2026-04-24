from state.state import IMState


async def confirm_node(state: IMState) -> IMState:
    """通用确认等待节点"""
    state["messages"].append("[confirm_node] 等待用户确认")
    # 实际场景中工作流会在此暂停，等待用户操作后继续
    return state
