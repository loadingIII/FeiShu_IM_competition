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


def format_doc_outline(doc_outline: dict) -> str:
    """格式化文档大纲为易读的文本"""
    lines = []
    lines.append("=" * 50)
    lines.append(f"[文档标题] {doc_outline.get('title', 'N/A')}")
    lines.append(f"[文档类型] {doc_outline.get('doc_type', 'N/A')}")
    lines.append("=" * 50)
    
    lines.append("\n[文档结构]")
    sections = doc_outline.get('sections', [])
    for i, section in enumerate(sections, 1):
        lines.append(f"  {i}. {section.get('heading', '未命名章节')}")
        points = section.get('points', [])
        for point in points:
            lines.append(f"     - {point}")
        lines.append("")
    
    lines.append("=" * 50)
    return "\n".join(lines)


def format_ppt_outline(ppt_structure: dict) -> str:
    """格式化PPT大纲为易读的文本"""
    lines = []
    lines.append("=" * 50)
    lines.append(f"[PPT标题] {ppt_structure.get('title', 'N/A')}")
    lines.append(f"[PPT类型] {ppt_structure.get('ppt_type', 'N/A')}")
    lines.append(f"[PPT风格] {ppt_structure.get('ppt_style', 'business_blue')}")
    lines.append("=" * 50)
    
    lines.append("\n[PPT结构]")
    slides = ppt_structure.get('slides', [])
    for slide in slides:
        page = slide.get('page', 0)
        slide_type = slide.get('type', 'content')
        title = slide.get('title', '未命名页面')
        
        type_emoji = {
            'cover': '📘',
            'agenda': '📋',
            'content': '📝',
            'summary': '✅',
            'ending': '🎉'
        }.get(slide_type, '📄')
        
        lines.append(f"  {type_emoji} 第{page}页 [{slide_type}] {title}")
        
        if slide_type in ['agenda', 'content', 'summary']:
            points = slide.get('points', [])
            for point in points:
                lines.append(f"     • {point}")
        
        if slide.get('subtitle'):
            lines.append(f"     副标题: {slide['subtitle']}")
    
    lines.append("=" * 50)
    return "\n".join(lines)


async def confirm_node(state: IMState) -> IMState:
    """通用确认等待节点 - 命令行交互版本
    
    支持四种确认场景:
    1. 任务计划确认 (task_plan)
    2. 文档大纲确认 (doc_outline)
    3. PPT风格选择 (style_selection)
    4. PPT大纲确认 (ppt_structure)
    """
    logger.info("[confirm_node] 进入确认节点")
    state["current_scene"] = "confirm_node"
    state["messages"].append("[confirm_node] 等待用户确认")
    
    # 判断当前需要确认的内容
    task_plan = state.get("task_plan")
    doc_outline = state.get("doc_outline")
    ppt_structure = state.get("ppt_structure")
    current_scene = state.get("current_scene_before_confirm", "")
    confirm_type = state.get("confirm_type", "")
    
    # Step 1: 处理PPT风格选择
    # 注意：当从plan_node进入且需要生成PPT时，也应该显示风格选择
    if (confirm_type == "style_selection" and current_scene == "ppt_generate_node") or \
       (current_scene == "ppt_generate_node" and not state.get("ppt_style_confirmed")):
        # PPT风格选择模式
        from nodes.PPTGenerateNode import format_style_selection, parse_style_selection, PPT_STYLE_OPTIONS
        
        print("\n" + format_style_selection())
        
        while True:
            try:
                user_input = input("\n请输入您的选择: ").strip()
                
                style_key, is_valid, message = parse_style_selection(user_input)
                
                if message == "cancelled":
                    state["cancelled"] = True
                    state["need_confirm"] = False
                    state["messages"].append("[confirm_node] 用户取消PPT生成")
                    print("[已取消] 任务结束")
                    return state
                
                if is_valid:
                    if style_key == "auto":
                        # 自动推荐，让PPTGenerateNode自己决定
                        state["ppt_style_selected"] = None
                        state["ppt_style_confirmed"] = True
                    else:
                        state["ppt_style_selected"] = style_key
                        state["ppt_style_confirmed"] = True
                    
                    state["confirmed"] = True
                    state["need_confirm"] = False
                    state["messages"].append(f"[confirm_node] 用户选择PPT风格: {message}")
                    print(f"[已选择] {message}")
                    return state
                else:
                    print(f"[错误] {message}")
                    print("请重新输入，或输入 'cancel' 取消")
                    
            except (EOFError, KeyboardInterrupt):
                # 非交互环境，自动选择
                print("\n[警告] 检测到非交互环境，自动选择商务蓝风格")
                state["ppt_style_selected"] = "business_blue"
                state["ppt_style_confirmed"] = True
                state["confirmed"] = True
                state["need_confirm"] = False
                state["messages"].append("[confirm_node] 非交互环境，自动选择business_blue风格")
                return state
    
    # Step 2: 处理PPT满意度确认
    # 检查是否已生成PPT且需要满意度确认
    if (confirm_type == "ppt_satisfaction" and current_scene == "ppt_generate_node") or \
       (current_scene == "ppt_generate_node" and state.get("ppt_url") and not state.get("ppt_satisfaction_confirmed")):
        # PPT满意度确认模式
        ppt_url = state.get("ppt_url", "")
        ppt_title = state.get("ppt_structure", {}).get("title", "未命名PPT")
        revision_count = state.get("ppt_revision_count", 0)
        
        from nodes.PPTGenerateNode import format_ppt_satisfaction_check
        print("\n" + format_ppt_satisfaction_check(ppt_url, ppt_title, revision_count))
        
        while True:
            try:
                choice = input("\n请输入选项 (1/2/3): ").strip()
                
                if choice == "1":
                    # 满意，完成任务
                    state["ppt_satisfaction_confirmed"] = True
                    state["confirmed"] = True
                    state["cancelled"] = False
                    state["need_confirm"] = False
                    state["messages"].append("[confirm_node] 用户确认PPT满意，任务完成")
                    print("[已确认] 任务完成！")
                    return state
                    
                elif choice == "2":
                    # 需要修改，在原有基础上调整
                    state["ppt_satisfaction_confirmed"] = False
                    state["confirmed"] = False
                    state["cancelled"] = False
                    state["need_confirm"] = False
                    
                    print("\n[修改意见] 请描述您希望如何修改PPT：")
                    print("  例如：增加数据图表、调整某页内容、修改配色等")
                    
                    try:
                        feedback = input("\n您的修改意见: ").strip()
                        if feedback:
                            state["ppt_satisfaction_feedback"] = feedback
                            state["messages"].append(f"[confirm_node] 用户要求修改PPT: {feedback}")
                        else:
                            state["ppt_satisfaction_feedback"] = "用户未提供具体修改意见，请尝试优化内容"
                            state["messages"].append("[confirm_node] 用户要求修改PPT，但未提供具体意见")
                    except (EOFError, KeyboardInterrupt):
                        state["ppt_satisfaction_feedback"] = "用户未提供具体修改意见，请尝试优化内容"
                        state["messages"].append("[confirm_node] 用户要求修改PPT(非交互环境)")
                    
                    # 设置修改类型为"revise"（在原有基础上修改）
                    state["ppt_revision_type"] = "revise"
                    print("[修改中] 正在根据您的意见修改PPT...")
                    return state
                    
                elif choice == "3":
                    # 重新生成，保留大纲
                    state["ppt_satisfaction_confirmed"] = False
                    state["confirmed"] = False
                    state["cancelled"] = False
                    state["need_confirm"] = False
                    
                    print("\n[重新生成] 请描述您希望如何重新生成：")
                    print("  例如：内容要更详细、风格要更活泼、增加案例分析等")
                    
                    try:
                        feedback = input("\n您的意见: ").strip()
                        if feedback:
                            state["ppt_satisfaction_feedback"] = feedback
                            state["messages"].append(f"[confirm_node] 用户要求重新生成PPT: {feedback}")
                        else:
                            state["ppt_satisfaction_feedback"] = "用户要求重新生成PPT，请尝试不同的内容"
                            state["messages"].append("[confirm_node] 用户要求重新生成PPT")
                    except (EOFError, KeyboardInterrupt):
                        state["ppt_satisfaction_feedback"] = "用户要求重新生成PPT"
                        state["messages"].append("[confirm_node] 用户要求重新生成PPT(非交互环境)")
                    
                    # 设置修改类型为"regenerate"（重新生成内容）
                    state["ppt_revision_type"] = "regenerate"
                    # 清除内容但保留大纲
                    state["ppt_content"] = None
                    print("[重新生成] 正在重新生成PPT内容...")
                    return state
                    
                else:
                    print("[警告] 无效输入，请输入 1、2 或 3")
                    
            except (EOFError, KeyboardInterrupt):
                # 非交互环境，自动确认满意
                print("\n[警告] 检测到非交互环境，自动确认满意")
                state["ppt_satisfaction_confirmed"] = True
                state["confirmed"] = True
                state["need_confirm"] = False
                state["messages"].append("[confirm_node] 非交互环境，自动确认PPT满意")
                return state
    
    # Step 3: 处理大纲/计划确认
    # 根据当前场景决定确认什么内容
    # PPT大纲确认：有ppt_structure且风格已确认但大纲未确认
    if ppt_structure and current_scene == "ppt_generate_node" and state.get("ppt_style_confirmed") and not state.get("ppt_url"):
        # PPT大纲确认模式
        print("\n" + format_ppt_outline(ppt_structure))
        confirm_type = "ppt_outline"
        item_name = "PPT大纲"
    elif doc_outline and not state.get("confirmed") and current_scene == "text_generate_node":
        # 文档大纲确认模式
        print("\n" + format_doc_outline(doc_outline))
        confirm_type = "outline"
        item_name = "文档大纲"
    elif task_plan and current_scene == "plan_node":
        # 任务计划确认模式
        print("\n" + format_task_plan(task_plan))
        confirm_type = "plan"
        item_name = "任务计划"
    else:
        logger.warning("[confirm_node] 没有可确认的内容")
        state["error"] = "没有可确认的内容"
        return state
    
    # 命令行交互
    while True:
        print(f"\n请确认{item_name}:")
        print("  [1] 确认执行 - 按照当前内容继续")
        print("  [2] 修改内容 - 重新生成")
        print("  [3] 取消任务 - 结束当前工作流")
        
        try:
            choice = input("\n请输入选项 (1/2/3): ").strip()
            
            if choice == "1":
                state["confirmed"] = True
                state["cancelled"] = False
                state["need_confirm"] = False  # 确认完成，关闭确认开关
                state["messages"].append(f"[confirm_node] 用户确认{item_name}")
                print(f"[已确认] 继续执行...")
                break
                
            elif choice == "2":
                state["confirmed"] = False
                state["cancelled"] = False
                state["need_confirm"] = False  # 临时关闭，重新生成后会再次打开
                
                # 收集用户修改意见
                print(f"\n[修改意见] 请描述您希望如何调整{item_name}:")
                if confirm_type == "outline":
                    print("  例如：增加XXX章节、删除XXX部分、调整顺序等")
                else:
                    print("  例如：不需要生成PPT、文档要更详细、先确认大纲再生成 等")
                
                try:
                    feedback = input("\n您的意见: ").strip()
                    if feedback:
                        if confirm_type == "outline":
                            state["outline_feedback"] = feedback
                        elif confirm_type == "ppt_outline":
                            state["ppt_outline_feedback"] = feedback
                        else:
                            state["plan_feedback"] = feedback
                        state["messages"].append(f"[confirm_node] 用户要求修改: {feedback}")
                    else:
                        feedback_msg = "用户未提供具体意见，请尝试生成不同的方案"
                        if confirm_type == "outline":
                            state["outline_feedback"] = feedback_msg
                        elif confirm_type == "ppt_outline":
                            state["ppt_outline_feedback"] = feedback_msg
                        else:
                            state["plan_feedback"] = feedback_msg
                        state["messages"].append(f"[confirm_node] 用户要求修改，但未提供具体意见")
                except (EOFError, KeyboardInterrupt):
                    feedback_msg = "用户未提供具体意见，请尝试生成不同的方案"
                    if confirm_type == "outline":
                        state["outline_feedback"] = feedback_msg
                    elif confirm_type == "ppt_outline":
                        state["ppt_outline_feedback"] = feedback_msg
                    else:
                        state["plan_feedback"] = feedback_msg
                    state["messages"].append(f"[confirm_node] 用户要求修改(非交互环境)")
                
                # 保存之前的内容供参考
                if confirm_type == "outline":
                    # 大纲修改时保留当前大纲作为参考
                    pass
                else:
                    state["previous_plan"] = task_plan
                
                print(f"[重新生成] 正在根据您的意见重新生成{item_name}...")
                break
                
            elif choice == "3":
                state["confirmed"] = False
                state["cancelled"] = True
                state["need_confirm"] = False
                state["messages"].append("[confirm_node] 用户取消任务")
                print("[已取消] 任务结束")
                break
                
            else:
                print("[警告] 无效输入，请输入 1、2 或 3")
                
        except (EOFError, KeyboardInterrupt):
            # 处理非交互环境或用户中断
            print(f"\n[警告] 检测到非交互环境，自动确认执行")
            state["confirmed"] = True
            state["cancelled"] = False
            state["need_confirm"] = False
            state["messages"].append("[confirm_node] 非交互环境，自动确认")
            break
    
    return state


if __name__ == "__main__":
    import asyncio
    
    # 测试用例1 - 任务计划确认
    print("=" * 50)
    print("测试用例1: 任务计划确认")
    print("=" * 50)
    
    test_state1 = IMState(
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
    
    # result1 = asyncio.run(confirm_node(test_state1))
    # print("\n最终状态:")
    # print(f"  confirmed: {result1.get('confirmed')}")
    # print(f"  cancelled: {result1.get('cancelled')}")
    
    # 测试用例2 - 文档大纲确认
    print("\n" + "=" * 50)
    print("测试用例2: 文档大纲确认")
    print("=" * 50)
    
    test_state2 = IMState(
        workflow_id="test_002",
        user_id="user_123",
        user_input="生成会议纪要",
        source="test",
        chat_id="test_chat",
        messages=["[text_generate_node] 生成文档大纲"],
        intent={"intent_type": "meeting_summary", "topic": "产品评审会议"},
        doc_outline={
            "title": "产品评审会议纪要 - 2026.04.24",
            "doc_type": "meeting_summary",
            "sections": [
                {
                    "heading": "会议概述",
                    "points": ["会议时间", "参会人员", "会议主题"]
                },
                {
                    "heading": "讨论要点",
                    "points": ["用户增长策略", "技术架构升级"]
                },
                {
                    "heading": "决议事项",
                    "points": ["确定方案A", "排期确认"]
                },
                {
                    "heading": "待办事项",
                    "points": ["设计稿输出", "技术方案评审"]
                }
            ]
        },
        need_confirm=True,
        current_scene_before_confirm="text_generate_node"
    )
    
    result2 = asyncio.run(confirm_node(test_state2))
    print("\n最终状态:")
    print(f"  confirmed: {result2.get('confirmed')}")
    print(f"  cancelled: {result2.get('cancelled')}")
    print(f"  outline_feedback: {result2.get('outline_feedback')}")
