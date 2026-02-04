from pydantic import BaseModel, Field
from typing import Literal


class ResponseSchema(BaseModel):
    """
    标准 API 响应模型
    """
    result: Literal['success', 'fail'] = Field("success", description="响应消息")