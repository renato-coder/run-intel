"""
Database module — SQLAlchemy models and connection for Run Intel.

Provides models, session management, and a context manager for safe transactions.
"""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import Column, Date, Float, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import DATABASE_URL

logger = logging.getLogger(__name__)

engine = create_engine(
    DATABASE_URL,
    pool_size=3,
    max_overflow=5,
    pool_recycle=300,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()


class _SerializableMixin:
    """Auto-serialize all columns (except id) to a dict."""

    def to_dict(self) -> dict:
        result = {}
        for c in self.__table__.columns:
            if c.name == "id":
                continue
            val = getattr(self, c.name)
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            result[c.name] = val
        return result


class Run(_SerializableMixin, Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_date", "date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    distance_miles = Column(Float)
    time_minutes = Column(Float)
    pace_per_mile = Column(String(10))
    avg_hr = Column(Integer)
    max_hr = Column(Integer)
    strain = Column(Float)
    whoop_distance_meters = Column(Float)
    zone_zero_milli = Column(Integer)
    zone_one_milli = Column(Integer)
    zone_two_milli = Column(Integer)
    zone_three_milli = Column(Integer)
    zone_four_milli = Column(Integer)
    zone_five_milli = Column(Integer)
    shoes = Column(Text)


class Recovery(_SerializableMixin, Base):
    __tablename__ = "recovery"
    __table_args__ = (Index("ix_recovery_date", "date", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, unique=True)
    recovery_score = Column(Float)
    hrv = Column(Float)
    resting_hr = Column(Float)


class Token(Base):
    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    expiry = Column(Float, nullable=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional session with automatic commit/rollback."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)
