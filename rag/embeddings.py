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
        batch_size: int | None = None,
    ):
        self.model = model or settings.EMBEDDING_MODEL
        self.batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
        if self.batch_size < 1:
            raise ValueError("EMBEDDING_BATCH_SIZE 必须大于 0")
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

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量生成文档向量，保持输入文本和返回向量的顺序一致。

        DashScope 等供应商对单次 embeddings 请求有条数上限（例如 10），
        因此这里按 ``batch_size`` 分批请求后再拼接结果。
        """

        if not texts:
            return []

        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            response = await self.client.embeddings.create(
                model=self.model,
                input=batch,
            )
            # OpenAI 兼容接口通常按输入顺序返回；仍按 index 排序以兼容乱序响应。
            batch_embeddings = [
                item.embedding
                for item in sorted(response.data, key=lambda item: item.index)
            ]
            if len(batch_embeddings) != len(batch):
                raise ValueError(
                    "Embedding 返回数量不匹配："
                    f"期望 {len(batch)}，实际 {len(batch_embeddings)}"
                )
            embeddings.extend(batch_embeddings)

        if len(embeddings) != len(texts):
            raise ValueError(
                f"Embedding 返回数量不匹配：期望 {len(texts)}，实际 {len(embeddings)}"
            )
        return embeddings
