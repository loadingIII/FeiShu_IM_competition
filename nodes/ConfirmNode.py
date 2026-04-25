import json
from state.state import IMState
from utils.logger_handler import logger


def format_task_plan(task_plan: dict) -> str:
    """格式化任务计划为易读的文本"""
    lines = []
    lines.append("=" * 50)
    lines.append(f"[任务目标] {task_plan.get('goal', 'N/A')}")
    lines.append("=" * 50)
    
    lines.append("\n[执行分支]")
    branches = task_plan.get('branches', [])
    for i, branch in enumerate(branches, 1):
        lines.append(f"  {i}. 场景 {branch.get('scene', '?')} - {branch.get('action', 'N/A')}")
        lines.append(f"     描述: {branch.get('description', 'N/A')}")
        lines.append(f"     触发: {'是' if branch.get('trigger') else '否'}")
        lines.append(f"     需大纲确认: {'是' if branch.get('need_outline_confirm') else '否'}")
        lines.append("")
    
    lines.append("[后续动作]")
    post_actions = task_plan.get('post_actions', [])
    for action in post_actions:
        lines.append(f"  - 场景 {action.get('scene', '?')} - {action.get('action', 'N/A')}")
    
    lines.append("=" * 50)
    return "\n".join(lines)


async def confirm_node(state: IMState) -> IMState:
    """通用确认等待节点 - 命令行交互版本"""
    logger.info("[confirm_node] 进入确认节点")
    state["current_scene"] = "confirm_node"
    state["messages"].append("[confirm_node] 等待用户确认")
    
    task_plan = state.get("task_plan", {})
    
    # 打印任务计划供用户审核
    print("\n" + format_task_plan(task_plan))
    
    # 命令行交互
    while True:
        print("\n请选择操作:")
        print("  [1] 确认执行 - 按照当前计划继续")
        print("  [2] 修改计划 - 重新生成任务规划")
        print("  [3] 取消任务 - 结束当前工作流")
        
        try:
            choice = input("\n请输入选项 (1/2/3): ").strip()
            
            if choice == "1":
                state["confirmed"] = True
                state["cancelled"] = False
                state["messages"].append("[confirm_node] 用户确认执行")
                print("[已确认] 继续执行任务...")
                break
                
            elif choice == "2":
                state["confirmed"] = False
                state["cancelled"] = False
                state["need_confirm"] = False  # 重置确认标志，让 plan_node 重新生成
                
                # 收集用户修改意见
                print("\n[修改意见] 请描述您希望如何调整任务计划:")
                print("  例如：不需要生成PPT、文档要更详细、先确认大纲再生成 等")
                try:
                    feedback = input("\n您的意见: ").strip()
                    if feedback:
                        state["plan_feedback"] = feedback
                        state["messages"].append(f"[confirm_node] 用户要求修改计划: {feedback}")
                    else:
                        state["plan_feedback"] = "用户未提供具体意见，请尝试生成不同的计划"
                        state["messages"].append("[confirm_node] 用户要求修改计划，但未提供具体意见")
                except (EOFError, KeyboardInterrupt):
                    state["plan_feedback"] = "用户未提供具体意见，请尝试生成不同的计划"
                    state["messages"].append("[confirm_node] 用户要求修改计划(非交互环境)")
                
                # 保存之前的计划供参考
                state["previous_plan"] = task_plan
                
                print("[重新规划] 正在根据您的意见重新生成任务计划...")
                break
                
            elif choice == "3":
                state["confirmed"] = False
                state["cancelled"] = True
                state["messages"].append("[confirm_node] 用户取消任务")
                print("[已取消] 任务结束")
                break
                
            else:
                print("[警告] 无效输入，请输入 1、2 或 3")
                
        except (EOFError, KeyboardInterrupt):
            # 处理非交互环境或用户中断
            print("\n[警告] 检测到非交互环境，自动确认执行")
            state["confirmed"] = True
            state["cancelled"] = False
            state["messages"].append("[confirm_node] 非交互环境，自动确认")
            break
    
    return state


if __name__ == "__main__":
    import asyncio
    
    # 测试用例
    test_state = IMState(
        workflow_id="test_001",
        user_id="user_123",
        user_input="测试输入",
        source="test",
        chat_id="test_chat",
        messages=[],
        intent={"intent_type": "doc_generation", "topic": "测试文档"},
        task_plan={
            "goal": "完成测试文档生成",
            "branches": [
                {
                    "scene": "C",
                    "action": "生成测试文档",
                    "description": "根据需求生成测试文档内容",
                    "trigger": True,
                    "need_outline_confirm": True
                }
            ],
            "post_actions": [
                {"scene": "E", "action": "多端同步"},
                {"scene": "F", "action": "总结交付"}
            ]
        },
        need_confirm=True
    )
    
    result = asyncio.run(confirm_node(test_state))
    print("\n最终状态:")
    print(f"  confirmed: {result.get('confirmed')}")
    print(f"  cancelled: {result.get('cancelled')}")
