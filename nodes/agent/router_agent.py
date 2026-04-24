"""创建意图识别的Agent"""
from langchain.agents import create_agent
from nodes.agent.llm.router_llms import router_llm
from nodes.agent.prompt.router_prompt import router_prompt


router_agent = create_agent(
    model=router_llm,
    system_prompt=router_prompt
)



if __name__ == "__main__":
    res = router_agent.invoke(input={"messages": [{"role": "user", "content": "帮我创建一个文档，内容是关于人工智能的介绍"}]})
    print(res["messages"][-1].content)
