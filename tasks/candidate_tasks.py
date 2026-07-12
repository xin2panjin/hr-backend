from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema
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
        messages=[
            {
                "role": "user",
                "content": (
                    f"候选人信息：{candidate.model_dump_json()}，"
                    f"职位信息：{position.model_dump_json()}"
                ),
            }
        ],
    )
    print(response)
    return response
