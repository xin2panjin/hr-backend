from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema
from agents.candidate.state import CandidateEventType
from services.candidate_workflow_service import CandidateWorkflowService


async def run_candidate_agent_by_id(candidate_id: str):
    """BackgroundTask 入口：候选人创建后交给工作流服务处理。"""
    return await CandidateWorkflowService().on_candidate_created(candidate_id)


async def run_candidate_agent(
    candidate: CandidateSchema,
    position: PositionSchema,
    interviewer: UserSchema,
):
    """兼容旧调用方：直接传入上下文时仍通过统一工作流服务调用 Agent。"""
    response = await CandidateWorkflowService().run_candidate_agent(
        candidate=candidate,
        position=position,
        interviewer=interviewer,
        event_type=CandidateEventType.CANDIDATE_CREATED,
        messages=[
            {
                "role": "user",
                "content": (
                    "候选人创建事件："
                    f"candidate_id={candidate.id}，"
                    f"position_id={position.id}，"
                    f"interviewer_id={interviewer.id}"
                ),
            }
        ],
    )
    print(response)
    return response
