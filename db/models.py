import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


# Engagement Status Values
# =======================
# engagement_status field values for lifecycle tracking:
# - "missing": No engagement data ever collected
# - "unstable": Engagement data exists but shows high volatility
# - "stable": Engagement data exists and shows consistent patterns
# - "unavailable": Engagement data cannot be fetched (private, deleted, etc.)


class IngestionStatus(str, Enum):
    PENDING = "PENDING"
    READY_FOR_PROCESSING = "READY_FOR_PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IngestionLogStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRY = "retry"


class Creator(Base):
    __tablename__ = "creators"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, default="instagram")
    followers: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    reels: Mapped[list["Reel"]] = relationship("Reel", back_populates="creator")


class Reel(Base):
    __tablename__ = "reels"
    __table_args__ = (
        UniqueConstraint("reel_url", name="uq_reels_reel_url"),
        CheckConstraint(
            "ingestion_status IN ('PENDING', 'READY_FOR_PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_reels_ingestion_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    reel_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    thumbnail_url: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    audio_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comments: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("creators.id", ondelete="CASCADE"),
        nullable=False,
    )
    publish_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    has_engagement_metrics: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_training_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    metadata_completeness_score: Mapped[float] = mapped_column(
        nullable=False, default=0.0
    )
    ingestion_status: Mapped[IngestionStatus] = mapped_column(
        String(32),
        nullable=False,
        default=IngestionStatus.PENDING.value,
    )
    discovery_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    # Engagement lifecycle tracking fields
    engagement_last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    engagement_fetch_attempts: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    engagement_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="missing"
    )
    is_active_for_training: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    stability_score: Mapped[float] = mapped_column(
        nullable=False, default=0.0
    )
    
    # Worker retry tracking
    retries: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    creator: Mapped[Creator] = relationship("Creator", back_populates="reels")
    ingestion_logs: Mapped[list["IngestionLog"]] = relationship(
        "IngestionLog", back_populates="reel", cascade="all, delete-orphan"
    )


class IngestionLog(Base):
    __tablename__ = "ingestion_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'failed', 'skipped', 'retry')",
            name="ck_ingestion_logs_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    reel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reels.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[IngestionLogStatus] = mapped_column(
        String(32), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    reel: Mapped[Reel] = relationship("Reel", back_populates="ingestion_logs")

