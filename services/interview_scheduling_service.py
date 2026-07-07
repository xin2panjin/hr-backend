import json
from datetime import datetime, time, timedelta
from typing import Any

from loguru import logger

from core.cache import DingTalkTokenInfoSchema, HRCache
from core.dingtalk import DingTalkHttp
from core.email_bot import EmailBot, EmailBotSettings
from models import AsyncSessionFactory
from models.candidate import CandidateStatusEnum
from models.interview import InterviewResultEnum
from repository.candidate_repo import CandidateRepo
from repository.interview_repo import InterviewRepo
from repository.user_repo import UserRepo
from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema
from settings import settings
from utils.available_time import find_available_slot
from utils.iso8601 import datetime_to_iso8601_beijing, iso8601_to_datetime_beijing


class InterviewSchedulingService:
    """统一编排候选人邮件、面试官钉钉日程和系统面试记录。"""

    async def get_dingtalk_access_token(self, user_id: str) -> str:
        """使用缓存中的 refresh_token 获取并保存最新钉钉令牌。"""
        cache = HRCache()
        token_info = await cache.get_dingtalk_info(user_id)
        if not token_info:
            raise ValueError(f"{user_id}用户钉钉授权已过期！")

        refresh_token, access_token = await DingTalkHttp().refresh_access_token(
            token_info.refresh_token
        )
        await cache.set_dingtalk_info(
            DingTalkTokenInfoSchema(
                user_id=user_id,
                access_token=access_token,
                refresh_token=refresh_token,
            )
        )
        return access_token

    async def get_available_slots(self, interviewer: UserSchema) -> str:
        """读取未来七天钉钉日程，计算工作时间内的一小时空闲段。"""
        try:
            union_id = await self._get_interviewer_union_id(interviewer.id)
            access_token = await self.get_dingtalk_access_token(interviewer.id)

            # 从明天上午9点开始查询，避免把今天已经过去的时段返回给候选人。
            tomorrow = datetime.now().date() + timedelta(days=1)
            tomorrow_nine = datetime.combine(tomorrow, time(hour=9))
            events: list[dict[str, Any]] = await DingTalkHttp().get_calendar_list(
                union_id=union_id,
                access_token=access_token,
                time_min=tomorrow_nine,
                time_max=tomorrow_nine + timedelta(days=7),
            )
            # 空闲时间算法使用不带时区的北京时间，先统一钉钉返回值的格式。
            busy_slots = [
                (
                    self._as_naive_beijing(event["start"]["dateTime"]),
                    self._as_naive_beijing(event["end"]["dateTime"]),
                )
                for event in events
            ]
            available_slots = find_available_slot(
                busy_slots,
                start_date=tomorrow_nine,
            )
            if not available_slots:
                return "获取面试官可用时间失败：7天内没有空闲时间！"

            # 返回给模型前重新转为带 +08:00 的 ISO 8601 字符串，确保可序列化。
            available_times = [
                (
                    datetime_to_iso8601_beijing(start),
                    datetime_to_iso8601_beijing(end),
                )
                for start, end in available_slots
            ]
            return f"找到面试官可用的时间：{json.dumps(available_times, ensure_ascii=False)}"
        except Exception as exc:
            logger.error(exc)
            return f"获取面试官可用时间失败：{exc}"

    async def send_invitation(
        self,
        candidate: CandidateSchema,
        position: PositionSchema,
        interview_datetime_str: str,
    ) -> str:
        """发送初步面试时间，等待候选人确认或提出新时间。"""
        body = f"""尊敬的{candidate.name}，
您好！
感谢您投递我司{position.title}职位。
我们初步确定了您的面试时间，请您确认是否方便。
面试时间：{interview_datetime_str}
如果方便，请回复“确认”；如果不方便，请回复您方便的时间。
谢谢！
"""
        try:
            await self._send_email(
                to=candidate.email,
                subject="【知了课堂】面试邀请-协商面试时间",
                body=body,
            )
            return f"给候选人发送面试邀请邮件成功！面试时间初步确定为：{interview_datetime_str}"
        except Exception as exc:
            logger.error(exc)
            return f"给候选人发送邮件失败：{exc}"

    async def confirm_interview(
        self,
        candidate: CandidateSchema,
        position: PositionSchema,
        interviewer: UserSchema,
        interview_datetime_str: str,
    ) -> str:
        """确认最终面试时间，并同步外部日程和内部业务数据。"""
        try:
            interview_datetime = iso8601_to_datetime_beijing(interview_datetime_str)
        except Exception as exc:
            return f"{interview_datetime_str}格式化失败！{exc}"

        # 先通知候选人，再创建面试官日程；任一步失败都会返回明确结果给 Agent。
        try:
            await self._send_email(
                to=candidate.email,
                subject="【知了课堂】面试时间确定",
                body=(
                    f"尊敬的{candidate.name}，\n"
                    f"面试时间已确定：{interview_datetime_str}\n"
                    "请您准时参加面试。该邮件无需再回复。谢谢！"
                ),
            )
        except Exception as exc:
            logger.error(exc)
            return f"给候选人发送邮件失败：{exc}"

        # 候选人确认后，为面试官创建一小时的钉钉日程。
        try:
            union_id = await self._get_interviewer_union_id(interviewer.id)
            access_token = await self.get_dingtalk_access_token(interviewer.id)
            await DingTalkHttp().create_calendar(
                union_id=union_id,
                access_token=access_token,
                summary=f"面试安排：{position.title} - {candidate.name}",
                start_datetime=interview_datetime,
                end_datetime=interview_datetime + timedelta(hours=1),
            )
        except Exception as exc:
            return f"给面试官创建钉钉日程安排失败！{exc}"

        # 面试记录和候选人状态在同一数据库事务中提交。
        try:
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    await InterviewRepo(session).create_interview(
                        {
                            "scheduled_time": interview_datetime.replace(tzinfo=None),
                            "result": InterviewResultEnum.PENDING,
                            "candidate_id": candidate.id,
                            "interviewer_id": interviewer.id,
                        }
                    )
                    await CandidateRepo(session).update_candidate_status(
                        candidate_id=candidate.id,
                        status=CandidateStatusEnum.WAITING_FOR_INTERVIEW,
                    )
        except Exception as exc:
            return f"在系统中创建面试预约记录和候选人状态修改失败！{exc}"

        return (
            "给候选人发送面试时间成功；给面试官创建钉钉日程成功；"
            "创建面试预约并将候选人状态修改为待面试成功。"
        )

    async def mark_refused(self, candidate_id: str) -> str:
        """记录候选人主动拒绝面试。"""
        try:
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    await CandidateRepo(session).update_candidate_status(
                        candidate_id=candidate_id,
                        status=CandidateStatusEnum.REFUSED_INTERVIEW,
                    )
            return "已修改候选人状态为拒绝面试！"
        except Exception as exc:
            logger.error(exc)
            return f"修改候选人状态为拒绝面试失败！{exc}"

    async def _get_interviewer_union_id(self, interviewer_id: str) -> str:
        """读取面试官绑定的钉钉 union_id。"""
        async with AsyncSessionFactory() as session:
            async with session.begin():
                dingding_user = await UserRepo(session).get_dingding_user(
                    user_id=interviewer_id
                )
                if not dingding_user:
                    raise ValueError("面试官没有绑定钉钉账号")
                return dingding_user.union_id

    async def _send_email(self, to: str, subject: str, body: str) -> None:
        """根据统一邮箱配置建立连接并发送纯文本邮件。"""
        email_settings = EmailBotSettings(
            imap_host=settings.EMAIL_BOT_IMAP_HOST,
            smtp_host=settings.EMAIL_BOT_SMTP_HOST,
            email=settings.EMAIL_BOT_EMAIL,
            password=settings.EMAIL_BOT_PASSWORD,
        )
        async with EmailBot(email_settings) as bot:
            await bot.send_email(to=to, subject=subject, text=body)

    @staticmethod
    def _as_naive_beijing(value: str) -> datetime:
        """将 ISO 时间统一为不带时区信息的北京时间，供空闲算法比较。"""
        return iso8601_to_datetime_beijing(value).replace(tzinfo=None)
