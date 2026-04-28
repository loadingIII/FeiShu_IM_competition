import asyncio
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from utils.feishuUtils import feishu_api
from nodes.agent.text_generate_agent import outline_agent, outline_revision_agent, content_agent
from state.state import IMState
from utils.logger_handler import logger
from nodes.agent.prompt.text_generate_prompt import doc_outline_prompt,doc_outline_revision_prompt


def extract_json(content: str) -> str:
    """从 LLM 返回内容中提取 JSON"""
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if json_match:
        return json_match.group(1).strip()
    return content.strip()


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


def build_outline_messages(state: IMState) -> list:
    """构建大纲生成的消息列表"""
    from datetime import datetime
    
    intent = state["intent"]
    chat_context = state.get("chat_context", "")
    
    topic = intent.get("topic", "未命名文档")
    doc_type = intent.get("additional_info", {}).get("doc_type", "report")
    key_points = intent.get("key_points", [])
    
    # 获取当前日期，格式: YYYY.MM.DD
    current_date = datetime.now().strftime("%Y.%m.%d")
    
    # 检查是否有用户反馈（大纲修改的情况）
    outline_feedback = state.get("outline_feedback")
    current_outline = state.get("doc_outline")
    
    if outline_feedback and current_outline:
        # 用户要求修改大纲
        prompt = doc_outline_revision_prompt.format(
            topic=topic,
            doc_type=doc_type,
            key_points=json.dumps(key_points, ensure_ascii=False),
            context=chat_context,
            current_outline=json.dumps(current_outline, ensure_ascii=False, indent=2),
            user_feedback=outline_feedback,
            current_date=current_date
        )
        logger.info(f"[text_generate_node] 重新生成大纲，用户反馈: {outline_feedback}")
        state["messages"].append(f"[text_generate_node] 根据用户反馈重新生成大纲")
    else:
        # 首次生成大纲
        prompt = doc_outline_prompt.format(
            topic=topic,
            doc_type=doc_type,
            key_points=json.dumps(key_points, ensure_ascii=False),
            context=chat_context,
            current_date=current_date
        )
    
    messages = [
        HumanMessage(content=prompt)
    ]
    return messages


def build_content_messages(doc_outline: dict, chat_context: str) -> list:
    """构建文档内容生成的消息列表"""
    from nodes.agent.prompt.text_generate_prompt import doc_content_prompt
    
    prompt = doc_content_prompt.format(
        doc_outline=json.dumps(doc_outline, ensure_ascii=False, indent=2),
        context=chat_context
    )
    
    messages = [
        HumanMessage(content=prompt)
    ]  
    return messages


async def text_generate_node(state: IMState) -> IMState:
    """场景C：文档生成
    
    执行流程:
    Step C1: 检查用户确认状态
      - 如果是首次进入：生成大纲 → 设置need_confirm=True → 返回等待确认
      - 如果用户已确认(confirmed=True)：执行内容生成
      - 如果用户要求修改(confirmed=False, cancelled=False)：重新生成大纲
      - 如果用户取消(cancelled=True)：直接返回
    """
    state["current_scene"] = "text_generate_node"
    state["messages"].append("[text_generate_node] 进入文档生成节点")
    
    # 检查用户是否取消了任务
    if state.get("cancelled"):
        logger.info("[text_generate_node] 用户已取消任务，跳过文档生成")
        state["messages"].append("[text_generate_node] 用户取消任务，跳过执行")
        return state
    
    # 检查是否已有大纲且用户已确认
    doc_outline = state.get("doc_outline")
    confirmed = state.get("confirmed", False)
    outline_feedback = state.get("outline_feedback")

    if doc_outline and confirmed:
        # 用户已确认大纲，执行内容生成
        logger.info("[text_generate_node] 用户已确认大纲，开始生成文档内容")
        state["messages"].append("[text_generate_node] 用户确认大纲，开始生成内容")
        return await generate_doc_content(state)
    
    if doc_outline and outline_feedback:
        # 用户要求修改大纲，重新生成
        logger.info("[text_generate_node] 用户要求修改大纲，重新生成")
        state["messages"].append("[text_generate_node] 根据用户反馈重新生成大纲")
        # 清除确认状态，重新生成后会再次进入确认流程
        state["confirmed"] = False
        state["need_confirm"] = True
    else:
        # 首次生成大纲
        logger.info("[text_generate_node] 首次生成文档大纲")
        state["messages"].append("[text_generate_node] 首次生成文档大纲")
    
    # Step C1: 文档大纲生成
    messages = build_outline_messages(state)

    # 根据是否有用户反馈选择不同的agent
    if outline_feedback and doc_outline:
        res = await outline_revision_agent.ainvoke({"messages": messages})
    else:
        res = await outline_agent.ainvoke({"messages": messages})
    
    raw_content = res["messages"][-1].content
    json_content = extract_json(raw_content)
    
    try:
        doc_outline = json.loads(json_content)
    except json.JSONDecodeError as e:
        logger.error(f"[text_generate_node] JSON解析失败: {e}")
        logger.error(f"[text_generate_node] 原始内容: {raw_content}")
        state["error"] = f"大纲解析失败: {e}"
        return state
    
    state["doc_outline"] = doc_outline
    state["confirm_type"] = "doc_outline"  # 设置确认类型，用于ConfirmNode路由
    state["current_scene_before_confirm"] = "text_generate_node"  # 记录来源，用于ConfirmNode路由
    state["need_confirm"] = True
    state["confirmed"] = False  # 重置确认状态
    
    # 清理反馈信息（避免影响下次生成）
    state.pop("outline_feedback", None)
    
    # 打印大纲供用户查看（在ConfirmNode中会再次显示）
    logger.info(f"[text_generate_node] 文档大纲生成完成: {doc_outline.get('title')}")
    state["messages"].append(f"[text_generate_node] 文档大纲生成完成，等待用户确认")
    
    return state


async def generate_doc_content(state: IMState) -> IMState:
    """生成文档详细内容（在用户确认大纲后调用）"""
    doc_outline = state.get("doc_outline")
    chat_context = state.get("chat_context", "")
    
    if not doc_outline:
        logger.error("[text_generate_node] 缺少文档大纲，无法生成内容")
        state["error"] = "缺少文档大纲，无法生成内容"
        return state
    
    # Step C3: LLM逐节展开内容
    messages = build_content_messages(doc_outline, chat_context)
    res = await content_agent.ainvoke({"messages": messages})
    
    raw_content = res["messages"][-1].content
    json_content = extract_json(raw_content)
    
    try:
        doc_content = json.loads(json_content)
    except json.JSONDecodeError as e:
        logger.error(f"[text_generate_node] 内容JSON解析失败: {e}")
        logger.error(f"[text_generate_node] 原始内容: {raw_content}")
        state["error"] = f"文档内容解析失败: {e}"
        return state
    
    state["doc_content"] = doc_content
    
    logger.info(f"[text_generate_node] 文档内容生成完成: {doc_content.get('title')}")
    state["messages"].append(f"[text_generate_node] 文档内容生成完成")
    
    # Step C4: 创建飞书文档并写入
    doc_url = await create_feishu_document(state, doc_content)
    state["doc_url"] = doc_url
    state["doc_generation_completed"] = True

    logger.info(f"[text_generate_node] 飞书文档创建完成: {doc_url}")
    state["messages"].append(f"[text_generate_node] 飞书文档创建完成，链接: {doc_url}")
    
    return state


def parse_markdown_to_elements(text: str) -> list:
    """将Markdown文本解析为飞书文档的elements列表
    
    支持:
    - **粗体** → 加粗文本
    - *斜体* → 斜体文本  
    - `代码` → 行内代码
    - [链接](url) → 超链接
    - 普通文本
    """
    elements = []
    import re
    
    # 匹配模式: **粗体**, *斜体*, `代码`, [链接](url), 普通文本
    pattern = r'(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^\)]+\)|[^\[*`]+)'
    
    pos = 0
    while pos < len(text):
        # 尝试匹配各种格式
        matched = False
        
        # 匹配 **粗体**
        bold_match = re.match(r'\*\*([^*]+)\*\*', text[pos:])
        if bold_match:
            content = bold_match.group(1)
            elements.append({
                "text_run": {
                    "content": content,
                    "text_element_style": {"bold": True}
                }
            })
            pos += bold_match.end()
            matched = True
            continue
        
        # 匹配 *斜体*
        italic_match = re.match(r'\*([^*]+)\*', text[pos:])
        if italic_match:
            content = italic_match.group(1)
            elements.append({
                "text_run": {
                    "content": content,
                    "text_element_style": {"italic": True}
                }
            })
            pos += italic_match.end()
            matched = True
            continue
        
        # 匹配 `代码`
        code_match = re.match(r'`([^`]+)`', text[pos:])
        if code_match:
            content = code_match.group(1)
            elements.append({
                "text_run": {
                    "content": content,
                    "text_element_style": {"inline_code": True}
                }
            })
            pos += code_match.end()
            matched = True
            continue
        
        # 匹配 [链接](url)
        link_match = re.match(r'\[([^\]]+)\]\(([^\)]+)\)', text[pos:])
        if link_match:
            link_text = link_match.group(1)
            link_url = link_match.group(2)
            elements.append({
                "text_run": {
                    "content": link_text,
                    "text_element_style": {
                        "link": {"url": link_url}
                    }
                }
            })
            pos += link_match.end()
            matched = True
            continue
        
        # 普通文本（收集连续的非特殊字符）
        if not matched:
            # 找到下一个特殊字符的位置
            next_special = re.search(r'[\[*`]', text[pos:])
            if next_special:
                end_pos = pos + next_special.start()
            else:
                end_pos = len(text)
            
            if end_pos > pos:
                plain_text = text[pos:end_pos]
                if plain_text:
                    elements.append({
                        "text_run": {"content": plain_text}
                    })
                pos = end_pos
            else:
                # 避免无限循环，跳过当前字符
                pos += 1
    
    return elements if elements else [{"text_run": {"content": text}}]


def parse_content_to_blocks(content: str) -> list:
    """将内容解析为飞书文档Block列表
    
    解析Markdown格式:
    - ## 标题 → 标题2 Block
    - ### 标题 → 标题3 Block
    - - 列表项 → 无序列表 Block
    - 1. 列表项 → 有序列表 Block
    - **粗体文本** → 带粗体样式的文本
    - 普通段落 → 文本 Block
    """
    blocks = []
    lines = content.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        if not line:
            i += 1
            continue
        
        # 匹配 ## 标题
        if re.match(r'^##\s+', line):
            heading_text = re.sub(r'^##\s+', '', line)
            # 去除Markdown格式标记
            heading_text = re.sub(r'\*\*', '', heading_text)
            blocks.append({
                "block_type": 4,
                "heading2": {
                    "elements": [{"text_run": {"content": heading_text}}]
                }
            })
            i += 1
            continue
        
        # 匹配 ### 标题
        if re.match(r'^###\s+', line):
            heading_text = re.sub(r'^###\s+', '', line)
            heading_text = re.sub(r'\*\*', '', heading_text)
            blocks.append({
                "block_type": 5,
                "heading3": {
                    "elements": [{"text_run": {"content": heading_text}}]
                }
            })
            i += 1
            continue
        
        # 匹配 - 列表项 或 * 列表项
        if re.match(r'^[-*]\s+', line):
            list_text = re.sub(r'^[-*]\s+', '', line)
            elements = parse_markdown_to_elements(list_text)
            blocks.append({
                "block_type": 12,
                "bullet": {"elements": elements}
            })
            i += 1
            continue
        
        # 匹配 1. 列表项
        if re.match(r'^\d+\.\s+', line):
            list_text = re.sub(r'^\d+\.\s+', '', line)
            elements = parse_markdown_to_elements(list_text)
            blocks.append({
                "block_type": 13,
                "ordered": {"elements": elements}
            })
            i += 1
            continue
        
        # 普通段落（支持行内格式）
        elements = parse_markdown_to_elements(line)
        blocks.append({
            "block_type": 2,
            "text": {"elements": elements}
        })
        i += 1
    
    return blocks


async def create_feishu_document(state: IMState, doc_content: dict) -> str:
    """创建飞书文档并写入内容
    
    实现步骤:
    1. 调用 FeishuAPI.create_document 创建空白文档
    2. 将 doc_content 转换为飞书 Block 结构（支持Markdown格式解析）
    3. 调用 FeishuAPI.create_document_blocks 写入内容块
    4. 返回文档 URL
    
    Args:
        state: 工作流状态
        doc_content: 文档内容，包含 title 和 sections
        
    Returns:
        飞书文档URL
    """

    title = doc_content.get("title", "未命名文档")
    sections = doc_content.get("sections", [])
    
    try:
        # 1. 创建空白文档
        logger.info(f"[create_feishu_document] 开始创建飞书文档: {title}")
        document = await feishu_api.create_document(title=title)
        document_id = document["document_id"]
        logger.info(f"[create_feishu_document] 文档创建成功, document_id: {document_id}")
        
        # 2. 构建文档内容块
        blocks = []
        
        # 添加文档标题（作为页面标题）
        blocks.append({
            "block_type": 3,
            "heading1": {
                "elements": [{"text_run": {"content": title}}]
            }
        })
        
        # 添加各章节内容
        for section in sections:
            # 章节标题
            heading = section.get("heading", "")
            if heading:
                blocks.append({
                    "block_type": 4,
                    "heading2": {
                        "elements": [{"text_run": {"content": heading}}]
                    }
                })
            
            # 要点列表（解析Markdown格式）
            points = section.get("points", [])
            for point in points:
                if point.strip():
                    elements = parse_markdown_to_elements(point.strip())
                    blocks.append({
                        "block_type": 12,
                        "bullet": {"elements": elements}
                    })
            
            # 详细内容（解析Markdown格式）
            content = section.get("content", "")
            if content:
                # 解析内容为Blocks（支持标题、列表、粗体等格式）
                content_blocks = parse_content_to_blocks(content)
                blocks.extend(content_blocks)
        
        # 3. 分批写入内容块（每次最多50个）
        batch_size = 50
        total_blocks = len(blocks)
        logger.info(f"[create_feishu_document] 准备写入 {total_blocks} 个内容块")
        
        for i in range(0, total_blocks, batch_size):
            batch = blocks[i:i + batch_size]
            await feishu_api.create_document_blocks(
                document_id=document_id,
                block_id=document_id,
                children=batch
            )
            logger.info(f"[create_feishu_document] 已写入第 {i//batch_size + 1} 批内容块 ({len(batch)} 个)")
            
            # 频率控制：每秒最多3次请求，添加0.4秒延迟
            if i + batch_size < total_blocks:
                await asyncio.sleep(0.4)
        
        # 4. 构建并返回文档URL
        doc_url = f"https://www.feishu.cn/docx/{document_id}"
        logger.info(f"[create_feishu_document] 文档创建完成: {doc_url}")
        return doc_url
        
    except Exception as e:
        logger.error(f"[create_feishu_document] 创建飞书文档失败: {e}")
        # 返回错误信息或回退到mock URL
        raise


if __name__ == "__main__":
    # 测试用例 - 首次生成大纲
    state = IMState(
        workflow_id="wf_001",
        user_id="123",
        user_input="@Agent-Pilot根据今天的群消息,帮我生成一个总结文档",
        source="feishu_im",
        chat_id="oc_81881e331cd9d7f921771aa884b96742",
        messages=["[router_node] 开始意图识别", "[router_node] 识别到意图：doc_creation"],
        intent={
            "intent_type": "doc_creation",
            "topic": "新功能开发计划总结文档",
            "key_points": ["核心功能规划（用户画像、推荐系统、可视化）", "数据源说明与开发周期评估",
                           "计划调整说明（推荐系统延期至 4 周）", "当前进度状态与后续待办事项"],
            "confidence": 0.95,
            "additional_info": {
                "doc_type": "report"
            }
        },
        chat_context="【任务 / 主题】：新功能开发计划讨论（用户画像、推荐系统、可视化）\n\n【关键信息】：\n- 核心功能：用户画像分析、"
                     "智能推荐系统、数据可视化面板。\n- 数据源：用户注册信息、行为日志数据、第三方数据接口。\n- 开发周期：用户画像 2 周，"
                     "数据可视化 1 周。\n- 计划调整：智能推荐系统因算法调优耗时，由 3 周调整为 4 周。\n- 总工期：共计 7 周。\n\n"
                     "【当前状态】：需求文档已整理，开发周期评估完成，计划已更新确认。\n\n【待办事项】：\n- [ ] 李四更新推荐系统开发时间"
                     "为 4 周 \n- [ ] 按更新后计划执行开发 \n\n【用户偏好 / 约束】：\n- 推荐系统需预留充足时间进行算法调优。"
    )
    
    res = asyncio.run(text_generate_node(state))
    print("\n=== 生成的文档大纲 ===")
    print(format_doc_outline(res.get("doc_outline", {})))
    print(f"\n=== 状态 ===")
    print(f"need_confirm: {res.get('need_confirm')}")
    print(f"confirmed: {res.get('confirmed')}")
