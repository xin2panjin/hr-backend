from shortuuid import uuid
from fastapi import APIRouter, Depends
from loguru import logger

from agents.hr_assistant.agent import HRAssistantAgent
from dependencies import get_current_user
from models.user import UserModel
from schemas.hr_assistant_schema import (
    HRAssistantChatReqSchema,
    HRAssistantChatRespSchema,
)

router = APIRouter(prefix="/hr-assistant", tags=["hr-assistant"])


@router.post("/chat", summary="HR招聘助手对话", response_model=HRAssistantChatRespSchema)
async def chat_with_hr_assistant(
    chat_data: HRAssistantChatReqSchema,
    current_user: UserModel = Depends(get_current_user),
):
    conversation_id = chat_data.conversation_id or uuid()
    thread_id = f"hr-assistant:{current_user.id}:{conversation_id}"
    logger.info(
        f"HR助手请求：user_id={current_user.id}, conversation_id={conversation_id}, message={chat_data.message}"
    )
    async with HRAssistantAgent(current_user_id=current_user.id) as agent:
        response = await agent.ainvoke(
            messages=[
                {
                    "role": "user",
                    "content": chat_data.message,
                }
            ],
            thread_id=thread_id,
        )

    messages = response.get("messages", [])
    answer = messages[-1].content if messages else ""
    logger.info(
        f"HR助手响应：user_id={current_user.id}, conversation_id={conversation_id}"
    )
    return {
        "conversation_id": conversation_id,
        "answer": answer,
    }