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
    """处理用户确认结果

    根据确认前的场景决定路由:
    - plan_node来的 → modify返回plan_node
    - text_generate_node来的 → modify返回text_generate_node重新生成大纲
    - ppt_generate_node来的 → 可能是风格选择确认、大纲确认或满意度确认
    """
    if state.get("cancelled", False):
        return "end"
    elif state.get("confirmed", True):
        # 用户已确认，根据场景决定执行什么
        prev_scene = state.get("current_scene_before_confirm", "")
        confirm_type = state.get("confirm_type", "")
        
        if prev_scene == "ppt_generate_node":
            if confirm_type == "style_selection":
                # 风格选择确认后，继续执行PPT生成（会进入大纲生成）
                return "continue_ppt_generate"
            elif confirm_type == "ppt_satisfaction":
                # 满意度确认后，用户满意，任务完成
                return "ppt_satisfied"
            else:
                # 大纲确认后，继续执行PPT内容生成
                return "execute_ppt_content"
        return "execute"
    else:
        # 用户要求修改，根据来源决定返回哪个节点
        prev_scene = state.get("current_scene_before_confirm", "")
        confirm_type = state.get("confirm_type", "")
        
        if prev_scene == "text_generate_node":
            return "modify_doc_outline"  # 返回text_generate_node重新生成文档大纲
        elif prev_scene == "ppt_generate_node":
            if confirm_type == "ppt_satisfaction":
                # 满意度确认时用户不满意，需要修改PPT
                revision_type = state.get("ppt_revision_type", "")
                if revision_type == "revise":
                    return "revise_ppt"  # 在原有基础上修改
                else:
                    return "regenerate_ppt"  # 重新生成内容
            return "modify_ppt_outline"  # 返回ppt_generate_node重新生成PPT大纲
        return "modify_plan"  # 默认返回plan_node重新规划


def route_after_plan(state: IMState) -> str:
    """任务规划后路由 - 根据任务计划决定执行路径

    支持三种场景:
    1. 只生成文档: 直接到 text_generate_node
    2. 只生成PPT: 直接到 ppt_generate_node
    3. 两者都生成: 先到 text_generate_node，再到 ppt_generate_node
    """
    plan = state.get("task_plan", {})
    branches = plan.get("branches", [])

    need_doc = any(b["scene"] == "C" and b["trigger"] for b in branches)
    need_ppt = any(b["scene"] == "D" and b["trigger"] for b in branches)

    if need_doc:
        # 需要生成文档，先执行文档生成
        return "text_generate"
    elif need_ppt:
        # 不需要文档但需要PPT，直接执行PPT生成
        return "ppt_generate"
    else:
        # 两者都不需要，直接到多端同步
        return "multi_terminal"


def route_after_text_generate(state: IMState) -> str:
    """文档生成节点后路由

    1. 如果需要确认(need_confirm=True) → 进入确认节点
    2. 如果已确认且需要PPT → 进入PPT生成
    3. 否则 → 进入多端同步
    """
    # 优先检查是否需要确认（大纲确认）
    if state.get("need_confirm", False):
        return "confirm"

    # 检查是否需要执行PPT生成
    plan = state.get("task_plan", {})
    branches = plan.get("branches", [])
    need_ppt = any(b["scene"] == "D" and b["trigger"] for b in branches)

    if need_ppt and not state.get("ppt_url"):
        return "ppt_generate"
    return "multi_terminal"


def route_after_ppt_generate(state: IMState) -> str:
    """PPT生成节点后路由

    1. 如果需要确认(need_confirm=True) → 进入确认节点
    2. 如果已确认 → 进入多端同步
    """
    # 优先检查是否需要确认（PPT大纲确认）
    if state.get("need_confirm", False):
        return "confirm"
    return "multi_terminal"


def build_workflow() -> StateGraph:
    """构建完整的LangGraph工作流

    支持三种执行模式:
    1. 只生成文档: router_node → plan_node → text_generate_node → multi_terminal_node → delivery_node
    2. 只生成PPT: router_node → plan_node → ppt_generate_node → multi_terminal_node → delivery_node
    3. 两者都生成: router_node → plan_node → text_generate_node → ppt_generate_node → multi_terminal_node → delivery_node

    确认节点可插入在 plan_node 后或 text_generate_node 后
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

    # plan_node → 根据任务计划路由到不同节点
    graph.add_conditional_edges("plan_node", route_after_plan, {
        "text_generate": "text_generate_node",  # 执行文档生成
        "ppt_generate": "ppt_generate_node",    # 直接执行PPT生成（不需要文档）
        "multi_terminal": "multi_terminal_node" # 两者都不需要
    })

    # 文档生成节点后：可能需要确认大纲，或继续执行
    graph.add_conditional_edges("text_generate_node", route_after_text_generate, {
        "confirm": "confirm_node",  # 需要确认大纲
        "ppt_generate": "ppt_generate_node",
        "multi_terminal": "multi_terminal_node"
    })

    # 确认节点 → 重新规划或执行
    graph.add_conditional_edges("confirm_node", handle_confirm, {
        "end": END,
        "execute": "text_generate_node",  # 执行文档生成
        "execute_ppt_content": "ppt_generate_node",  # 执行PPT内容生成（大纲已确认）
        "continue_ppt_generate": "ppt_generate_node",  # 继续PPT生成（风格已选择，进入大纲生成）
        "ppt_satisfied": "multi_terminal_node",  # PPT满意，进入多端同步
        "revise_ppt": "ppt_generate_node",  # 修改PPT（在原有基础上调整）
        "regenerate_ppt": "ppt_generate_node",  # 重新生成PPT（保留大纲）
        "modify_plan": "plan_node",  # 修改任务计划
        "modify_doc_outline": "text_generate_node",  # 修改文档大纲
        "modify_ppt_outline": "ppt_generate_node"  # 修改PPT大纲
    })

    # PPT生成节点后：可能需要确认大纲，或继续执行
    graph.add_conditional_edges("ppt_generate_node", route_after_ppt_generate, {
        "confirm": "confirm_node",  # 需要确认PPT大纲
        "multi_terminal": "multi_terminal_node"
    })

    # 多端同步 → 总结交付 → END
    graph.add_edge("multi_terminal_node", "delivery_node")
    graph.add_edge("delivery_node", END)

    return graph.compile()
