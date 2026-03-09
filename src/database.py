"""
Database module — SQLAlchemy models and connection for Run Intel.

Provides models, session management, and a context manager for safe transactions.
"""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Float, Index, Integer, Numeric, String, Text, create_engine
from sqlalchemy.sql import func as sa_func
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


class UserProfile(Base):
    __tablename__ = "user_profile"

    id = Column(Integer, primary_key=True, autoincrement=True)
    age = Column(Integer, CheckConstraint("age >= 10 AND age <= 130"))
    height_inches = Column(Integer, CheckConstraint("height_inches >= 36 AND height_inches <= 108"))
    weight_lbs = Column(Numeric(5, 1), CheckConstraint("weight_lbs >= 50 AND weight_lbs <= 500"))
    max_hr = Column(Integer, CheckConstraint("max_hr >= 100 AND max_hr <= 230"))
    resting_hr_baseline = Column(Numeric(4, 1))
    body_fat_pct = Column(Numeric(4, 1), CheckConstraint("body_fat_pct >= 3 AND body_fat_pct <= 60"))
    goal_marathon_time_min = Column(Numeric(5, 1))
    goal_body_fat_pct = Column(Numeric(4, 1), CheckConstraint("goal_body_fat_pct >= 3 AND goal_body_fat_pct <= 60"))
    goal_weight_lbs = Column(Numeric(5, 1), CheckConstraint("goal_weight_lbs >= 50 AND goal_weight_lbs <= 500"))
    goal_target_date = Column(Date)
    created_at = Column(DateTime, server_default=sa_func.now())
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now())

    def to_dict(self) -> dict:
        return {
            "age": self.age,
            "height_inches": self.height_inches,
            "weight_lbs": float(self.weight_lbs) if self.weight_lbs else None,
            "max_hr": self.max_hr,
            "resting_hr_baseline": float(self.resting_hr_baseline) if self.resting_hr_baseline else None,
            "body_fat_pct": float(self.body_fat_pct) if self.body_fat_pct else None,
            "goal_marathon_time_min": float(self.goal_marathon_time_min) if self.goal_marathon_time_min else None,
            "goal_body_fat_pct": float(self.goal_body_fat_pct) if self.goal_body_fat_pct else None,
            "goal_weight_lbs": float(self.goal_weight_lbs) if self.goal_weight_lbs else None,
            "goal_target_date": self.goal_target_date.isoformat() if self.goal_target_date else None,
        }


class NutritionLog(_SerializableMixin, Base):
    __tablename__ = "nutrition_log"
    __table_args__ = (Index("ix_nutrition_log_date", "date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, server_default=sa_func.current_date())
    calories = Column(Integer, nullable=False)
    protein_grams = Column(Integer, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=sa_func.now())


class BodyComp(_SerializableMixin, Base):
    __tablename__ = "body_comp"
    __table_args__ = (Index("ix_body_comp_date", "date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    weight_lbs = Column(Numeric(5, 1), nullable=False)
    body_fat_pct = Column(Numeric(4, 1))
    notes = Column(Text)
    created_at = Column(DateTime, server_default=sa_func.now())


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
