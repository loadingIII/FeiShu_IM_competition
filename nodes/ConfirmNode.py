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


def format_ppt_outline(ppt_outline: dict) -> str:
    """格式化PPT大纲为易读的文本"""
    lines = []
    lines.append("=" * 60)
    lines.append(f"[PPT标题] {ppt_outline.get('title', 'N/A')}")
    lines.append(f"[PPT类型] {ppt_outline.get('ppt_type', 'N/A')}")
    lines.append(f"[总页数] {ppt_outline.get('total_pages', 'N/A')}")
    lines.append("=" * 60)
    
    lines.append("\n[页面结构]")
    slides = ppt_outline.get('slides', [])
    for slide in slides:
        page_num = slide.get('page_number', '?')
        slide_type = slide.get('type', 'content')
        title = slide.get('title', '未命名页面')
        layout = slide.get('layout', '-')
        
        type_emoji = {
            'cover': '📔',
            'table_of_contents': '📋',
            'content': '📝',
            'section_divider': '🔖',
            'final': '🎉'
        }.get(slide_type, '📄')
        
        lines.append(f"  {type_emoji} 第{page_num}页 [{slide_type}] {title}")
        
        content = slide.get('content', [])
        if content and slide_type == 'content':
            for point in content:
                lines.append(f"     • {point}")
        
        visual_note = slide.get('visual_note', '')
        if visual_note:
            lines.append(f"     💡 视觉建议: {visual_note}")
        
        lines.append("")
    
    lines.append("=" * 60)
    return "\n".join(lines)


def format_ppt_content(ppt_content: dict) -> str:
    """格式化PPT内容为易读的文本摘要"""
    lines = []
    lines.append("=" * 60)
    lines.append(f"[PPT标题] {ppt_content.get('title', 'N/A')}")
    lines.append(f"[总页数] {ppt_content.get('total_pages', 'N/A')}")
    lines.append("=" * 60)
    
    slides = ppt_content.get('slides', [])
    for slide in slides:
        page_num = slide.get('page_number', '?')
        title = slide.get('title', '未命名页面')
        slide_type = slide.get('type', 'content')
        
        type_emoji = {
            'cover': '📔',
            'table_of_contents': '📋',
            'content': '📝',
            'section_divider': '🔖',
            'final': '🎉'
        }.get(slide_type, '📄')
        
        lines.append(f"\n{type_emoji} 第{page_num}页: {title}")
        
        bullets = slide.get('bullets', [])
        if bullets:
            for bullet in bullets:
                lines.append(f"   • {bullet}")
        
        subtitle = slide.get('subtitle', '')
        if subtitle:
            lines.append(f"   副标题: {subtitle}")
    
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


async def confirm_node(state: IMState) -> IMState:
    """通用确认等待节点 - 命令行交互版本
    
    支持以下确认场景:
    1. 任务计划确认 (plan)
    2. 文档大纲确认 (doc_outline)
    3. PPT大纲确认 (ppt_outline)
    4. PPT内容确认 (ppt_content)
    """
    logger.info("[confirm_node] 进入确认节点")
    state["current_scene"] = "confirm_node"
    state["messages"].append("[confirm_node] 等待用户确认")
    
    # 判断当前需要确认的内容
    task_plan = state.get("task_plan")
    doc_outline = state.get("doc_outline")
    ppt_outline = state.get("ppt_outline")
    ppt_content = state.get("ppt_content")
    current_scene = state.get("current_scene_before_confirm", "")
    confirm_type = state.get("confirm_type", "")
    
    # ========================================
    # Step 1: 处理各类确认场景
    # ========================================
    
    # PPT内容确认（最高优先级，内容已生成完毕）
    if confirm_type == "ppt_content" and ppt_content:
        print("\n" + format_ppt_content(ppt_content))
        item_name = "PPT内容"
    
    # PPT大纲确认
    elif confirm_type == "ppt_outline" and ppt_outline:
        print("\n" + format_ppt_outline(ppt_outline))
        item_name = "PPT大纲"
    
    # 文档大纲确认
    elif confirm_type == "doc_outline" and doc_outline and current_scene == "text_generate_node":
        print("\n" + format_doc_outline(doc_outline))
        item_name = "文档大纲"
    
    # 任务计划确认
    elif task_plan and current_scene == "plan_node":
        print("\n" + format_task_plan(task_plan))
        confirm_type = "task_plan"
        item_name = "任务计划"
    
    else:
        logger.warning("[confirm_node] 没有可确认的内容")
        state["error"] = "没有可确认的内容"
        return state
    
    # 设置确认类型到state，供后续路由使用
    state["confirm_type"] = confirm_type
    
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
                if confirm_type == "doc_outline":
                    print("  例如：增加XXX章节、删除XXX部分、调整顺序等")
                elif confirm_type == "ppt_outline":
                    print("  例如：增加封面页、删除某页内容、调整页面顺序等")
                elif confirm_type == "ppt_content":
                    print("  例如：修改某页标题、调整要点表述、增加数据等")
                else:
                    print("  例如：不需要生成PPT、文档要更详细、先确认大纲再生成 等")
                
                try:
                    feedback = input("\n您的意见: ").strip()
                    if feedback:
                        # 根据确认类型存储反馈到对应字段
                        if confirm_type == "doc_outline":
                            state["outline_feedback"] = feedback
                        elif confirm_type == "ppt_outline":
                            state["ppt_outline_feedback"] = feedback
                        elif confirm_type == "ppt_content":
                            state["ppt_content_feedback"] = feedback
                        else:
                            state["plan_feedback"] = feedback
                        state["messages"].append(f"[confirm_node] 用户要求修改: {feedback}")
                    else:
                        feedback_msg = "用户未提供具体意见，请尝试生成不同的方案"
                        if confirm_type == "doc_outline":
                            state["outline_feedback"] = feedback_msg
                        elif confirm_type == "ppt_outline":
                            state["ppt_outline_feedback"] = feedback_msg
                        elif confirm_type == "ppt_content":
                            state["ppt_content_feedback"] = feedback_msg
                        else:
                            state["plan_feedback"] = feedback_msg
                        state["messages"].append(f"[confirm_node] 用户要求修改，但未提供具体意见")
                except (EOFError, KeyboardInterrupt):
                    feedback_msg = "用户未提供具体意见，请尝试生成不同的方案"
                    if confirm_type == "doc_outline":
                        state["outline_feedback"] = feedback_msg
                    elif confirm_type == "ppt_outline":
                        state["ppt_outline_feedback"] = feedback_msg
                    elif confirm_type == "ppt_content":
                        state["ppt_content_feedback"] = feedback_msg
                    else:
                        state["plan_feedback"] = feedback_msg
                    state["messages"].append(f"[confirm_node] 用户要求修改(非交互环境)")
                
                # 保存之前的内容供参考
                if confirm_type == "task_plan":
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
