from langchain_openai import ChatOpenAI
from utils.envUtils import QWEN_KEY, ROUTER_MODEL,QWEN_URL

router_llm = ChatOpenAI(
    model=ROUTER_MODEL,
    temperature=0.2,
    openai_api_key=QWEN_KEY,
    base_url=QWEN_URL
)





if __name__ == "__main__":
    res = router_llm.invoke("你好啊")
    print(res.content)