"""文档生成Agent

提供文档大纲生成、大纲修改、文档内容生成等功能
"""
from langchain.agents import create_agent
from nodes.agent.llm.text_generate_llms import text_generate_llm

# 创建大纲生成Agent
outline_agent = create_agent(
    model=text_generate_llm,
    tools=[],
)

# 创建大纲修改Agent
outline_revision_agent = create_agent(
    model=text_generate_llm,
    tools=[],
)

# 创建文档内容生成Agent
content_agent = create_agent(
    model=text_generate_llm,
    tools=[],
)


__all__ = [
    "outline_agent",
    "outline_revision_agent",
    "content_agent"
]
