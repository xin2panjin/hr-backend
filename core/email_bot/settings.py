from __future__ import annotations
from pydantic import Field, BaseModel


class EmailBotSettings(BaseModel):
    """
    EmailBot配置
    * IMAP（Internet Message Access Protocol，互联网消息访问协议） 是一种应用层通信协议，用于电子邮件客户端从远程邮件服务器访问、检索和管理电子邮件。
    * SMTP（Simple Mail Transfer Protocol，简单邮件传输协议） 是一种应用层通信协议，专门用于在互联网上发送和中转电子邮件。
    """
    # IMAP：用于收邮件
    imap_host: str = Field(..., description="IMAP协议邮件服务器的主机")
    imap_port: int = Field(993, description="IMAP协议邮件服务器的端口号")
    imap_ssl: bool = Field(True, description="使用SSL协议")
    imap_mailbox: str = Field("INBOX", description="标准默认收件箱名称")

    # SMTP：用于发邮件
    smtp_host: str = Field(..., description="SMTP协议邮件服务器的主机")
    smtp_port: int = Field(587, description="SMTP协议邮件服务器的端口号")
    smtp_starttls: bool = Field(True, description="使用TLS协议")

    # Polling helpers
    default_fetch_limit: int = Field(10, description="每次检测最新的多少封邮件")

    email: str = Field(..., description="邮箱账号")
    password: str = Field(..., description="邮箱密码")