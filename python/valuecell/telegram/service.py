"""Orchestrate Telegram interactions with ValueCell core services."""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Optional

from valuecell.core.coordinate.orchestrator import AgentOrchestrator
from valuecell.core.types import BaseResponse, UserInput, UserInputMetadata
from valuecell.server.services.conversation_service import ConversationService

from .context import ChatContextManager, TelegramChatIdentity
from .storage import TelegramSessionStore


class TelegramBotService:
    """Bridges Telegram command handling with ValueCell orchestration."""

    def __init__(
        self,
        conversation_service: ConversationService | None = None,
        orchestrator: AgentOrchestrator | None = None,
    ) -> None:
        self._conversation_service = conversation_service or ConversationService()
        self._context_manager = ChatContextManager(self._conversation_service)
        self._session_store = TelegramSessionStore()
        if orchestrator is None:
            # Lazy import to avoid circular dependency during tests.
            from valuecell.server.services.agent_stream_service import (
                AgentStreamService,
            )

            self._stream_service = AgentStreamService()
            self._orchestrator = self._stream_service.orchestrator
        else:
            self._stream_service = None
            self._orchestrator = orchestrator

    @property
    def conversation_service(self) -> ConversationService:
        return self._conversation_service

    async def stream_chat_completion(
        self,
        identity: TelegramChatIdentity,
        message: str,
        agent_name: Optional[str] = None,
    ) -> AsyncGenerator[BaseResponse, None]:
        """Convert a Telegram chat message into ValueCell responses."""
        active_session = None
        if agent_name is None:
            active_session = await self._session_store.get_active_session(
                chat_id=identity.chat_id,
                user_id=identity.user_id,
            )
            if active_session:
                agent_name = active_session.agent_name

        conversation = await self._context_manager.ensure_conversation(
            identity, agent_name=agent_name
        )

        if agent_name is None:
            agent_name = conversation.agent_name

        await self._session_store.upsert_session(
            chat_id=identity.chat_id,
            user_id=identity.user_id,
            conversation_id=conversation.conversation_id,
            agent_name=agent_name or conversation.agent_name or "default_agent",
        )

        metadata = UserInputMetadata(
            user_id=str(identity.user_id),
            conversation_id=conversation.conversation_id,
        )
        user_input = UserInput(
            query=message,
            target_agent_name=agent_name,
            meta=metadata,
        )

        async for response in self._orchestrator.process_user_input(user_input):
            yield response

    async def run_stream_to_queue(
        self,
        identity: TelegramChatIdentity,
        message: str,
        queue: "asyncio.Queue[BaseResponse]",
        agent_name: Optional[str] = None,
    ) -> None:
        """Helper to push streamed responses into an asyncio queue."""
        async for resp in self.stream_chat_completion(identity, message, agent_name):
            await queue.put(resp)

    async def switch_agent(
        self, identity: TelegramChatIdentity, agent_name: str
    ) -> str:
        """Switch default agent for the Telegram user."""
        conversation = await self._context_manager.switch_agent(
            identity, new_agent_name=agent_name
        )
        await self._session_store.upsert_session(
            chat_id=identity.chat_id,
            user_id=identity.user_id,
            conversation_id=conversation.conversation_id,
            agent_name=agent_name,
        )
        return conversation.conversation_id

    async def list_agents(self, enabled_only: bool = True):
        """List available agents (optionally filtered to enabled ones)."""
        from valuecell.server.db.connection import get_database_manager
        from valuecell.server.services.agent_service import AgentService

        db_manager = get_database_manager()

        def _fetch():
            session = db_manager.get_session()
            try:
                return AgentService.get_all_agents(
                    db=session, enabled_only=enabled_only
                )
            finally:
                session.close()

        return await asyncio.to_thread(_fetch)

    async def get_active_history(self, identity: TelegramChatIdentity, limit: int = 10):
        """Fetch recent history for the active conversation."""
        active_session = await self._session_store.get_active_session(
            chat_id=identity.chat_id,
            user_id=identity.user_id,
        )
        if not active_session:
            return []

        history = await self._conversation_service.get_conversation_history(
            conversation_id=active_session.conversation_id
        )
        if not history.items:
            return []

        return history.items[-limit:]
