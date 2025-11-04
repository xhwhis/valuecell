"""Manage mapping between Telegram chats/users and ValueCell conversations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from valuecell.core.conversation import ConversationManager
from valuecell.core.conversation.models import Conversation
from valuecell.server.services.conversation_service import ConversationService


@dataclass(slots=True)
class TelegramChatIdentity:
    """Canonical identity for a Telegram chat interaction."""

    chat_id: int
    user_id: int

    def key(self) -> str:
        return f"{self.chat_id}:{self.user_id}"


class ChatContextManager:
    """High-level helper for resolving conversation identifiers."""

    def __init__(self, conversation_service: ConversationService) -> None:
        self._conversation_service = conversation_service

    @property
    def conversation_manager(self) -> ConversationManager:
        return self._conversation_service.conversation_manager

    async def ensure_conversation(
        self,
        identity: TelegramChatIdentity,
        agent_name: Optional[str] = None,
    ) -> Conversation:
        """Ensure a unique conversation for the given Telegram user + chat."""
        conversation_id = self._build_conversation_id(identity, agent_name)
        (
            conversation,
            _,
        ) = await self._conversation_service.core_conversation_service.ensure_conversation(
            user_id=str(identity.user_id),
            conversation_id=conversation_id,
            agent_name=agent_name,
        )
        return conversation

    async def switch_agent(
        self,
        identity: TelegramChatIdentity,
        new_agent_name: str,
    ) -> Conversation:
        """Create or load a conversation for the specified agent."""
        return await self.ensure_conversation(identity, agent_name=new_agent_name)

    def _build_conversation_id(
        self, identity: TelegramChatIdentity, agent_name: Optional[str]
    ) -> str:
        suffix = agent_name or "default_agent"
        return f"tg-{identity.chat_id}-{identity.user_id}-{suffix}"
