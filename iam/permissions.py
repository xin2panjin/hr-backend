"""固定权限码与系统默认角色定义。

权限码由代码维护，数据库只保存其关联关系和审计数据，管理端不能创建未知
权限码。这能避免字符串拼写错误或配置漂移造成的意外越权。
"""

from dataclasses import dataclass
from enum import StrEnum


class PermissionCode(StrEnum):
    USER_READ = "user.read"
    USER_INVITE = "user.invite"
    USER_UPDATE = "user.update"
    USER_DISABLE = "user.disable"
    USER_RESET_PASSWORD = "user.reset_password"
    USER_SESSION_REVOKE = "user.session.revoke"

    ROLE_READ = "role.read"
    ROLE_ASSIGN = "role.assign"
    ROLE_UPDATE_PERMISSIONS = "role.update_permissions"
    AUDIT_READ = "audit.read"

    DEPARTMENT_READ = "department.read"
    DEPARTMENT_CREATE = "department.create"
    DEPARTMENT_UPDATE = "department.update"
    DEPARTMENT_ARCHIVE = "department.archive"

    POSITION_READ = "position.read"
    POSITION_CREATE = "position.create"
    POSITION_DELETE = "position.delete"

    CANDIDATE_READ = "candidate.read"
    CANDIDATE_CREATE = "candidate.create"
    CANDIDATE_UPDATE_STATUS = "candidate.update_status"
    CANDIDATE_READ_AI_SCORE = "candidate.read_ai_score"

    RESUME_UPLOAD = "resume.upload"
    RESUME_PARSE = "resume.parse"
    TALENT_SEARCH_QUERY = "talent_search.query"
    ASSISTANT_USE = "assistant.use"
    CANDIDATE_COMMUNICATION_USE = "candidate.communication.use"
    KNOWLEDGE_DOCUMENT_MANAGE = "knowledge.document_manage"


class RoleCode(StrEnum):
    """固定系统角色的正式机器编码，展示名称由角色定义提供。"""

    SYSTEM_ADMIN = "ROLE_SYSTEM_ADMIN"
    HR_ADMIN = "ROLE_HR_ADMIN"
    RECRUITER = "ROLE_HR_RECRUITER"
    HIRING_MANAGER = "ROLE_HIRING_MANAGER"
    EMPLOYEE = "ROLE_EMPLOYEE"


@dataclass(frozen=True)
class SystemRoleDefinition:
    code: RoleCode
    name: str
    description: str
    permissions: frozenset[PermissionCode]


ALL_PERMISSIONS = frozenset(PermissionCode)


# 管理端展示只使用中文模块与操作名称；权限码仅是后端授权契约。
PERMISSION_VIEW_GROUPS = {
    "user": ("用户与组织", 10),
    "role": ("角色与权限", 20),
    "department": ("用户与组织", 10),
    "position": ("职位管理", 30),
    "candidate": ("候选人管理", 40),
    "resume": ("简历管理", 50),
    "talent_search": ("人才搜索", 60),
    "assistant": ("招聘助手", 70),
    "knowledge": ("知识库管理", 75),
    "audit": ("审计与安全", 80),
}

PERMISSION_VIEW_METADATA = {
    PermissionCode.USER_READ: ("查看用户", "查看用户基础资料和账号状态"),
    PermissionCode.USER_INVITE: ("邀请用户", "创建带初始角色和部门范围的用户邀请"),
    PermissionCode.USER_UPDATE: ("编辑用户", "修改用户资料和主所属部门"),
    PermissionCode.USER_DISABLE: ("启用或停用账号", "修改账号状态并使原会话失效"),
    PermissionCode.USER_RESET_PASSWORD: ("重置用户密码", "为其他用户重置登录密码"),
    PermissionCode.USER_SESSION_REVOKE: ("撤销用户会话", "撤销其他用户的有效登录设备"),
    PermissionCode.ROLE_READ: ("查看角色权限", "查看角色的业务权限配置"),
    PermissionCode.ROLE_ASSIGN: ("授予用户角色", "为用户授予、撤销角色或调整部门范围"),
    PermissionCode.ROLE_UPDATE_PERMISSIONS: ("编辑角色权限", "调整既有权限项在角色中的勾选关系"),
    PermissionCode.DEPARTMENT_READ: ("查看部门", "查看组织架构和部门详情"),
    PermissionCode.DEPARTMENT_CREATE: ("新增部门", "创建组织部门或子部门"),
    PermissionCode.DEPARTMENT_UPDATE: ("编辑部门", "调整部门名称、编码、描述和上级部门"),
    PermissionCode.DEPARTMENT_ARCHIVE: ("归档部门", "归档无有效依赖的部门"),
    PermissionCode.POSITION_READ: ("查看职位", "查看可访问范围内的职位"),
    PermissionCode.POSITION_CREATE: ("新建职位", "创建职位"),
    PermissionCode.POSITION_DELETE: ("删除职位", "关闭或删除可管理的职位"),
    PermissionCode.CANDIDATE_READ: ("查看候选人", "查看可访问范围内的候选人"),
    PermissionCode.CANDIDATE_CREATE: ("新增候选人", "创建候选人记录"),
    PermissionCode.CANDIDATE_UPDATE_STATUS: ("更新招聘状态", "推进候选人招聘流程"),
    PermissionCode.CANDIDATE_READ_AI_SCORE: ("查看 AI 评分", "查看候选人的 AI 评估结果"),
    PermissionCode.RESUME_UPLOAD: ("上传简历", "上传候选人简历"),
    PermissionCode.RESUME_PARSE: ("解析简历", "发起简历解析"),
    PermissionCode.TALENT_SEARCH_QUERY: ("检索人才", "使用人才库检索能力"),
    PermissionCode.ASSISTANT_USE: ("使用招聘助手", "使用招聘智能助手"),
    PermissionCode.CANDIDATE_COMMUNICATION_USE: ("使用候选人沟通", "查看候选人会话、洞察和待办"),
    PermissionCode.KNOWLEDGE_DOCUMENT_MANAGE: (
        "管理制度知识库",
        "上传、重建、归档企业制度文档并查看索引状态",
    ),
    PermissionCode.AUDIT_READ: ("查看审计日志", "查看敏感操作和权限变更记录"),
}

SYSTEM_ROLE_DEFINITIONS = (
    SystemRoleDefinition(
        code=RoleCode.SYSTEM_ADMIN,
        name="系统管理员",
        description="管理系统、用户、角色与全部业务数据",
        permissions=ALL_PERMISSIONS,
    ),
    SystemRoleDefinition(
        code=RoleCode.HR_ADMIN,
        name="招聘管理员",
        description="管理招聘业务、招聘用户和招聘配置",
        permissions=frozenset(
            {
                PermissionCode.USER_READ,
                PermissionCode.USER_INVITE,
                PermissionCode.USER_UPDATE,
                PermissionCode.USER_DISABLE,
                PermissionCode.ROLE_READ,
                PermissionCode.ROLE_ASSIGN,
                PermissionCode.DEPARTMENT_READ,
                PermissionCode.POSITION_READ,
                PermissionCode.POSITION_CREATE,
                PermissionCode.POSITION_DELETE,
                PermissionCode.CANDIDATE_READ,
                PermissionCode.CANDIDATE_CREATE,
                PermissionCode.CANDIDATE_UPDATE_STATUS,
                PermissionCode.CANDIDATE_READ_AI_SCORE,
                PermissionCode.RESUME_UPLOAD,
                PermissionCode.RESUME_PARSE,
                PermissionCode.TALENT_SEARCH_QUERY,
                PermissionCode.ASSISTANT_USE,
                PermissionCode.CANDIDATE_COMMUNICATION_USE,
                PermissionCode.KNOWLEDGE_DOCUMENT_MANAGE,
            }
        ),
    ),
    SystemRoleDefinition(
        code=RoleCode.RECRUITER,
        name="招聘专员",
        description="在负责部门范围内执行招聘工作",
        permissions=frozenset(
            {
                PermissionCode.POSITION_READ,
                PermissionCode.POSITION_CREATE,
                PermissionCode.CANDIDATE_READ,
                PermissionCode.CANDIDATE_CREATE,
                PermissionCode.CANDIDATE_UPDATE_STATUS,
                PermissionCode.CANDIDATE_READ_AI_SCORE,
                PermissionCode.RESUME_UPLOAD,
                PermissionCode.RESUME_PARSE,
                PermissionCode.TALENT_SEARCH_QUERY,
                PermissionCode.ASSISTANT_USE,
                PermissionCode.CANDIDATE_COMMUNICATION_USE,
            }
        ),
    ),
    SystemRoleDefinition(
        code=RoleCode.HIRING_MANAGER,
        name="用人部门负责人",
        description="管理本人创建职位及其候选人",
        permissions=frozenset(
            {
                PermissionCode.POSITION_READ,
                PermissionCode.POSITION_CREATE,
                PermissionCode.POSITION_DELETE,
                PermissionCode.CANDIDATE_READ,
                PermissionCode.CANDIDATE_CREATE,
                PermissionCode.CANDIDATE_UPDATE_STATUS,
                PermissionCode.CANDIDATE_READ_AI_SCORE,
                PermissionCode.RESUME_UPLOAD,
                PermissionCode.RESUME_PARSE,
                PermissionCode.TALENT_SEARCH_QUERY,
                PermissionCode.CANDIDATE_COMMUNICATION_USE,
            }
        ),
    ),
    SystemRoleDefinition(
        code=RoleCode.EMPLOYEE,
        name="普通员工",
        description="维护个人资料并上传、解析本人简历",
        permissions=frozenset(
            {
                PermissionCode.RESUME_UPLOAD,
                PermissionCode.RESUME_PARSE,
            }
        ),
    ),
)
