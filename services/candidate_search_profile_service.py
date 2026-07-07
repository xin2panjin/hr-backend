from models.candidate import CandidateModel
from models.candidate_search import CandidateIndexEventTypeEnum
from repository.candidate_search_repo import (
    CandidateIndexOutboxRepo,
    CandidateSearchProfileRepo,
)

class CandidateSearchProfileService:
    """候选人语义检索画像服务。

    第一阶段只负责生成脱敏画像和写 outbox。
    不在这里直接调用 Milvus，避免业务事务和向量库写入强耦合。
    """

    def __init__(
        self,
        profile_repo: CandidateSearchProfileRepo,
        outbox_repo: CandidateIndexOutboxRepo,
    ):
        self.profile_repo = profile_repo
        self.outbox_repo = outbox_repo

    async def rebuild_candidate_profile(self, candidate: CandidateModel):
        """重建单个候选人的检索画像，并写入索引同步事件。"""

        old_profile = await self.profile_repo.get_by_candidate_id(candidate.id)
        next_version = 1 if old_profile is None else old_profile.profile_version + 1

        profile_text = self.build_profile_text(candidate)

        profile = await self.profile_repo.upsert_profile(
            candidate_id=candidate.id,
            profile_text=profile_text,
            profile_version=next_version,
        )

        await self.outbox_repo.create_event(
            candidate_id=candidate.id,
            event_type=CandidateIndexEventTypeEnum.UPSERT,
            profile_version=next_version,
        )

        return profile

    def build_profile_text(self, candidate: CandidateModel) -> str:
        """生成脱敏后的候选人画像文本。

        注意：这里不能写入手机号、邮箱、生日、原始简历路径等敏感信息。
        """

        position = candidate.position

        parts = [
            f"候选人姓名：{candidate.name}",
            f"当前状态：{candidate.status.value if candidate.status else ''}",
            f"应聘岗位：{position.title if position else ''}",
            f"技能：{candidate.skills or ''}",
            f"工作经历：{candidate.work_experience or ''}",
            f"项目经历：{candidate.project_experience or ''}",
            f"教育经历：{candidate.education_experience or ''}",
            f"自我评价：{candidate.self_evaluation or ''}",
            f"其他信息：{candidate.other_information or ''}",
        ]

        return "\n".join(part for part in parts if part.strip())