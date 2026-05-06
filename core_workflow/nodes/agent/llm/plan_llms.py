from langchain_openai import ChatOpenAI
from utils.envUtils import QWEN_KEY, ROUTER_MODEL,QWEN_URL

plan_llm = ChatOpenAI(
    model=ROUTER_MODEL,
    temperature=0.5,
    openai_api_key=QWEN_KEY,
    base_url=QWEN_URL,
    timeout=60,
    max_retries=2
)