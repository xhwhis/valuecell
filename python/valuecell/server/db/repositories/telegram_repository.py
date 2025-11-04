"""Repository utilities for Telegram sessions."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, update
from sqlalchemy.orm import Session

from valuecell.server.db.models.telegram import TelegramSession


class TelegramSessionRepository:
    """CRUD helpers for Telegram session persistence."""

    def __init__(self, db_session: Session):
        self._db = db_session

    def upsert_session(
        self,
        *,
        chat_id: int,
        user_id: int,
        conversation_id: str,
        agent_name: str,
    ) -> TelegramSession:
        """Create or update a session mapping."""
        session = self.get_session(
            chat_id=chat_id, user_id=user_id, agent_name=agent_name
        )
        if session:
            session.conversation_id = conversation_id
            session.is_active = True
        else:
            session = TelegramSession(
                chat_id=chat_id,
                user_id=user_id,
                conversation_id=conversation_id,
                agent_name=agent_name,
            )
            self._db.add(session)
        self._db.commit()
        self._db.refresh(session)
        return session

    def get_session(
        self, *, chat_id: int, user_id: int, agent_name: str
    ) -> Optional[TelegramSession]:
        """Fetch session by unique key."""
        return (
            self._db.query(TelegramSession)
            .filter(
                TelegramSession.chat_id == chat_id,
                TelegramSession.user_id == user_id,
                TelegramSession.agent_name == agent_name,
            )
            .one_or_none()
        )

    def get_active_session(
        self, *, chat_id: int, user_id: int
    ) -> Optional[TelegramSession]:
        """Return the active session for the chat/user, if any."""
        return (
            self._db.query(TelegramSession)
            .filter(
                TelegramSession.chat_id == chat_id,
                TelegramSession.user_id == user_id,
                TelegramSession.is_active.is_(True),
            )
            .order_by(TelegramSession.updated_at.desc())
            .first()
        )

    def deactivate_other_agents(
        self, *, chat_id: int, user_id: int, keep_agent: str
    ) -> None:
        """Mark other agent sessions inactive when switching agent."""
        self._db.execute(
            update(TelegramSession)
            .where(
                and_(
                    TelegramSession.chat_id == chat_id,
                    TelegramSession.user_id == user_id,
                    TelegramSession.agent_name != keep_agent,
                )
            )
            .values(is_active=False)
        )
        self._db.commit()


def get_telegram_session_repository(db_session: Session) -> TelegramSessionRepository:
    """Factory for repository."""
    return TelegramSessionRepository(db_session=db_session)
