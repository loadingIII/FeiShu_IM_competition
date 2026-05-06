from typing import TypedDict, Annotated, Optional, List, Dict
import operator


def last_value(left, right):
    """保留最后一个值，用于处理并行更新"""
    return right


class IMState(TypedDict):
    """Agent 全局状态：贯穿整个工作流执行过程的共享数据容器"""
    # 基础信息（不会被并行节点修改）
    workflow_id: str  # 工作流实例唯一ID，用于日志追踪和幂等校验
    user_id: str  # 发起请求的用户ID，用于权限校验和个性化配置
    user_input: str  # 用户原始输入文本，整个工作流的处理源头
    source: str  # 请求来源：feishu_im(飞书群聊) / h5(网页端)
    chat_id: Optional[str]  # 飞书群聊ID，用于拉取群聊历史消息

    # 场景 A(意图识别) 输出（不会被并行节点修改）
    intent: Optional[Dict]  # 意图识别结果：包含类型、主题、关键点、置信度
    chat_context: str  # 上下文增强信息：飞书来源时包含群聊历史摘要

    # 场景 B(任务理解与规划) 输出（不会被并行节点修改）
    task_plan: Optional[Dict]  # 完整任务执行计划：定义后续工作流执行路径

    # ===== 文档生成相关状态 =====
    doc_outline: Annotated[Optional[Dict], last_value]  # 生成的文档大纲，用于人工确认
    outline_feedback: Annotated[Optional[str], last_value]  # 用户对文档大纲的修改意见
    doc_content: Annotated[Optional[Dict], last_value]  # 完整文档结构化内容
    doc_url: Annotated[str, last_value]  # 生成的飞书文档在线访问链接

    # ===== PPT生成相关状态 =====
    ppt_outline: Annotated[Optional[Dict], last_value]  # 生成的PPT大纲，用于人工确认
    ppt_outline_feedback: Annotated[Optional[str], last_value]  # 用户对PPT大纲的修改意见
    ppt_content: Annotated[Optional[Dict], last_value]  # PPT详细内容结构
    ppt_content_feedback: Annotated[Optional[str], last_value]  # 用户对PPT内容的修改意见
    ppt_url: Annotated[str, last_value]  # 生成的PPT本地文件路径
    ppt_id: Annotated[Optional[str], last_value]  # PPT的ID，用于查询状态

    # 场景 F(总结与交付) 输出
    delivery: Optional[Dict]  # 最终交付结果汇总：包含所有生成链接、执行总结

    # ===== 控制流字段 =====
    messages: Annotated[List[str], operator.add]  # 工作流执行日志，所有节点追加日志
    current_scene: Annotated[str, last_value]  # 当前正在执行的场景标识，用于状态追踪
    current_scene_before_confirm: Annotated[Optional[str], last_value]  # 进入确认节点前的场景标识
    
    # 确认控制
    need_confirm: Annotated[bool, last_value]  # 是否触发确认节点
    confirmed: Annotated[bool, last_value]  # 用户是否确认
    cancelled: Annotated[bool, last_value]  # 用户是否取消任务
    confirm_type: Annotated[Optional[str], last_value]  # 确认类型标识
    
    # 错误处理
    error: Annotated[Optional[str], last_value]  # 异常信息存储
    
    # 任务规划相关（用于重新规划）
    plan_feedback: Annotated[Optional[str], last_value]  # 用户对计划的修改意见
    previous_plan: Annotated[Optional[Dict], last_value]  # 之前的任务计划
    
    # 执行追踪
    doc_generation_completed: Annotated[bool, last_value]  # 文档生成是否已完成
    ppt_generation_completed: Annotated[bool, last_value]  # PPT生成是否已完成

    # 历史上下文
    chat_history: Annotated[Optional[List[Dict]], last_value]  # 聊天对话历史 [{role, content}]
