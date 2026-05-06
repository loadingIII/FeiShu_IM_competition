from langgraph.graph import StateGraph, END
from state.state import IMState
from nodes.RouterNode import router_node
from nodes.PlanNode import plan_node
from nodes.TextGenerateNode import (
    text_generate_node,
    generate_doc_content
)
from nodes.PPTGenerateNode import ppt_generate_node
from nodes.MultiTerminalNode import multi_terminal_node
from nodes.DeliveryNode import delivery_node
from nodes.ConfirmNode import confirm_node


def get_task_plan_branch(state: IMState) -> str:
    """根据任务计划确定执行分支

    检查任务计划中的branches，确定需要执行的场景:
    - C: 文档生成
    - D: PPT生成

    当同时需要文档和PPT时，优先执行文档生成，
    文档完成后会自动继续PPT生成。
    """
    task_plan = state.get("task_plan", {})
    branches = task_plan.get("branches", [])

    has_doc = False
    has_ppt = False

    for branch in branches:
        if branch.get("trigger"):
            scene = branch.get("scene", "")
            if scene == "C":
                has_doc = True
            elif scene == "D":
                has_ppt = True

    # 同时需要文档和PPT，先做文档
    if has_doc and has_ppt:
        return "doc"

    # 单一分支
    for branch in branches:
        if branch.get("trigger"):
            scene = branch.get("scene", "")
            if scene == "C":
                return "doc"
            elif scene == "D":
                return "ppt"

    # 默认执行文档生成
    return "doc"


def is_ppt_needed(state: IMState) -> bool:
    """检查任务计划中是否包含PPT生成"""
    task_plan = state.get("task_plan", {})
    branches = task_plan.get("branches", [])
    for branch in branches:
        if branch.get("trigger") and branch.get("scene") == "D":
            return True
    return False


def handle_confirm(state: IMState) -> str:
    """处理用户确认结果

    根据确认类型和来源场景决定路由:
    - doc_outline确认: 确认后生成内容
    - ppt_outline确认: 确认后生成PPT内容
    - ppt_content确认: 确认后制作PPT文件
    """
    if state.get("cancelled", False):
        return "end"

    confirm_type = state.get("confirm_type", "")

    if state.get("confirmed", True):
        # 用户已确认，根据确认类型执行下一步
        if confirm_type == "doc_outline":
            return "generate_doc_content"
        elif confirm_type == "ppt_outline":
            return "generate_ppt_content"
        elif confirm_type == "ppt_content":
            return "generate_ppt_file"
        return "execute"
    else:
        # 用户要求修改
        if confirm_type == "doc_outline":
            return "modify_doc_outline"
        elif confirm_type == "ppt_outline":
            return "modify_ppt_outline"
        elif confirm_type == "ppt_content":
            return "modify_ppt_content"
        return "modify_doc_outline"


def route_after_plan(state: IMState) -> str:
    """任务规划后路由

    生成任务计划后直接进入执行流程，无需用户确认
    """
    if state.get("need_confirm", False):
        return "confirm"
    # 不需要确认时，根据任务计划决定执行路径
    branch = get_task_plan_branch(state)
    if branch == "ppt":
        return "execute_ppt"
    return "execute_doc"


def route_after_router(state: IMState) -> str:
    """意图识别后路由

    根据意图识别结果决定下一步：
    - 闲聊类意图已在入口处处理，不会进入工作流
    - 此处只处理明确的任务意图 → plan_node
    """
    return "plan"


def route_after_doc_outline(state: IMState) -> str:
    """文档大纲生成后路由"""
    if state.get("need_confirm", False):
        return "confirm"
    return "generate_content"


def route_after_doc_generation(state: IMState) -> str:
    """文档生成完成后路由

    文档生成完成后，检查是否还需要生成PPT：
    - 需要PPT → 继续PPT生成
    - 不需要 → 路由到多端同步
    """
    if is_ppt_needed(state):
        return "ppt_generate"
    return "multi_terminal"


def route_after_ppt_node(state: IMState) -> str:
    """PPT生成节点后路由
    
    根据PPT生成状态决定下一步：
    - 需要确认 -> 确认节点
    - PPT已生成完成 -> 多端同步
    - 继续生成 -> 保持在PPT生成节点
    """
    # 如果出错，直接进入交付节点结束流程
    if state.get("error"):
        return "delivery"
    
    # 如果PPT已生成完成（有ppt_url），路由到多端同步
    if state.get("ppt_url") or state.get("ppt_generation_completed"):
        return "multi_terminal"
    
    # 如果需要确认，进入确认节点
    if state.get("need_confirm", False):
        return "confirm"
    
    # 继续生成流程
    return "continue"


def route_after_ppt_content(state: IMState) -> str:
    """PPT内容生成后路由"""
    if state.get("need_confirm", False):
        return "confirm"
    return "generate_ppt_file"


def build_workflow() -> StateGraph:
    """构建LangGraph工作流

    流程设计:
    1. 意图识别 → 任务规划（自动执行，无需确认）
    2. 根据计划执行:
       - 仅文档生成(C): 大纲生成 → 大纲确认 → 内容生成 → 生成文档
       - 仅PPT生成(D): 大纲生成 → 大纲确认 → 内容生成 → 内容确认 → 制作文件
       - 文档+PPT(C+D): 先生成文档，完成后继续PPT生成流程
    3. 完成后 → 多端同步 → 总结交付
    """
    graph = StateGraph(IMState)

    # 添加节点
    graph.add_node("router_node", router_node)
    graph.add_node("plan_node", plan_node)
    graph.add_node("confirm_node", confirm_node)
    graph.add_node("multi_terminal_node", multi_terminal_node)
    graph.add_node("delivery_node", delivery_node)

    # 文档生成节点
    graph.add_node("text_generate_node", text_generate_node)
    graph.add_node("generate_doc_content", generate_doc_content)

    # PPT生成节点
    graph.add_node("ppt_generate_node", ppt_generate_node)

    # 定义入口
    graph.set_entry_point("router_node")

    # router_node → 任务规划（闲聊已在入口处理）
    graph.add_edge("router_node", "plan_node")

    # plan_node → 任务计划确认或直接执行
    graph.add_conditional_edges("plan_node", route_after_plan, {
        "confirm": "confirm_node",
        "execute_doc": "text_generate_node",
        "execute_ppt": "ppt_generate_node"
    })

    # 确认节点 → 根据确认类型路由
    graph.add_conditional_edges("confirm_node", handle_confirm, {
        "end": END,
        "execute": "text_generate_node",
        "generate_doc_content": "generate_doc_content",
        "generate_ppt_content": "ppt_generate_node",  # PPT大纲确认后，继续生成内容
        "generate_ppt_file": "ppt_generate_node",     # PPT内容确认后，制作文件
        "modify_doc_outline": "text_generate_node",
        "modify_ppt_outline": "ppt_generate_node",    # 修改PPT大纲
        "modify_ppt_content": "ppt_generate_node",    # 修改PPT内容
    })

    # 文档生成流程
    graph.add_conditional_edges("text_generate_node", route_after_doc_outline, {
        "confirm": "confirm_node",
        "generate_content": "generate_doc_content"
    })
    
    # 生成文档内容后，根据是否需要PPT决定下一步
    graph.add_conditional_edges("generate_doc_content", route_after_doc_generation, {
        "ppt_generate": "ppt_generate_node",
        "multi_terminal": "multi_terminal_node"
    })
    
    # PPT生成流程：大纲生成 → 大纲确认 → 内容生成 → 内容确认 → 制作文件 → 多端同步
    graph.add_conditional_edges("ppt_generate_node", route_after_ppt_node, {
        "confirm": "confirm_node",           # 需要用户确认
        "continue": "ppt_generate_node",     # 继续生成（大纲→内容→文件）
        "multi_terminal": "multi_terminal_node",  # PPT生成完成，进入多端同步
        "delivery": "delivery_node"           # 出错，结束流程
    })
    
    # 多端同步 → 总结交付 → END
    graph.add_edge("multi_terminal_node", "delivery_node")
    graph.add_edge("delivery_node", END)

    return graph.compile()
