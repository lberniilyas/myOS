from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    # Serverless instances come and go, so each request opens its own connection and hosted
    # poolers (Neon, Supabase) do the pooling.
    poolclass=NullPool if settings.serverless else None,
    # Poolers in transaction mode can't keep server-side prepared statements between requests.
    connect_args={"prepare_threshold": None},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_factory() -> Callable[[], AbstractContextManager[Session]]:
    """FastAPI dependency: opens sessions for work that runs after the reply."""
    return SessionLocal
