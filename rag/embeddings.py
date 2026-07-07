from openai import AsyncOpenAI

from settings import settings


class EmbeddingService:
    """Embedding 服务封装。

    第一阶段统一在应用侧生成向量，再写入 Milvus。
    这样 Milvus 只负责向量存储和检索，不绑定具体模型供应商。
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        self.model = model or settings.EMBEDDING_MODEL
        self.client = AsyncOpenAI(
            api_key=api_key or settings.DASHSCOPE_API_KEY,
            base_url=base_url or settings.EMBEDDING_BASE_URL,
        )

    async def embed_query(self, text: str) -> list[float]:
        """生成单条文本向量。"""

        response = await self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding