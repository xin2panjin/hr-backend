from agents.candidate import CandidateProcessAgent
from models import AsyncSessionFactory
from repository.candidate_repo import CandidateRepo
from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema


async def run_candidate_agent_by_id(candidate_id: str):
    async with AsyncSessionFactory() as session:
        async with session.begin():
            candidate_model = await CandidateRepo(session).get_by_id(candidate_id)
            if not candidate_model:
                raise ValueError(f"候选人不存在：{candidate_id}")

            candidate = CandidateSchema.model_validate(candidate_model)
            position = PositionSchema.model_validate(candidate_model.position)
            interviewer = UserSchema.model_validate(candidate_model.position.creator)

    return await run_candidate_agent(
        candidate=candidate,
        position=position,
        interviewer=interviewer,
    )


async def run_candidate_agent(
    candidate: CandidateSchema,
    position: PositionSchema,
    interviewer: UserSchema,
):
    async with CandidateProcessAgent(
        candidate=candidate,
        position=position,
        interviewer=interviewer,
    ) as agent:
        response = await agent.ainvoke(
            messages=[
                {
                    "role": "user",
                    "content": f"候选人信息：{candidate.model_dump_json()}，职位信息：{position.model_dump_json()}",
                }
            ],
            thread_id=candidate.email,
        )
        print(response)
        return response
