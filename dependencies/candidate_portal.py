from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.candidate_portal_auth_service import CandidatePortalAuthService

candidate_portal_security = HTTPBearer()


def get_candidate_portal_email(
    auth: HTTPAuthorizationCredentials = Security(candidate_portal_security),
) -> str:
    """解析候选人门户 token，不进入员工身份和 RBAC 依赖链。"""

    return CandidatePortalAuthService().decode_access_token(auth.credentials)
