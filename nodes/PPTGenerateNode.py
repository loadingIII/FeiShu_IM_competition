from state.state import IMState


async def ppt_generate_node(state: IMState) -> IMState:
    """场景D：PPT生成"""
    state["current_scene"] = "ppt_generate_node"
    state["messages"].append("[ppt_generate_node] 开始PPT生成")

    # Step D1: PPT结构规划
    # TODO: 调用LLM生成PPT结构
    ppt_structure = {
        "title": "产品评审汇报",
        "slides": [
            {"page": 1, "type": "cover", "title": "产品评审汇报", "subtitle": "2026.04.24"},
            {"page": 2, "type": "agenda", "title": "汇报大纲", "points": ["讨论要点", "决议事项", "下一步计划"]},
            {"page": 3, "type": "content", "title": "用户增长策略", "points": ["邀请返现活动", "目标新增10万用户"]},
            {"page": 4, "type": "content", "title": "技术架构升级", "points": ["微服务重构", "提升系统稳定性"]},
            {"page": 5, "type": "summary", "title": "总结与下一步", "points": ["5月完成需求评审", "6月上线第一版"]},
            {"page": 6, "type": "ending", "title": "谢谢"}
        ]
    }
    state["ppt_structure"] = ppt_structure

    # Step D2: LLM逐页内容精炼
    # TODO: 精炼PPT内容
    ppt_content = ppt_structure
    state["ppt_content"] = ppt_content

    # Step D3: python-pptx渲染
    # TODO: 渲染PPT文件
    # Step D4: 上传飞书云空间
    # TODO: 上传PPT到飞书
    ppt_url = "https://feishu.cn/file/xxxxxx"
    state["ppt_url"] = ppt_url

    # Step D5: 广播PPT就绪
    # TODO: 实现广播逻辑

    state["messages"].append(f"[ppt_generate_node] PPT生成完成，链接：{ppt_url}")
    return state
