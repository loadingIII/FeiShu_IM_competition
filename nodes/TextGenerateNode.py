from state.state import IMState


async def text_generate_node(state: IMState) -> IMState:
    """场景C：文档生成"""
    state["current_scene"] = "text_generate_node"
    state["messages"].append("[text_generate_node] 开始文档生成")

    # Step C1: 文档大纲生成
    # TODO: 调用LLM生成文档大纲
    doc_outline = {
        "title": "产品评审会议纪要 - 2026.04.24",
        "sections": [
            {"heading": "会议概述", "points": ["时间", "参会人", "议题"]},
            {"heading": "讨论要点", "points": ["用户增长策略", "技术架构升级"]},
            {"heading": "决议事项", "points": []},
            {"heading": "待办事项", "points": []}
        ]
    }
    state["doc_outline"] = doc_outline

    # Step C2: 等待用户确认大纲（实际场景中会在此暂停）
    # TODO: 实现大纲确认逻辑

    # Step C3: LLM逐节展开内容
    # TODO: 生成详细文档内容
    doc_content = {
        "title": doc_outline["title"],
        "sections": [
            {"heading": "会议概述", "content": "本次会议于2026年4月24日召开，参会人员包括产品、技术、运营团队，主要讨论产品下一阶段迭代计划。"},
            {"heading": "讨论要点", "content": "1. 用户增长策略：计划推出邀请返现活动，目标新增用户10万；2. 技术架构升级：采用微服务架构重构核心模块，提升系统稳定性。"}
        ]
    }
    state["doc_content"] = doc_content

    # Step C4: 创建飞书文档并写入
    # TODO: 调用飞书API创建文档
    doc_url = "https://feishu.cn/docx/xxxxxx"
    state["doc_url"] = doc_url

    # Step C5: 广播文档就绪
    # TODO: 实现广播逻辑

    state["messages"].append(f"[text_generate_node] 文档生成完成，链接：{doc_url}")
    return state
