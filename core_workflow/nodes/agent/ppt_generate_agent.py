"""PPT生成Agent

提供PPT大纲生成、大纲修改、PPT内容生成等功能
"""
from langchain.agents import create_agent
from nodes.agent.llm.ppt_generate_llms import ppt_generate_llm

# 创建PPT大纲生成Agent
ppt_outline_agent = create_agent(
    model=ppt_generate_llm,
    tools=[],
)

# 创建PPT大纲修改Agent
ppt_outline_revision_agent = create_agent(
    model=ppt_generate_llm,
    tools=[],
)

# 创建PPT内容生成Agent
ppt_content_agent = create_agent(
    model=ppt_generate_llm,
    tools=[],
)

# 创建PPT内容修改Agent
ppt_content_revision_agent = create_agent(
    model=ppt_generate_llm,
    tools=[],
)


__all__ = [
    "ppt_outline_agent",
    "ppt_outline_revision_agent",
    "ppt_content_agent",
    "ppt_content_revision_agent"
]
