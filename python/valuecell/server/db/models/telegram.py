"""Telegram session tracking model."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)

from .base import Base


class TelegramSession(Base):
    """Persist mapping between Telegram chats and ValueCell conversations."""

    __tablename__ = "telegram_sessions"
    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "user_id",
            "agent_name",
            name="uq_telegram_session_chat_user_agent",
        ),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    conversation_id = Column(String(255), nullable=False)
    agent_name = Column(String(255), nullable=False, default="default_agent")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def as_dict(self) -> dict:
        """Serialize model to dictionary."""
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "agent_name": self.agent_name,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
