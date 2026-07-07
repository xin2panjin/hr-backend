from pymilvus import MilvusClient

from settings import settings


def get_milvus_client() -> MilvusClient:
    """创建 Milvus 客户端。

    本项目第一阶段只做客户端连接封装，不在业务请求里临时创建 Collection。
    Collection 初始化由独立脚本负责，避免线上请求被建表逻辑拖慢或误改 schema。
    """
    client_kwargs = {
        "uri": settings.MILVUS_URI,
        "db_name": settings.MILVUS_DATABASE,
    }

    # 本地 Milvus Standalone 默认不需要 token；云服务或开启认证时再配置。
    if settings.MILVUS_TOKEN:
        client_kwargs["token"] = settings.MILVUS_TOKEN

    return MilvusClient(**client_kwargs)