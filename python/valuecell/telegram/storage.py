"""Async helpers for Telegram session persistence."""

from __future__ import annotations

import asyncio
from typing import Optional

from sqlalchemy.orm import Session

from valuecell.server.db.connection import get_database_manager
from valuecell.server.db.models.telegram import TelegramSession
from valuecell.server.db.repositories import get_telegram_session_repository


class TelegramSessionStore:
    """Expose async-friendly helpers on top of the repository."""

    def __init__(self) -> None:
        self._db_manager = get_database_manager()

    def _get_session(self) -> Session:
        return self._db_manager.get_session()

    async def upsert_session(
        self,
        *,
        chat_id: int,
        user_id: int,
        conversation_id: str,
        agent_name: str,
    ) -> TelegramSession:
        return await asyncio.to_thread(
            self._upsert_sync,
            chat_id,
            user_id,
            conversation_id,
            agent_name,
        )

    def _upsert_sync(
        self,
        chat_id: int,
        user_id: int,
        conversation_id: str,
        agent_name: str,
    ) -> TelegramSession:
        session = self._get_session()
        try:
            repo = get_telegram_session_repository(db_session=session)
            result = repo.upsert_session(
                chat_id=chat_id,
                user_id=user_id,
                conversation_id=conversation_id,
                agent_name=agent_name,
            )
            repo.deactivate_other_agents(
                chat_id=chat_id,
                user_id=user_id,
                keep_agent=agent_name,
            )
            return result
        finally:
            session.close()

    async def get_session(
        self,
        *,
        chat_id: int,
        user_id: int,
        agent_name: str,
    ) -> Optional[TelegramSession]:
        return await asyncio.to_thread(
            self._get_sync,
            chat_id,
            user_id,
            agent_name,
        )

    def _get_sync(
        self,
        chat_id: int,
        user_id: int,
        agent_name: str,
    ) -> Optional[TelegramSession]:
        session = self._get_session()
        try:
            repo = get_telegram_session_repository(db_session=session)
            return repo.get_session(
                chat_id=chat_id,
                user_id=user_id,
                agent_name=agent_name,
            )
        finally:
            session.close()

    async def get_active_session(
        self,
        *,
        chat_id: int,
        user_id: int,
    ) -> Optional[TelegramSession]:
        return await asyncio.to_thread(
            self._get_active_sync,
            chat_id,
            user_id,
        )

    def _get_active_sync(
        self,
        chat_id: int,
        user_id: int,
    ) -> Optional[TelegramSession]:
        session = self._get_session()
        try:
            repo = get_telegram_session_repository(db_session=session)
            return repo.get_active_session(chat_id=chat_id, user_id=user_id)
        finally:
            session.close()
