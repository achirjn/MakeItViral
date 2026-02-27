import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from db.base import Base


class ReelFeatures(Base):
    __tablename__ = "reel_features"

    reel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reels.id", ondelete="CASCADE"),
        primary_key=True,
    )

    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)

    motion_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    frame_entropy: Mapped[float | None] = mapped_column(Float, nullable=True)
    scene_change_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    object_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    emotion_vector: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_energy: Mapped[float | None] = mapped_column(Float, nullable=True)
    speech_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)

    hook_motion_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    hook_scene_change_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    hook_ocr_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hook_signals: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    hook_recommendations: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    llm_hook_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_hook_signals: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    llm_hook_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_hook_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    model_versions: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReelAudioFeatures(Base):
    __tablename__ = "reel_audio_features"

    reel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reels.id", ondelete="CASCADE"),
        primary_key=True,
    )

    tempo: Mapped[float | None] = mapped_column(Float, nullable=True)
    beat_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    speech_presence: Mapped[float | None] = mapped_column(Float, nullable=True)
    music_presence: Mapped[float | None] = mapped_column(Float, nullable=True)

    model_versions: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReelTextFeatures(Base):
    __tablename__ = "reel_text_features"

    reel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reels.id", ondelete="CASCADE"),
        primary_key=True,
    )

    caption_keywords: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    ocr_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    transcript_keywords: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )

    sentiment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)

    model_versions: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReelProjections(Base):
    __tablename__ = "reel_projections"

    reel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reels.id", ondelete="CASCADE"),
        primary_key=True,
    )

    hook_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pacing_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    projection_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="v1_mvp"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReelEmbeddings(Base):
    __tablename__ = "reel_embeddings"

    reel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reels.id", ondelete="CASCADE"),
        primary_key=True,
    )

    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    text_bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
