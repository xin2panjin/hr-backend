import os
from langchain_openai import ChatOpenAI

api_key = os.getenv("DASHSCOPE_API_KEY")

qwen_llm = ChatOpenAI(
    model="qwen3-max",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=api_key
)

deepseek_llm = ChatOpenAI(
    model="deepseek-v3.2",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=api_key
)