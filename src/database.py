"""
Database module — SQLAlchemy models and connection for Run Intel.

Provides models, session management, and a context manager for safe transactions.
"""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Float, Index, Integer, LargeBinary, Numeric, String, Text, create_engine, text
from sqlalchemy.sql import func as sa_func
from sqlalchemy.orm import Session, declarative_base, deferred, sessionmaker

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
    """Auto-serialize all columns (except id and excluded) to a dict."""

    _exclude_from_dict: set = set()

    def to_dict(self) -> dict:
        result = {}
        for c in self.__table__.columns:
            if c.name == "id" or c.name in self._exclude_from_dict:
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
    provider = Column(String(20), server_default="whoop")


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
    goal_calorie_target = Column(Integer, CheckConstraint("goal_calorie_target >= 800 AND goal_calorie_target <= 10000"))
    goal_protein_target_grams = Column(Integer, CheckConstraint("goal_protein_target_grams >= 20 AND goal_protein_target_grams <= 500"))
    sex = Column(String(10), CheckConstraint("sex IN ('male', 'female')"))
    rmr_override = Column(Integer, CheckConstraint("rmr_override >= 800 AND rmr_override <= 5000"))
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
            "goal_calorie_target": self.goal_calorie_target,
            "goal_protein_target_grams": self.goal_protein_target_grams,
            "sex": self.sex,
            "rmr_override": self.rmr_override,
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

    _exclude_from_dict = {"photo"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    weight_lbs = Column(Numeric(5, 1), nullable=False)
    body_fat_pct = Column(Numeric(4, 1))
    notes = Column(Text)
    source = Column(String(20), server_default="manual")
    photo = deferred(Column(LargeBinary))
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


def _run_migrations(eng):
    """Idempotent column additions. create_all() won't add these to existing tables."""
    columns = [
        "ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS goal_calorie_target INTEGER",
        "ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS goal_protein_target_grams INTEGER",
        "ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS sex VARCHAR(10)",
        "ALTER TABLE body_comp ADD COLUMN IF NOT EXISTS photo BYTEA",
        "ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS rmr_override INTEGER",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS provider VARCHAR(20) DEFAULT 'whoop'",
        "ALTER TABLE body_comp ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'manual'",
    ]
    constraints = [
        "ALTER TABLE user_profile ADD CONSTRAINT ck_profile_cal_target CHECK (goal_calorie_target >= 800 AND goal_calorie_target <= 10000)",
        "ALTER TABLE user_profile ADD CONSTRAINT ck_profile_protein_target CHECK (goal_protein_target_grams >= 20 AND goal_protein_target_grams <= 500)",
        "ALTER TABLE user_profile ADD CONSTRAINT ck_profile_sex CHECK (sex IN ('male', 'female'))",
        "ALTER TABLE user_profile ADD CONSTRAINT ck_profile_rmr_override CHECK (rmr_override >= 800 AND rmr_override <= 5000)",
    ]
    data_fixes = [
        # Fix run logged 2026-03-08 local time, stored as 03-09 due to UTC bug
        "UPDATE runs SET date = '2026-03-08' WHERE date = '2026-03-09' AND distance_miles = 12.0 AND time_minutes = 140.0",
        # Fix time (was 140, should be 100) and recalculate pace; clear Whoop fields for re-match
        """UPDATE runs SET time_minutes = 100.0, pace_per_mile = '8:20',
           avg_hr = NULL, max_hr = NULL, strain = NULL,
           whoop_distance_meters = NULL,
           zone_zero_milli = NULL, zone_one_milli = NULL,
           zone_two_milli = NULL, zone_three_milli = NULL,
           zone_four_milli = NULL, zone_five_milli = NULL
           WHERE date = '2026-03-08' AND distance_miles = 12.0 AND time_minutes = 140.0""",
        # Fix nutrition entries logged 2026-03-08 MST but stored as 03-09 (UTC date)
        "UPDATE nutrition_log SET date = '2026-03-08' WHERE date = '2026-03-09' AND created_at < '2026-03-09T07:00:00'",
        # Delete duplicate run on 2026-03-09 (keep the one with the lowest id)
        """DELETE FROM runs WHERE date = '2026-03-09'
           AND id NOT IN (SELECT MIN(id) FROM runs WHERE date = '2026-03-09')""",
    ]
    with eng.begin() as conn:
        for sql in columns:
            conn.execute(text(sql))
        for sql in constraints:
            conn.execute(text(f"DO $$ BEGIN {sql}; EXCEPTION WHEN duplicate_object THEN NULL; END $$;"))
        for sql in data_fixes:
            conn.execute(text(sql))


def init_db():
    """Create all tables + add any columns missing from existing tables."""
    Base.metadata.create_all(engine)
    try:
        _run_migrations(engine)
    except Exception:
        logger.warning("Migration failed (may be expected on fresh DB)", exc_info=True)
