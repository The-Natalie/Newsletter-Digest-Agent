import sqlalchemy as sa
from sqlalchemy import Column, Date, Integer, MetaData, Table, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

engine = create_async_engine(settings.database_url, echo=False)

async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)

metadata = MetaData()

digest_runs = Table(
    "digest_runs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("run_at", sa.DateTime, server_default=sa.func.now()),
    Column("folder", Text, nullable=False),
    Column("date_start", Date, nullable=True),
    Column("date_end", Date, nullable=True),
    Column("story_count", Integer, server_default="0"),
    Column("status", Text, server_default="pending"),
    Column("error_message", Text, nullable=True),
    Column("output_json", Text, nullable=True),
)
