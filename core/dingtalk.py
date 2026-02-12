from urllib.parse import urljoin
import httpx
from settings import settings
from datetime import datetime
from utils.iso8601 import datetime_to_iso8601_beijing
from urllib.parse import quote


class DingTalkApi:
    dingtalk_api_base_url: str = "https://api.dingtalk.com"

    @classmethod
    def build_access_token_url(cls):
        return urljoin(cls.dingtalk_api_base_url, "/v1.0/oauth2/userAccessToken")

    @classmethod
    def build_get_my_info_url(cls):
        return urljoin(cls.dingtalk_api_base_url, "/v1.0/contact/users/me")

    @classmethod
    def build_get_calendar_list_url(cls, union_id: str, time_min: datetime, time_max: datetime):
        # 将日期转化为ISO-8601的date-time格式
        time_min_iso8601: str = datetime_to_iso8601_beijing(time_min)
        time_max_iso8601: str = datetime_to_iso8601_beijing(time_max)

        # 对时间字符串进行 URL 编码，防止 '+' 被识别为空格
        time_min_encoded = quote(time_min_iso8601)
        time_max_encoded = quote(time_max_iso8601)

        path = f"/v1.0/calendar/users/{union_id}/calendars/primary/events?timeMin={time_min_encoded}&timeMax={time_max_encoded}"
        return urljoin(cls.dingtalk_api_base_url, path)

    @classmethod
    def build_create_calendar_url(self, union_id: str):
        path = f"/v1.0/calendar/users/{union_id}/calendars/primary/events"
        return urljoin(self.dingtalk_api_base_url, path)


class DingTalkHttp:
    async def refresh_access_token(self, refresh_token: str) -> tuple[str, str]:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                url=DingTalkApi.build_access_token_url(),
                json={
                    "clientId": settings.DINGTALK_CLIENT_ID,
                    "clientSecret": settings.DINGTALK_CLIENT_SECRET,
                    "refreshToken": refresh_token,
                    "grantType": "refresh_token",
                }
            )
            if token_resp.status_code != 200:
                raise ValueError(f"Token刷新失败！{token_resp.text}")
            token_data = token_resp.json() or {}
            access_token = token_data.get("accessToken")
            refresh_token = token_data.get("refreshToken")
            return refresh_token, access_token

    async def get_calendar_list(self, union_id: str, access_token: str, time_min: datetime, time_max: datetime):
        url = DingTalkApi.build_get_calendar_list_url(union_id, time_min, time_max)
        headers = {
            "x-acs-dingtalk-access-token": access_token
        }
        async with httpx.AsyncClient() as client:
            calendar_resp = await client.get(url,headers=headers)
            calendar_resp.raise_for_status()
            calendar_data = calendar_resp.json() or {}
            events = calendar_data.get("events")
            return events

    async def create_calendar(self, union_id: str, access_token: str, summary: str, start_datetime: datetime, end_datetime: datetime):
        url = DingTalkApi.build_create_calendar_url(union_id)
        headers = {
            "x-acs-dingtalk-access-token": access_token
        }
        data = {
            "summary": summary,
            "start": {
                "dateTime": datetime_to_iso8601_beijing(start_datetime),
                "timeZone": "Asia/Shanghai",
            },
            "end": {
                "dateTime": datetime_to_iso8601_beijing(end_datetime),
                "timeZone": "Asia/Shanghai",
            }
        }
        async with httpx.AsyncClient() as client:
            calendar_response = await client.post(url, json=data, headers=headers)
            calendar_response.raise_for_status()
            calendar_data = calendar_response.json() or {}
            return calendar_data