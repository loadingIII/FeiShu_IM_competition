"""PPT生成节点

整合PPT生成Agent技能配置，实现完整的PPT生成流程：
1. 大纲生成 → 2. 用户确认 → 3. 内容生成 → 4. PPT文件制作

该模块与 nodes/agent/skills/pptx 技能模块深度整合，利用PptxGenJS技术栈生成高质量PPT文件。
"""
import asyncio
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Any

from langchain_core.messages import HumanMessage
from state.state import IMState
from utils.logger_handler import logger
from nodes.agent.ppt_generate_agent import (
    ppt_outline_agent,
    ppt_outline_revision_agent,
    ppt_content_agent,
    ppt_content_revision_agent
)
from nodes.agent.prompt.ppt_generate_prompt import (
    ppt_outline_prompt,
    ppt_outline_revision_prompt,
    ppt_content_prompt,
    ppt_content_revision_prompt
)


# ============================================
# 工具函数
# ============================================

def extract_json(content: str) -> str:
    """从 LLM 返回内容中提取 JSON"""
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if json_match:
        return json_match.group(1).strip()
    return content.strip()


def escape_js_string(text: str) -> str:
    """转义JavaScript字符串中的特殊字符
    
    处理:
    - 换行符 -> \\n
    - 双引号 -> \\"
    - 反斜杠 -> \\\\
    - 其他特殊字符
    """
    if not text:
        return ""
    # 先处理反斜杠，再处理其他字符
    text = text.replace('\\', '\\\\')
    text = text.replace('"', '\\"')
    text = text.replace("\n", ' ')
    text = text.replace("\r", ' ')
    text = text.replace("\t", ' ')
    # 移除其他控制字符
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')
    return text


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


# ============================================
# 消息构建函数
# ============================================

def build_outline_messages(state: IMState) -> list:
    """构建PPT大纲生成的消息列表"""
    intent = state.get("intent", {})
    chat_context = state.get("chat_context", "")
    
    topic = intent.get("topic", "未命名PPT")
    ppt_type = intent.get("additional_info", {}).get("ppt_type", "presentation")
    key_points = intent.get("key_points", [])
    target_pages = intent.get("additional_info", {}).get("target_pages", 10)
    
    current_date = datetime.now().strftime("%Y.%m.%d")
    
    # 检查是否有用户反馈（大纲修改的情况）
    outline_feedback = state.get("ppt_outline_feedback")
    current_outline = state.get("ppt_outline")
    
    if outline_feedback and current_outline:
        # 用户要求修改大纲
        prompt = ppt_outline_revision_prompt.format(
            topic=topic,
            ppt_type=ppt_type,
            key_points=json.dumps(key_points, ensure_ascii=False),
            context=chat_context,
            current_outline=json.dumps(current_outline, ensure_ascii=False, indent=2),
            user_feedback=outline_feedback,
            current_date=current_date,
            target_pages=target_pages
        )
        logger.info(f"[ppt_generate_node] 重新生成PPT大纲，用户反馈: {outline_feedback}")
    else:
        # 首次生成大纲
        prompt = ppt_outline_prompt.format(
            topic=topic,
            ppt_type=ppt_type,
            key_points=json.dumps(key_points, ensure_ascii=False),
            context=chat_context,
            current_date=current_date,
            target_pages=target_pages
        )
    
    messages = [HumanMessage(content=prompt)]
    return messages


def build_content_messages(state: IMState) -> list:
    """构建PPT内容生成的消息列表"""
    ppt_outline = state.get("ppt_outline", {})
    chat_context = state.get("chat_context", "")
    
    # 检查是否有用户反馈（内容修改的情况）
    content_feedback = state.get("ppt_content_feedback")
    current_content = state.get("ppt_content")
    
    if content_feedback and current_content:
        # 用户要求修改内容
        prompt = ppt_content_revision_prompt.format(
            ppt_outline=json.dumps(ppt_outline, ensure_ascii=False, indent=2),
            current_content=json.dumps(current_content, ensure_ascii=False, indent=2),
            user_feedback=content_feedback,
            context=chat_context
        )
        logger.info(f"[ppt_generate_node] 重新生成PPT内容，用户反馈: {content_feedback}")
    else:
        # 首次生成内容
        prompt = ppt_content_prompt.format(
            ppt_outline=json.dumps(ppt_outline, ensure_ascii=False, indent=2),
            context=chat_context
        )
    
    messages = [HumanMessage(content=prompt)]
    return messages


# ============================================
# 核心节点函数
# ============================================

def get_ppt_generation_stage(state: IMState) -> str:
    """判断当前PPT生成阶段
    
    Returns:
        - "outline": 需要生成大纲
        - "content": 需要生成内容
        - "file": 需要制作文件
        - "complete": 已完成
    """
    ppt_outline = state.get("ppt_outline")
    ppt_content = state.get("ppt_content")
    ppt_url = state.get("ppt_url")
    
    if ppt_url:
        return "complete"
    if ppt_content:
        return "file"
    if ppt_outline:
        return "content"
    return "outline"


async def ppt_generate_node(state: IMState) -> IMState:
    """PPT生成主节点
    
    执行流程:
    Step 1: 检查用户确认状态
      - 如果是首次进入：生成大纲 → 设置need_confirm=True → 返回等待确认
      - 如果用户已确认大纲(confirmed=True, confirm_type=ppt_outline)：执行内容生成
      - 如果用户已确认内容(confirmed=True, confirm_type=ppt_content)：执行PPT文件制作
      - 如果用户要求修改(confirmed=False, cancelled=False)：重新生成
      - 如果用户取消(cancelled=True)：直接返回
    """
    state["current_scene"] = "ppt_generate_node"
    state["messages"].append("[ppt_generate_node] 进入PPT生成节点")
    
    # 检查用户是否取消了任务
    if state.get("cancelled"):
        logger.info("[ppt_generate_node] 用户已取消任务，跳过PPT生成")
        state["messages"].append("[ppt_generate_node] 用户取消任务，跳过执行")
        return state
    
    # 获取确认类型和确认状态
    confirm_type = state.get("confirm_type", "")
    confirmed = state.get("confirmed", False)
    
    # 检查当前阶段
    stage = get_ppt_generation_stage(state)
    logger.info(f"[ppt_generate_node] 当前PPT生成阶段: {stage}")
    
    # 根据阶段和确认状态执行相应逻辑
    if stage == "complete":
        # PPT已生成完成，直接返回
        logger.info("[ppt_generate_node] PPT已生成完成")
        state["messages"].append("[ppt_generate_node] PPT已生成完成")
        return state
    
    if stage == "file":
        # 已有内容，需要制作文件
        if confirm_type == "ppt_content" and confirmed:
            # 用户已确认内容，执行PPT文件制作
            logger.info("[ppt_generate_node] 用户已确认PPT内容，开始制作PPT文件")
            state["messages"].append("[ppt_generate_node] 用户确认内容，开始制作PPT文件")
            state = await generate_ppt_file(state)
            # 文件生成完成后，标记为完成
            if state.get("ppt_url"):
                state["ppt_generation_completed"] = True
            return state
        elif state.get("ppt_content_feedback"):
            # 用户要求修改内容
            logger.info("[ppt_generate_node] 用户要求修改PPT内容，重新生成")
            state["messages"].append("[ppt_generate_node] 根据用户反馈重新生成PPT内容")
            state["confirmed"] = False
            state["need_confirm"] = True
            state["confirm_type"] = "ppt_content"
            return await generate_ppt_content(state)
        else:
            # 内容已生成但未确认，等待确认
            logger.info("[ppt_generate_node] PPT内容已生成，等待用户确认")
            state["need_confirm"] = True
            state["confirm_type"] = "ppt_content"
            return state
    
    if stage == "content":
        # 已有大纲，需要生成内容
        if confirm_type == "ppt_outline" and confirmed:
            # 用户已确认大纲，执行内容生成
            logger.info("[ppt_generate_node] 用户已确认大纲，开始生成PPT内容")
            state["messages"].append("[ppt_generate_node] 用户确认大纲，开始生成PPT内容")
            return await generate_ppt_content(state)
        elif state.get("ppt_outline_feedback"):
            # 用户要求修改大纲
            logger.info("[ppt_generate_node] 用户要求修改大纲，重新生成")
            state["messages"].append("[ppt_generate_node] 根据用户反馈重新生成大纲")
            state["confirmed"] = False
            state["need_confirm"] = True
            state["confirm_type"] = "ppt_outline"
            return await generate_ppt_outline(state)
        else:
            # 大纲已生成但未确认，等待确认
            logger.info("[ppt_generate_node] PPT大纲已生成，等待用户确认")
            state["need_confirm"] = True
            state["confirm_type"] = "ppt_outline"
            return state
    
    # stage == "outline": 首次进入，生成大纲
    logger.info("[ppt_generate_node] 首次生成PPT大纲")
    state["messages"].append("[ppt_generate_node] 首次生成PPT大纲")
    return await generate_ppt_outline(state)


async def generate_ppt_outline(state: IMState) -> IMState:
    """生成PPT大纲"""
    try:
        messages = build_outline_messages(state)
        
        # 根据是否有用户反馈选择不同的agent
        outline_feedback = state.get("ppt_outline_feedback")
        current_outline = state.get("ppt_outline")
        
        if outline_feedback and current_outline:
            res = await ppt_outline_revision_agent.ainvoke({"messages": messages})
        else:
            res = await ppt_outline_agent.ainvoke({"messages": messages})
        
        raw_content = res["messages"][-1].content
        json_content = extract_json(raw_content)
        
        try:
            ppt_outline = json.loads(json_content)
        except json.JSONDecodeError as e:
            logger.error(f"[ppt_generate_node] PPT大纲JSON解析失败: {e}")
            logger.error(f"[ppt_generate_node] 原始内容: {raw_content}")
            state["error"] = f"PPT大纲解析失败: {e}"
            return state
        
        state["ppt_outline"] = ppt_outline
        state["current_scene_before_confirm"] = "ppt_generate_node"
        state["confirm_type"] = "ppt_outline"
        state["need_confirm"] = True
        state["confirmed"] = False
        
        # 清理反馈信息
        state.pop("ppt_outline_feedback", None)
        
        logger.info(f"[ppt_generate_node] PPT大纲生成完成: {ppt_outline.get('title')}")
        state["messages"].append(f"[ppt_generate_node] PPT大纲生成完成，等待用户确认")
        
        # 记录大纲摘要到日志
        logger.info(f"[ppt_generate_node] 大纲摘要:\n{format_ppt_outline(ppt_outline)}")
        
    except Exception as e:
        logger.error(f"[ppt_generate_node] 生成PPT大纲时出错: {e}")
        state["error"] = f"生成PPT大纲失败: {str(e)}"
    
    return state


async def generate_ppt_content(state: IMState) -> IMState:
    """生成PPT详细内容（在用户确认大纲后调用）"""
    try:
        ppt_outline = state.get("ppt_outline")
        if not ppt_outline:
            logger.error("[ppt_generate_node] 缺少PPT大纲，无法生成内容")
            state["error"] = "缺少PPT大纲，无法生成内容"
            return state
        
        messages = build_content_messages(state)
        
        # 根据是否有用户反馈选择不同的agent
        content_feedback = state.get("ppt_content_feedback")
        current_content = state.get("ppt_content")
        
        if content_feedback and current_content:
            res = await ppt_content_revision_agent.ainvoke({"messages": messages})
        else:
            res = await ppt_content_agent.ainvoke({"messages": messages})
        
        raw_content = res["messages"][-1].content
        json_content = extract_json(raw_content)
        
        try:
            ppt_content = json.loads(json_content)
        except json.JSONDecodeError as e:
            logger.error(f"[ppt_generate_node] PPT内容JSON解析失败: {e}")
            logger.error(f"[ppt_generate_node] 原始内容: {raw_content}")
            state["error"] = f"PPT内容解析失败: {e}"
            return state
        
        state["ppt_content"] = ppt_content
        state["current_scene_before_confirm"] = "ppt_generate_node"
        state["confirm_type"] = "ppt_content"
        state["need_confirm"] = True
        state["confirmed"] = False
        
        # 清理反馈信息
        state.pop("ppt_content_feedback", None)
        
        logger.info(f"[ppt_generate_node] PPT内容生成完成: {ppt_content.get('title')}")
        state["messages"].append(f"[ppt_generate_node] PPT内容生成完成，等待用户确认")
        
        # 记录内容摘要到日志
        logger.info(f"[ppt_generate_node] 内容摘要:\n{format_ppt_content(ppt_content)}")
        
    except Exception as e:
        logger.error(f"[ppt_generate_node] 生成PPT内容时出错: {e}")
        state["error"] = f"生成PPT内容失败: {str(e)}"
    
    return state


# ============================================
# PPT文件制作功能 - 基于SKILL.md设计规范
# ============================================

# 全套配色方案（来自SKILL.md）
COLOR_SCHEMES = {
    'Midnight Executive': {'primary': '1E2761', 'secondary': 'CADCFC', 'accent': 'FFFFFF'},
    'Forest & Moss': {'primary': '2C5F2D', 'secondary': '97BC62', 'accent': 'F5F5F5'},
    'Coral Energy': {'primary': 'F96167', 'secondary': 'F9E795', 'accent': '2F3C7E'},
    'Warm Terracotta': {'primary': 'B85042', 'secondary': 'E7E8D1', 'accent': 'A7BEAE'},
    'Ocean Gradient': {'primary': '065A82', 'secondary': '1C7293', 'accent': '21295C'},
    'Charcoal Minimal': {'primary': '36454F', 'secondary': 'F2F2F2', 'accent': '212121'},
    'Teal Trust': {'primary': '028090', 'secondary': '00A896', 'accent': '02C39A'},
    'Berry & Cream': {'primary': '6D2E46', 'secondary': 'A26769', 'accent': 'ECE2D0'},
    'Sage Calm': {'primary': '84B59F', 'secondary': '69A297', 'accent': '50808E'},
    'Cherry Bold': {'primary': '990011', 'secondary': 'FCF6F5', 'accent': '2F3C7E'},
}

# 字体搭配
FONT_PAIRINGS = {
    'elegant': {'header': 'Georgia', 'body': 'Calibri'},
    'bold': {'header': 'Arial Black', 'body': 'Arial'},
    'clean': {'header': 'Calibri', 'body': 'Calibri Light'},
    'professional': {'header': 'Cambria', 'body': 'Calibri'},
    'modern': {'header': 'Trebuchet MS', 'body': 'Calibri'},
    'classic': {'header': 'Palatino', 'body': 'Garamond'},
    'technical': {'header': 'Consolas', 'body': 'Calibri'},
}

DEFAULT_FONTS = {'header': 'Arial', 'body': 'Arial'}


def resolve_color_scheme(ppt_content: dict) -> dict:
    """根据content中的design或标题智能选择配色"""
    design = ppt_content.get('design', {})
    scheme_name = design.get('color_scheme', '')

    if scheme_name and scheme_name in COLOR_SCHEMES:
        scheme = COLOR_SCHEMES[scheme_name]
    else:
        # 根据标题智能选择
        title = ppt_content.get('title', '')
        title_lower = title.lower()
        if any(w in title_lower for w in ['报告', '汇报', '总结', 'review', 'report']):
            scheme = COLOR_SCHEMES['Midnight Executive']
        elif any(w in title_lower for w in ['培训', '教学', 'course', 'training']):
            scheme = COLOR_SCHEMES['Warm Terracotta']
        elif any(w in title_lower for w in ['创意', '创新', 'creative', 'innovation']):
            scheme = COLOR_SCHEMES['Coral Energy']
        elif any(w in title_lower for w in ['环保', '自然', 'environment', 'nature']):
            scheme = COLOR_SCHEMES['Forest & Moss']
        elif any(w in title_lower for w in ['极简', '简约', 'minimal']):
            scheme = COLOR_SCHEMES['Charcoal Minimal']
        elif any(w in title_lower for w in ['发布', '营销', 'launch', 'marketing']):
            scheme = COLOR_SCHEMES['Cherry Bold']
        else:
            scheme = COLOR_SCHEMES['Ocean Gradient']

    return {
        'primary': scheme['primary'],
        'secondary': scheme['secondary'],
        'accent': scheme['accent'],
        'text': '333333',
        'textLight': '666666',
    }


def resolve_font_pairing(ppt_content: dict) -> dict:
    """根据content中的design解析字体搭配"""
    design = ppt_content.get('design', {})
    pair = design.get('font_pairing', {})
    if isinstance(pair, dict) and 'header' in pair:
        return pair
    return DEFAULT_FONTS


def generate_pptxgenjs_code(ppt_content: dict, output_path: str) -> str:
    """根据PPT内容生成PptxGenJS代码（含丰富布局）"""
    output_path_js = output_path.replace('\\', '/')
    title = escape_js_string(ppt_content.get('title', '未命名PPT'))
    slides = ppt_content.get('slides', [])
    colors = resolve_color_scheme(ppt_content)
    fonts = resolve_font_pairing(ppt_content)

    header_font = fonts['header']
    body_font = fonts['body']

    js_code = f"""const pptxgen = require("pptxgenjs");

let pres = new pptxgen();
pres.layout = 'LAYOUT_16x9';
pres.author = 'AI Assistant';
pres.title = '{title}';
pres.subject = '{title}';

// ── 配色方案 ──
const C = {{
    primary: "{colors['primary']}",
    secondary: "{colors['secondary']}",
    accent: "{colors['accent']}",
    text: "{colors['text']}",
    textLight: "{colors['textLight']}",
}};

// ── 字体 ──
const F = {{ header: "{header_font}", body: "{body_font}" }};

// ── Slide Master ──
pres.defineSlideMaster({{
    title: 'MASTER_SLIDE',
    background: {{ color: 'FFFFFF' }},
    objects: [
        {{ rect: {{ x: 0, y: 0, w: '100%', h: 0.06, fill: {{ color: C.primary }} }} }},
        {{ rect: {{ x: 0, y: 5.525, w: '100%', h: 0.1, fill: {{ color: C.primary, transparency: 90 }} }} }},
    ]
}});

"""

    for slide in slides:
        slide_type = slide.get('type', 'content')
        if slide_type == 'cover':
            js_code += _gen_cover(slide, colors, fonts)
        elif slide_type == 'table_of_contents':
            js_code += _gen_toc(slide, colors, fonts)
        elif slide_type == 'section_divider':
            js_code += _gen_section_divider(slide, colors, fonts)
        elif slide_type == 'final':
            js_code += _gen_final(slide, colors, fonts)
        else:
            js_code += _gen_content(slide, colors, fonts)

    js_code += f"""
pres.writeFile({{ fileName: "{output_path_js}" }})
    .then(() => console.log("OK:{output_path_js}"))
    .catch(err => console.error("ERR:", err));
"""
    return js_code


# ── 封面 ──
def _gen_cover(slide: dict, colors: dict, fonts: dict) -> str:
    t = escape_js_string(slide.get('title', ''))
    st = escape_js_string(slide.get('subtitle', ''))
    date_str = escape_js_string(datetime.now().strftime('%Y年%m月%d日'))
    hf = fonts['header']
    return f'''
(function(){{
let s = pres.addSlide();
s.background = {{ color: C.primary }};
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0, y: 0, w: 10, h: 5.625,
    fill: {{ color: C.primary, transparency: 10 }}
}});
// 装饰线
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0.8, y: 2.0, w: 0.08, h: 1.8,
    fill: {{ color: C.accent, transparency: 20 }}
}});
s.addText("{t}", {{
    x: 1.2, y: 2.0, w: 8, h: 1.4,
    fontSize: 44, fontFace: "{hf}", bold: true,
    color: C.accent, align: "left", valign: "middle", margin: 0
}});
if ("{st}") {{
s.addText("{st}", {{
    x: 1.2, y: 3.6, w: 8, h: 0.7,
    fontSize: 22, fontFace: "{fonts['body']}",
    color: C.secondary, align: "left", valign: "middle", margin: 0
}});
}}
s.addText("{date_str}", {{
    x: 1.2, y: 4.6, w: 4, h: 0.4,
    fontSize: 13, fontFace: "{fonts['body']}",
    color: C.secondary, align: "left", margin: 0
}});
}})();
'''


# ── 目录 ──
def _gen_toc(slide: dict, colors: dict, fonts: dict) -> str:
    t = escape_js_string(slide.get('title', '目录'))
    items = slide.get('bullets', []) or slide.get('content', [])
    hf = fonts['header']
    bf = fonts['body']
    rows = []
    for i, item in enumerate(items, 1):
        txt = escape_js_string(str(item))
        rows.append(f'  {{ text: "{{i}}", options: {{ fontSize: 14, fontFace: "{bf}", color: C.accent, bold: true, breakLine: true }} }},')
        rows.append(f'  {{ text: "{txt}", options: {{ fontSize: 18, fontFace: "{bf}", color: C.text, bullet: false, breakLine: true }} }},')
    rows_code = '\n'.join(rows)

    return f'''
(function(){{
let s = pres.addSlide({{ masterName: "MASTER_SLIDE" }});
s.addText("{t}", {{
    x: 0.8, y: 0.4, w: 8.4, h: 0.7,
    fontSize: 36, fontFace: "{hf}", bold: true,
    color: C.primary, margin: 0
}});
// 下划线装饰
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0.8, y: 1.15, w: 1.2, h: 0.04,
    fill: {{ color: C.primary }}
}});
s.addText([
{rows_code}
], {{
    x: 1.2, y: 1.6, w: 7.6, h: 3.5,
    valign: "top", lineSpacing: 28
}});
}})();
'''


# ── 章节分隔页 ──
def _gen_section_divider(slide: dict, colors: dict, fonts: dict) -> str:
    t = escape_js_string(slide.get('title', ''))
    st = escape_js_string(slide.get('subtitle', ''))
    hf = fonts['header']
    return f'''
(function(){{
let s = pres.addSlide();
s.background = {{ color: C.primary }};
s.addText("{t}", {{
    x: 0.8, y: 1.8, w: 8.4, h: 1.2,
    fontSize: 48, fontFace: "{hf}", bold: true,
    color: C.accent, align: "center", valign: "middle", margin: 0
}});
if ("{st}") {{
s.addText("{st}", {{
    x: 0.8, y: 3.2, w: 8.4, h: 0.8,
    fontSize: 24, fontFace: "{fonts['body']}",
    color: C.secondary, align: "center", valign: "middle", margin: 0
}});
}}
}})();
'''


# ── 结束页 ──
def _gen_final(slide: dict, colors: dict, fonts: dict) -> str:
    t = escape_js_string(slide.get('title', '感谢观看'))
    bullets = slide.get('bullets', []) or slide.get('content', [])
    lines = [escape_js_string(str(b)) for b in bullets]
    hf = fonts['header']
    bf = fonts['body']
    if lines:
        text_arr = ',\n        '.join(
            [f'{{ text: "{l}", options: {{ breakLine: true, fontSize: 16, fontFace: "{bf}", color: C.secondary, align: "center" }} }}' for l in lines]
        )
        extra = f'''
s.addText([
    {text_arr}
], {{
    x: 1, y: 3.8, w: 8, h: 1.2,
    align: "center", valign: "top"
}});
'''
    else:
        extra = ''

    return f'''
(function(){{
let s = pres.addSlide();
s.background = {{ color: C.primary }};
// 装饰线
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0.8, y: 2.0, w: 0.08, h: 1.8,
    fill: {{ color: C.accent, transparency: 20 }}
}});
s.addText("{t}", {{
    x: 1.2, y: 2.0, w: 8, h: 1.4,
    fontSize: 48, fontFace: "{hf}", bold: true,
    color: C.accent, align: "left", valign: "middle", margin: 0
}});
{extra}
}})();
'''


# ── 内容页路由 ──
def _gen_content(slide: dict, colors: dict, fonts: dict) -> str:
    design = slide.get('design', {}) or {}
    layout_variant = design.get('layout_variant', '')

    # 兼容旧格式
    if not layout_variant:
        old_layout = slide.get('layout', '')
        if old_layout == 'two_column':
            layout_variant = 'two_column'
        else:
            layout_variant = 'standard'

    if layout_variant == 'data_callout':
        return _gen_data_callout(slide, colors, fonts)
    elif layout_variant == 'timeline':
        return _gen_timeline(slide, colors, fonts)
    elif layout_variant == 'chart':
        return _gen_chart_slide(slide, colors, fonts)
    elif layout_variant == 'two_column':
        return _gen_two_column(slide, colors, fonts)
    else:
        return _gen_standard(slide, colors, fonts)


# ── 标准内容（标题 + 要点 + 左装饰条） ──
def _gen_standard(slide: dict, colors: dict, fonts: dict) -> str:
    t = escape_js_string(slide.get('title', ''))
    bullets = slide.get('bullets', [])
    if not bullets:
        bullets = slide.get('content', [])
    hf = fonts['header']
    bf = fonts['body']

    items = []
    for b in bullets:
        txt = escape_js_string(str(b))
        items.append(f'{{ text: "{txt}", options: {{ bullet: true, breakLine: true, fontSize: 18, fontFace: "{bf}", color: C.text }} }}')
    bullets_code = ',\n        '.join(items) if items else ''

    return f'''
(function(){{
let s = pres.addSlide({{ masterName: "MASTER_SLIDE" }});
// 标题区
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0, y: 0, w: 10, h: 0.9,
    fill: {{ color: C.primary, transparency: 95 }}
}});
// 左装饰条
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0.3, y: 0.2, w: 0.06, h: 0.5,
    fill: {{ color: C.primary }}
}});
s.addText("{t}", {{
    x: 0.6, y: 0.15, w: 8.8, h: 0.6,
    fontSize: 30, fontFace: "{hf}", bold: true,
    color: C.primary, margin: 0
}});
// 底部装饰线
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0.5, y: 5.2, w: 9, h: 0.02,
    fill: {{ color: C.primary, transparency: 85 }}
}});
// Bullet内容
s.addText([
    {bullets_code}
], {{
    x: 0.7, y: 1.2, w: 8.6, h: 3.8,
    valign: "top", paraSpaceAfter: 8
}});
}})();
'''


# ── 双栏布局 ──
def _gen_two_column(slide: dict, colors: dict, fonts: dict) -> str:
    t = escape_js_string(slide.get('title', ''))
    bullets = slide.get('bullets', [])
    if not bullets:
        bullets = slide.get('content', [])
    hf = fonts['header']
    bf = fonts['body']

    # 平分到两栏
    mid = max(1, len(bullets) // 2 if len(bullets) % 2 == 0 else len(bullets) // 2 + 1)
    left_items = bullets[:mid]
    right_items = bullets[mid:]

    def col_text(items, side_label=''):
        arr = []
        if side_label:
            arr.append(f'{{ text: "{side_label}", options: {{ bold: true, fontSize: 14, fontFace: "{bf}", color: C.accent, breakLine: true }} }}')
        for b in items:
            txt = escape_js_string(str(b))
            arr.append(f'{{ text: "{txt}", options: {{ bullet: true, breakLine: true, fontSize: 15, fontFace: "{bf}", color: C.text }} }}')
        return ',\n        '.join(arr) if arr else ''

    l_code = col_text(left_items)
    r_code = col_text(right_items)

    return f'''
(function(){{
let s = pres.addSlide({{ masterName: "MASTER_SLIDE" }});
s.addText("{t}", {{
    x: 0.6, y: 0.15, w: 8.8, h: 0.6,
    fontSize: 30, fontFace: "{hf}", bold: true,
    color: C.primary, margin: 0
}});
// 左栏背景
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0.4, y: 1.0, w: 4.4, h: 3.8,
    fill: {{ color: C.primary, transparency: 93 }}
}});
// 右栏背景
s.addShape(pres.shapes.RECTANGLE, {{
    x: 5.2, y: 1.0, w: 4.4, h: 3.8,
    fill: {{ color: C.primary, transparency: 93 }}
}});
// 左栏内容
s.addText([
    {l_code}
], {{
    x: 0.6, y: 1.2, w: 4.0, h: 3.4,
    valign: "top", paraSpaceAfter: 6
}});
// 右栏内容
s.addText([
    {r_code}
], {{
    x: 5.4, y: 1.2, w: 4.0, h: 3.4,
    valign: "top", paraSpaceAfter: 6
}});
// 底部装饰线
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0.5, y: 5.2, w: 9, h: 0.02,
    fill: {{ color: C.primary, transparency: 85 }}
}});
}})();
'''


# ── 数据高亮（大号数字） ──
def _gen_data_callout(slide: dict, colors: dict, fonts: dict) -> str:
    t = escape_js_string(slide.get('title', ''))
    bullets = slide.get('bullets', [])
    design = slide.get('design', {})
    callout_data = design.get('callout_data', [])

    if not callout_data:
        # fallback: 用bullets首条
        for b in bullets[:3]:
            parts = str(b).split('：', 1)
            if len(parts) == 2:
                callout_data.append({'value': parts[0], 'label': parts[1]})
            else:
                callout_data.append({'value': parts[0], 'label': ''})

    hf = fonts['header']
    bf = fonts['body']
    n = len(callout_data)
    col_w = 8.0 / max(n, 1)
    start_x = 1.0
    cards = []
    for i, cd in enumerate(callout_data):
        val = escape_js_string(cd.get('value', ''))
        lbl = escape_js_string(cd.get('label', ''))
        cx = start_x + i * col_w
        cards.append(f'''
// 数据卡片 {i+1}
s.addShape(pres.shapes.RECTANGLE, {{
    x: {cx}, y: 2.8, w: {col_w - 0.3}, h: 2.0,
    fill: {{ color: C.primary, transparency: 93 }},
    shadow: {{ type: "outer", blur: 4, offset: 1, color: "000000", opacity: 0.08 }}
}});
s.addText("{val}", {{
    x: {cx}, y: 2.9, w: {col_w - 0.3}, h: 1.0,
    fontSize: 32, fontFace: "{hf}", bold: true,
    color: C.primary, align: "center", valign: "bottom", margin: 0
}});
s.addText("{lbl}", {{
    x: {cx}, y: 3.9, w: {col_w - 0.3}, h: 0.7,
    fontSize: 14, fontFace: "{bf}",
    color: C.textLight, align: "center", valign: "top", margin: 0
}});
''')

    cards_code = '\n'.join(cards)
    bf_code = ',\n        '.join(
        [f'{{ text: "{escape_js_string(str(b))}", options: {{ bullet: true, breakLine: true, fontSize: 15, fontFace: "{bf}", color: C.text }} }}' for b in bullets]
    ) if bullets else ''

    return f'''
(function(){{
let s = pres.addSlide({{ masterName: "MASTER_SLIDE" }});
s.addText("{t}", {{
    x: 0.6, y: 0.15, w: 8.8, h: 0.6,
    fontSize: 30, fontFace: "{hf}", bold: true,
    color: C.primary, margin: 0
}});
{cards_code}
'''.rstrip() + (f'''
s.addText([
    {bf_code}
], {{
    x: 0.7, y: 1.0, w: 8.6, h: 1.5,
    valign: "top", paraSpaceAfter: 4
}});
''' if bf_code else '') + f'''
// 底部装饰线
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0.5, y: 5.2, w: 9, h: 0.02,
    fill: {{ color: C.primary, transparency: 85 }}
}});
}})();
'''


# ── 时间线/流程步骤 ──
def _gen_timeline(slide: dict, colors: dict, fonts: dict) -> str:
    t = escape_js_string(slide.get('title', ''))
    bullets = slide.get('bullets', [])
    if not bullets:
        bullets = slide.get('content', [])
    hf = fonts['header']
    bf = fonts['body']
    n = len(bullets)
    if n == 0:
        return _gen_standard(slide, colors, fonts)

    step_w = min(2.8, 8.4 / max(n, 1))
    steps = []
    for i, b in enumerate(bullets):
        txt = escape_js_string(str(b))
        sx = 0.8 + i * (step_w + 0.2)
        # 圆圈编号
        steps.append(f'''
s.addShape(pres.shapes.OVAL, {{
    x: {sx + step_w/2 - 0.25}, y: 1.4, w: 0.5, h: 0.5,
    fill: {{ color: C.primary }}
}});
s.addText("{i+1}", {{
    x: {sx + step_w/2 - 0.25}, y: 1.4, w: 0.5, h: 0.5,
    fontSize: 18, fontFace: "{bf}", bold: true,
    color: C.accent, align: "center", valign: "middle", margin: 0
}});
// 连接线
if ({i} < {n-1}) {{
s.addShape(pres.shapes.RECTANGLE, {{
    x: {sx + step_w/2 + 0.3}, y: 1.6, w: {step_w - 0.3}, h: 0.04,
    fill: {{ color: C.primary, transparency: 70 }}
}});
}}
s.addText("{txt}", {{
    x: {sx}, y: 2.2, w: {step_w}, h: 2.5,
    fontSize: 14, fontFace: "{bf}",
    color: C.text, valign: "top", wrap: true, margin: 0
}});
''')
    steps_code = '\n'.join(steps)

    return f'''
(function(){{
let s = pres.addSlide({{ masterName: "MASTER_SLIDE" }});
s.addText("{t}", {{
    x: 0.6, y: 0.15, w: 8.8, h: 0.6,
    fontSize: 30, fontFace: "{hf}", bold: true,
    color: C.primary, margin: 0
}});
{steps_code}
// 底部装饰线
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0.5, y: 5.2, w: 9, h: 0.02,
    fill: {{ color: C.primary, transparency: 85 }}
}});
}})();
'''


# ── 图表页 ──
def _gen_chart_slide(slide: dict, colors: dict, fonts: dict) -> str:
    t = escape_js_string(slide.get('title', ''))
    bullets = slide.get('bullets', [])
    design = slide.get('design', {})
    chart_data = design.get('chart', {}) or {}
    hf = fonts['header']
    bf = fonts['body']

    # 解析图表数据
    chart_type = chart_data.get('type', 'bar')
    chart_title = escape_js_string(chart_data.get('title', ''))
    labels = chart_data.get('labels', [])
    datasets = chart_data.get('datasets', [])

    # PPT图表类型映射
    type_map = {
        'bar': 'pres.charts.BAR',
        'pie': 'pres.charts.PIE',
        'line': 'pres.charts.LINE',
        'doughnut': 'pres.charts.DOUGHNUT',
    }
    js_chart_type = type_map.get(chart_type, 'pres.charts.BAR')

    # Chart系列数据
    series = []
    for ds in datasets:
        name = escape_js_string(ds.get('name', ''))
        vals = ds.get('values', [])
        vals_str = ', '.join(str(v) for v in vals)
        series.append(f'{{ name: "{name}", labels: [{", ".join(f"\"{escape_js_string(str(l))}\"" for l in labels)}], values: [{vals_str}] }}')
    series_code = ', '.join(series)

    # Chart配置
    chart_cfg = f'chartColors: [C.primary, C.secondary, "{colors["accent"]}"]'
    if chart_type in ('bar',):
        chart_cfg += ', barDir: "col", showValue: true, dataLabelPosition: "outEnd"'
    elif chart_type == 'pie':
        chart_cfg += ', showPercent: true'
    elif chart_type == 'line':
        chart_cfg += ', lineSize: 3, lineSmooth: true'
    chart_cfg += ', showLegend: false, catAxisLabelColor: C.textLight, valAxisLabelColor: C.textLight'

    bf_code = ',\n        '.join(
        [f'{{ text: "{escape_js_string(str(b))}", options: {{ bullet: true, breakLine: true, fontSize: 14, fontFace: "{bf}", color: C.text }} }}' for b in bullets]
    ) if bullets else ''

    # 有图表时调整布局
    has_chart = bool(series_code and labels)

    return f'''
(function(){{
let s = pres.addSlide({{ masterName: "MASTER_SLIDE" }});
s.addText("{t}", {{
    x: 0.6, y: 0.15, w: 8.8, h: 0.6,
    fontSize: 30, fontFace: "{hf}", bold: true,
    color: C.primary, margin: 0
}});
''' + (f'''
s.addChart({js_chart_type}, [{series_code}], {{
    x: 0.5, y: 0.9, w: 5.5, h: 4.0,
    showTitle: {"true" if chart_title else "false"}, title: "{chart_title}",
    {chart_cfg},
    chartArea: {{ fill: {{ color: "FFFFFF" }}, roundedCorners: true }},
    valGridLine: {{ color: "E2E8F0", size: 0.5 }},
    catGridLine: {{ style: "none" }}
}});
s.addText([
    {bf_code}
], {{
    x: 6.3, y: 0.9, w: 3.3, h: 4.0,
    valign: "top", paraSpaceAfter: 6
}});
''' if has_chart else f'''
s.addText([
    {bf_code}
], {{
    x: 0.7, y: 1.0, w: 8.6, h: 4.0,
    valign: "top", paraSpaceAfter: 8
}});
''') + f'''
// 底部装饰线
s.addShape(pres.shapes.RECTANGLE, {{
    x: 0.5, y: 5.2, w: 9, h: 0.02,
    fill: {{ color: C.primary, transparency: 85 }}
}});
}})();
'''


async def generate_ppt_file(state: IMState) -> IMState:
    """生成PPT文件（在用户确认内容后调用）"""
    ppt_content = state.get("ppt_content")
    
    if not ppt_content:
        logger.error("[ppt_generate_node] 缺少PPT内容，无法制作文件")
        state["error"] = "缺少PPT内容，无法制作PPT文件"
        return state
    
    try:
        # 创建输出目录
        output_dir = os.path.join(os.getcwd(), "output", "ppt")
        os.makedirs(output_dir, exist_ok=True)
        
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[^\w\s-]', '', ppt_content.get('title', '未命名'))[:30]
        output_filename = f"{safe_title}_{timestamp}.pptx"
        output_path = os.path.join(output_dir, output_filename)
        
        # 生成JavaScript代码
        js_code = generate_pptxgenjs_code(ppt_content, output_path)
        
        # 保存JS文件
        js_path = os.path.join(tempfile.gettempdir(), f"ppt_gen_{timestamp}.js")
        with open(js_path, 'w', encoding='utf-8') as f:
            f.write(js_code)
        
        logger.info(f"[ppt_generate_node] JavaScript代码已生成: {js_path}")
        
        # 执行Node.js生成PPT
        try:
            # 设置环境变量确保UTF-8编码
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env['NODE_PATH'] = os.path.join(project_root, 'node_modules')
            result = subprocess.run(
                ['node', js_path],
                capture_output=True,
                text=True,
                timeout=60,
                encoding='utf-8',
                errors='ignore',  # 忽略编码错误
                env=env
            )
            
            if result.returncode == 0:
                logger.info(f"[ppt_generate_node] PPT文件生成成功: {output_path}")
                state["messages"].append(f"[ppt_generate_node] ✅ PPT文件生成成功")
                
                # 更新状态
                state["ppt_url"] = output_path
                state["ppt_generation_completed"] = True
                
                # 存储PPT信息到delivery
                if "delivery" not in state or state["delivery"] is None:
                    state["delivery"] = {}
                
                state["delivery"]["ppt_info"] = {
                    "ppt_id": f"ppt_{timestamp}",
                    "file_path": output_path,
                    "title": ppt_content.get('title', '未命名PPT'),
                    "total_pages": ppt_content.get('total_pages', 0),
                    "generated_at": datetime.now().isoformat()
                }
                
            else:
                error_msg = result.stderr or "未知错误"
                logger.error(f"[ppt_generate_node] PPT生成失败: {error_msg}")
                state["error"] = f"PPT文件生成失败: {error_msg}"
                state["messages"].append(f"[ppt_generate_node] ❌ PPT生成失败: {error_msg}")
                # 标记为完成以防止无限循环，但记录错误
                state["ppt_generation_completed"] = True
                state["ppt_generation_failed"] = True
                
        except subprocess.TimeoutExpired:
            logger.error("[ppt_generate_node] PPT生成超时")
            state["error"] = "PPT文件生成超时"
            state["messages"].append("[ppt_generate_node] ❌ PPT生成超时")
            state["ppt_generation_completed"] = True
            state["ppt_generation_failed"] = True
            
        except FileNotFoundError:
            logger.error("[ppt_generate_node] 未找到Node.js，尝试使用模拟模式")
            # 降级到模拟模式
            state["ppt_url"] = f"mock://{output_path}"
            state["ppt_generation_completed"] = True
            state["messages"].append("[ppt_generate_node] ⚠️ Node.js未安装，使用模拟模式")
            
            if "delivery" not in state or state["delivery"] is None:
                state["delivery"] = {}
            
            state["delivery"]["ppt_info"] = {
                "ppt_id": f"ppt_{timestamp}",
                "file_path": output_path,
                "title": ppt_content.get('title', '未命名PPT'),
                "total_pages": ppt_content.get('total_pages', 0),
                "mock": True,
                "generated_at": datetime.now().isoformat()
            }
        
        # 清理临时文件
        try:
            if os.path.exists(js_path):
                os.remove(js_path)
        except Exception as e:
            logger.warning(f"[ppt_generate_node] 清理临时文件失败: {e}")
        
    except Exception as e:
        logger.error(f"[ppt_generate_node] 制作PPT文件时出错: {e}")
        state["error"] = f"制作PPT文件失败: {str(e)}"
        state["messages"].append(f"[ppt_generate_node] ❌ PPT制作失败: {str(e)}")
        # 标记为完成以防止无限循环
        state["ppt_generation_completed"] = True
        state["ppt_generation_failed"] = True
    
    return state


# ============================================
# 辅助功能函数
# ============================================

async def check_ppt_status_node(state: IMState) -> IMState:
    """查询PPT生成状态节点"""
    state["current_scene"] = "check_ppt_status_node"
    
    ppt_info = state.get("delivery", {}).get("ppt_info", {})
    ppt_id = ppt_info.get("ppt_id", "")
    
    if not ppt_id:
        state["messages"].append("[check_ppt_status_node] ❌ 未找到PPT信息")
        return state
    
    # 检查文件是否存在
    file_path = ppt_info.get("file_path", "")
    if file_path and os.path.exists(file_path):
        state["messages"].append(f"[check_ppt_status_node] ✅ PPT文件已生成")
        state["messages"].append(f"[check_ppt_status_node] 文件路径: {file_path}")
        state["messages"].append(f"[check_ppt_status_node] 页数: {ppt_info.get('total_pages', 'N/A')}")
    else:
        state["messages"].append(f"[check_ppt_status_node] ⏳ PPT正在生成中")
    
    return state


def format_ppt_outline_for_display(ppt_outline: dict) -> str:
    """格式化PPT大纲为用户友好的显示文本"""
    return format_ppt_outline(ppt_outline)


def format_ppt_content_for_display(ppt_content: dict) -> str:
    """格式化PPT内容为用户友好的显示文本"""
    return format_ppt_content(ppt_content)


# ============================================
# 导出
# ============================================

__all__ = [
    "ppt_generate_node",
    "generate_ppt_outline",
    "generate_ppt_content",
    "generate_ppt_file",
    "check_ppt_status_node",
    "format_ppt_outline",
    "format_ppt_content",
    "format_ppt_outline_for_display",
    "format_ppt_content_for_display"
]


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    # 测试用例 - PPT生成流程
    print("=" * 60)
    print("测试用例: PPT生成节点")
    print("=" * 60)
    
    test_state = IMState(
        workflow_id="wf_ppt_001",
        user_id="user_123",
        user_input="帮我制作一个关于Q3产品战略的PPT",
        source="feishu_im",
        chat_id="test_chat",
        messages=[],
        intent={
            "intent_type": "ppt_creation",
            "topic": "Q3产品战略发布会",
            "key_points": ["市场分析", "产品路线图", "技术架构升级", "团队介绍"],
            "confidence": 0.95,
            "additional_info": {
                "ppt_type": "presentation",
                "target_pages": 8
            }
        },
        chat_context="用户需要制作一个面向内部团队的Q3产品战略发布会PPT，重点展示市场分析、产品规划和技术升级。"
    )
    
    async def test_flow():
        # Step 1: 生成大纲
        print("\n>>> Step 1: 生成PPT大纲")
        result = await ppt_generate_node(test_state)
        
        if result.get("error"):
            print(f"错误: {result['error']}")
            return
        
        ppt_outline = result.get("ppt_outline", {})
        print(format_ppt_outline(ppt_outline))
        print(f"\nneed_confirm: {result.get('need_confirm')}")
        print(f"confirm_type: {result.get('confirm_type')}")
        
        # 模拟用户确认大纲
        result["confirmed"] = True
        result["need_confirm"] = False
        
        # Step 2: 生成内容
        print("\n>>> Step 2: 生成PPT内容")
        result = await ppt_generate_node(result)
        
        if result.get("error"):
            print(f"错误: {result['error']}")
            return
        
        ppt_content = result.get("ppt_content", {})
        print(format_ppt_content(ppt_content))
        print(f"\nneed_confirm: {result.get('need_confirm')}")
        print(f"confirm_type: {result.get('confirm_type')}")
        
        # 模拟用户确认内容
        result["confirmed"] = True
        result["need_confirm"] = False
        
        # Step 3: 生成PPT文件
        print("\n>>> Step 3: 制作PPT文件")
        result = await ppt_generate_node(result)
        
        if result.get("error"):
            print(f"错误: {result['error']}")
            return
        
        print(f"\n✅ PPT生成完成!")
        print(f"文件路径: {result.get('ppt_url')}")
        print(f"完成状态: {result.get('ppt_generation_completed')}")
    
    asyncio.run(test_flow())
