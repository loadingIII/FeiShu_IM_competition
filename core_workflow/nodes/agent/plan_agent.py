from langchain.agents import create_agent
from nodes.agent.llm.plan_llms import plan_llm
from nodes.agent.prompt.plan_prompt import plan_agent_prompt


plan_agent = create_agent(
    model=plan_llm,
    tools=[],
    system_prompt=plan_agent_prompt
)