from langchain_openai import ChatOpenAI
from settings import settings

api_key = settings.DASHSCOPE_API_KEY

qwen_llm = ChatOpenAI(
    # 模型名称从 .env 读取，方便跟随百炼模型版本升级；默认值见 settings.Settings
    model=settings.QWEN_MODEL,
    base_url=settings.LLM_BASE_URL,
    api_key=api_key
)

deepseek_llm = ChatOpenAI(
    # DeepSeek 也通过百炼 OpenAI compatible mode 调用，模型名同样交给配置管理
    model=settings.DEEPSEEK_MODEL,
    base_url=settings.LLM_BASE_URL,
    api_key=api_key
)
