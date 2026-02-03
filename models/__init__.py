from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncSession
from shortuuid import uuid

from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import DateTime, String

from settings import settings

# 创建异步数据库引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    # 将输出所有执行SQL的日志（默认是关闭的）
    echo=False,
    # 连接池大小（默认是5个）
    pool_size=10,
    # 允许连接池最大的连接数（默认是10个）
    max_overflow=20,
    # 获得连接超时时间（默认是30s）
    pool_timeout=10,
    # 连接回收时间（默认是-1，代表永不回收）
    pool_recycle=3600,
    # 连接前是否预检查（默认为False）
    pool_pre_ping=True,
)

# 创建异步会话工厂
AsyncSessionFactory = sessionmaker(
    # Engine或者其子类对象（这里是AsyncEngine）
    bind=engine,
    # Session类的代替（默认是Session类）
    class_=AsyncSession,
    # 是否在查找之前执行flush操作（默认是True）
    autoflush=True,
    # 是否在执行commit操作后Session就过期（默认是True）
    expire_on_commit=False
)

# 创建 Declarative Base
# 定义命名约定的Base类
class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class BaseModel(Base):
    __abstract__ = True

    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=lambda: uuid())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


from . import user
from . import positions
from . import interview
from . import candidate