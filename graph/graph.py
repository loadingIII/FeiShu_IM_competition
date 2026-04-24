from langgraph.graph import StateGraph, END
from state.state import IMState
from nodes.RouterNode import router_node
from nodes.PlanNode import plan_node
from nodes.TextGenerateNode import text_generate_node
from nodes.PPTGenerateNode import ppt_generate_node
from nodes.MultiTerminalNode import multi_terminal_node
from nodes.DeliveryNode import delivery_node
from nodes.ConfirmNode import confirm_node


def should_confirm(state: IMState) -> str:
    """判断是否需要人工确认"""
    if state.get("need_confirm", False):
        return "confirm"
    return "execute"


def handle_confirm(state: IMState) -> str:
    """处理用户确认结果"""
    if state.get("cancelled", False):
        return "end"
    elif state.get("confirmed", False):
        return "execute"
    else:
        return "modify"


def route_after_text_generate(state: IMState) -> str:
    """文档生成完成后，检查是否需要执行PPT生成"""
    plan = state.get("task_plan", {})
    branches = plan.get("branches", [])
    need_ppt = any(b["scene"] == "D" and b["trigger"] for b in branches)
    
    # 如果任务计划包含PPT生成且还没有执行过
    if need_ppt and not state.get("ppt_url"):
        return "ppt_generate"
    return "multi_terminal"


def route_after_ppt_generate(state: IMState) -> str:
    """PPT生成完成后，到多端同步节点"""
    return "multi_terminal"


def build_workflow() -> StateGraph:
    """构建完整的LangGraph工作流
    
    流程: router_node → plan_node → [confirm] → text_generate_node → ppt_generate_node → multi_terminal_node → delivery_node
                                 ↘____________________↗
    
    注意：由于LangGraph的限制，文档生成和PPT生成采用串行执行但逻辑上独立的模式
    真正的并行需要在节点内部使用asyncio.gather或其他并发机制
    """
    graph = StateGraph(IMState)

    # 添加节点
    graph.add_node("router_node", router_node)
    graph.add_node("plan_node", plan_node)
    graph.add_node("text_generate_node", text_generate_node)
    graph.add_node("ppt_generate_node", ppt_generate_node)
    graph.add_node("multi_terminal_node", multi_terminal_node)
    graph.add_node("delivery_node", delivery_node)
    graph.add_node("confirm_node", confirm_node)

    # 定义入口
    graph.set_entry_point("router_node")
    graph.add_edge("router_node", "plan_node")

    # plan_node → 确认(可选) → 执行
    graph.add_conditional_edges("plan_node", should_confirm, {
        "confirm": "confirm_node",
        "execute": "text_generate_node"  # 直接执行文档生成
    })

    # 确认节点 → 重新规划或执行
    graph.add_conditional_edges("confirm_node", handle_confirm, {
        "end": END,
        "execute": "text_generate_node",  # 执行文档生成
        "modify": "plan_node"
    })

    # 文档生成完成后，根据条件决定是否执行PPT生成
    graph.add_conditional_edges("text_generate_node", route_after_text_generate, {
        "ppt_generate": "ppt_generate_node",
        "multi_terminal": "multi_terminal_node"
    })

    # PPT生成完成后到多端同步节点
    graph.add_conditional_edges("ppt_generate_node", route_after_ppt_generate, {
        "multi_terminal": "multi_terminal_node"
    })

    # 多端同步 → 总结交付 → END
    graph.add_edge("multi_terminal_node", "delivery_node")
    graph.add_edge("delivery_node", END)

    return graph.compile()
