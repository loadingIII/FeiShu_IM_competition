from langchain_openai import ChatOpenAI
from utils.envUtils import QWEN_KEY, QWEN_MODEL, QWEN_URL

chat_llm = ChatOpenAI(
    model=QWEN_MODEL,
    temperature=0.7,
    openai_api_key=QWEN_KEY,
    base_url=QWEN_URL
)
