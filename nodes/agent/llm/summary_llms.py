from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

from nodes.agent.prompt.summary_prompt import CONTEXT_COMPRESSION_PROMPT
from utils.envUtils import QWEN_KEY, QWEN_MODEL,QWEN_URL

summary_llm = ChatOpenAI(
    model=QWEN_MODEL,
    temperature=0.2,
    openai_api_key=QWEN_KEY,
    base_url=QWEN_URL
)


context_chain = PromptTemplate.from_template(CONTEXT_COMPRESSION_PROMPT) | summary_llm | StrOutputParser()
