"""
Database module — SQLAlchemy models and connection for Run Intel.

Connects via DATABASE_URL environment variable.
"""

import os

from sqlalchemy import (
    Column, Date, Float, Integer, String, Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Railway (and Heroku) may provide postgres:// but SQLAlchemy 2.x needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()


class Run(Base):
    __tablename__ = "runs"

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

    def to_dict(self):
        return {
            "date": self.date.isoformat() if self.date else None,
            "distance_miles": self.distance_miles,
            "time_minutes": self.time_minutes,
            "pace_per_mile": self.pace_per_mile,
            "avg_hr": self.avg_hr,
            "max_hr": self.max_hr,
            "strain": self.strain,
            "whoop_distance_meters": self.whoop_distance_meters,
            "zone_zero_milli": self.zone_zero_milli,
            "zone_one_milli": self.zone_one_milli,
            "zone_two_milli": self.zone_two_milli,
            "zone_three_milli": self.zone_three_milli,
            "zone_four_milli": self.zone_four_milli,
            "zone_five_milli": self.zone_five_milli,
            "shoes": self.shoes,
        }


class Recovery(Base):
    __tablename__ = "recovery"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    recovery_score = Column(Float)
    hrv = Column(Float)
    resting_hr = Column(Float)

    def to_dict(self):
        return {
            "date": self.date.isoformat() if self.date else None,
            "recovery_score": self.recovery_score,
            "hrv": self.hrv,
            "resting_hr": self.resting_hr,
        }


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)
