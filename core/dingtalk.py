from urllib.parse import urljoin

class DingTalkApi:
    dingtalk_api_base_url: str = "https://api.dingtalk.com"

    @classmethod
    def build_access_token_url(cls):
        return urljoin(cls.dingtalk_api_base_url, "/v1.0/oauth2/userAccessToken")

    @classmethod
    def build_get_my_info_url(cls):
        return urljoin(cls.dingtalk_api_base_url, "/v1.0/contact/users/me")