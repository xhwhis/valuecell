"""Telegram bot application entry point."""

from __future__ import annotations

import asyncio
import logging
import re
from functools import partial
from time import monotonic
from typing import List, Optional

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message

from .config import TelegramConfig
from .context import TelegramChatIdentity
from .service import TelegramBotService
from .translator import extract_text

logger = logging.getLogger(__name__)


class TelegramBotApp:
    """Bootstrap and run the Telegram bot."""

    def __init__(self, config: TelegramConfig | None = None) -> None:
        self._config = config or TelegramConfig.from_env()
        default_props = (
            DefaultBotProperties(parse_mode=self._config.parse_mode)
            if self._config.parse_mode
            else None
        )
        if default_props:
            self._bot = Bot(token=self._config.bot_token, default=default_props)
        else:
            self._bot = Bot(token=self._config.bot_token)
        self._dispatcher = Dispatcher()
        self._router = Router()
        self._service = TelegramBotService()
        self._bot_id: int | None = None
        self._register_handlers()
        self._dispatcher.include_router(self._router)

    def _register_handlers(self) -> None:
        @self._router.message(Command("start"))
        async def handle_start(message: Message) -> None:
            await self._safe_reply(
                message,
                "🤖 Welcome to ValueCell Telegram.\n"
                "Use /chat <question> to talk to the Super Agent.\n"
                "Use /agents to list available agents, /agent <name> to switch.\n"
                "Use /history to review recent replies.",
            )

        @self._router.message(Command("chat"))
        async def handle_chat(message: Message, command: CommandObject) -> None:
            prompt = self._extract_prompt(message, command)
            if not prompt:
                await self._safe_reply(
                    message,
                    "💬 Usage: `/chat <your question>` or reply to a message with /chat.",
                )
                return

            identity = self._identity_from_message(message)
            await self._bot.send_chat_action(message.chat.id, "typing")
            await self._stream_query(message, identity, prompt)

        @self._router.message(Command("agents"))
        async def handle_agents(message: Message) -> None:
            await self._send_agent_list(message, show_all=False)

        @self._router.message(Command("agent"))
        async def handle_agent(message: Message, command: CommandObject) -> None:
            arg = (command.args or "").strip()
            if not arg:
                await self._send_agent_list(message, show_all=True)
                return

            identity = self._identity_from_message(message)
            await self._switch_agent(message, identity, arg)

        @self._router.message(Command("history"))
        async def handle_history(message: Message, command: CommandObject) -> None:
            limit = self._parse_history_limit(command.args)
            identity = self._identity_from_message(message)
            await self._send_history(message, identity, limit)

        @self._router.message()
        async def handle_followup(message: Message) -> None:
            if not message.reply_to_message:
                return
            if message.text and message.text.strip().startswith("/"):
                return

            replied_user = message.reply_to_message.from_user
            if not replied_user:
                return

            bot_id = await self._ensure_bot_id()
            if replied_user.id != bot_id:
                return

            prompt = (message.text or message.caption or "").strip()
            if not prompt:
                return

            identity = self._identity_from_message(message)
            await self._bot.send_chat_action(message.chat.id, "typing")
            await self._stream_query(message, identity, prompt)

    async def run_polling(self) -> None:
        """Run the bot in long-polling mode."""
        logger.info("Starting Telegram bot polling...")
        await self._dispatcher.start_polling(
            self._bot,
            allowed_updates=self._dispatcher.resolve_used_update_types(),
            polling_timeout=self._config.request_timeout,
        )

    async def run_webhook(self) -> None:
        """Run the bot in webhook mode."""
        raise NotImplementedError("Webhook mode is not implemented yet.")

    async def _stream_query(
        self,
        message: Message,
        identity: TelegramChatIdentity,
        prompt: str,
        agent_name: Optional[str] = None,
    ) -> None:
        chat_id = message.chat.id

        placeholder = await self._answer_with_fallback(
            message,
            "⌛ 正在处理您的请求…",
            reply_to=message.message_id,
        )

        edit_callable = partial(
            self._bot.edit_message_text,
            chat_id=chat_id,
            message_id=placeholder.message_id,
        )

        buffer_text = ""
        tool_messages: list[str] = []
        last_edit = monotonic()
        throttle_seconds = 0.6
        last_sent_payload = ""

        try:
            async for response in self._service.stream_chat_completion(
                identity, prompt, agent_name=agent_name
            ):
                text = extract_text(response)
                if not text:
                    continue
                if self._is_tool_message(text):
                    tool_messages.append(text.strip())
                    tool_display = "\n".join(tool_messages)
                    await self._safe_send(edit_callable, tool_display)
                    last_sent_payload = tool_display
                    continue
                if tool_messages:
                    tool_messages.clear()
                    last_sent_payload = ""
                    buffer_text = ""
                    last_edit = 0
                normalized = self._normalize_chunk(text)
                if not normalized:
                    continue
                buffer_text = self._append_chunk(buffer_text, normalized)

                now = monotonic()
                if now - last_edit >= throttle_seconds or last_sent_payload == "":
                    if buffer_text != last_sent_payload:
                        await self._safe_send(edit_callable, buffer_text)
                        last_sent_payload = buffer_text
                    last_edit = now

            final_text = buffer_text.strip()
            if final_text:
                if final_text != last_sent_payload:
                    await self._safe_send(edit_callable, final_text)
            elif not tool_messages:
                fallback = "⚠️ 尚未收到任何内容，请稍后重试。"
                if fallback != last_sent_payload:
                    await self._safe_send(edit_callable, fallback)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Error while streaming response: %s", exc)
            await self._safe_send(
                edit_callable,
                f"❌ 处理请求时出错：{exc}",
            )

    async def _send_agent_list(self, message: Message, show_all: bool) -> None:
        data = await self._service.list_agents(enabled_only=not show_all)
        if not data.agents:
            await self._safe_reply(message, "ℹ️ No agents found.")
            return

        lines = []
        for agent in data.agents:
            status = "✅" if agent.enabled else "⛔"
            display = agent.display_name or agent.agent_name
            snippet = agent.description or ""
            snippet = snippet[:80] + "…" if len(snippet) > 80 else snippet
            lines.append(f"{status} `{agent.agent_name}` — {display}\n{snippet}")

        await self._safe_reply(
            message,
            "📋 Available agents:\n\n" + "\n\n".join(lines),
        )

    async def _switch_agent(
        self,
        message: Message,
        identity: TelegramChatIdentity,
        agent_name: str,
    ) -> None:
        data = await self._service.list_agents(enabled_only=False)
        target = next(
            (agent for agent in data.agents if agent.agent_name == agent_name), None
        )
        if not target:
            await self._safe_reply(
                message,
                f"❌ Agent `{agent_name}` not found. Use /agents to list options.",
            )
            return
        if not target.enabled:
            await self._safe_reply(
                message,
                f"⚠️ Agent `{agent_name}` is currently disabled.",
            )
            return

        await self._service.switch_agent(identity, agent_name=agent_name)
        await self._safe_reply(
            message,
            f"🔁 Switched to `{agent_name}`.",
        )

    async def _send_history(
        self,
        message: Message,
        identity: TelegramChatIdentity,
        limit: int,
    ) -> None:
        history_items = await self._service.get_active_history(identity, limit=limit)
        if not history_items:
            await self._safe_reply(message, "ℹ️ No conversation history yet.")
            return

        lines: List[str] = []
        for item in history_items:
            role = item.data.role or "unknown"
            payload = item.data.payload or {}
            content = payload.get("content") if isinstance(payload, dict) else ""
            if not content and isinstance(payload, dict):
                content = payload.get("result", "")
            if not content:
                content = str(payload) if payload else ""
            content = content.strip()
            if not content:
                continue
            lines.append(f"*{role.upper()}*: {content}")

        if not lines:
            await self._safe_reply(message, "ℹ️ No readable messages in history.")
            return

        await self._safe_reply(
            message,
            "🗂 Recent conversation history:\n\n" + "\n".join(lines),
        )

    def _extract_prompt(self, message: Message, command: CommandObject) -> str:
        if command.args:
            return command.args.strip()
        if message.reply_to_message and message.reply_to_message.text:
            return message.reply_to_message.text.strip()
        return ""

    def _parse_history_limit(self, arg: Optional[str]) -> int:
        if not arg:
            return 5
        try:
            value = int(arg.strip())
            return max(1, min(value, 20))
        except ValueError:
            return 5

    def _identity_from_message(self, message: Message) -> TelegramChatIdentity:
        user_id = message.from_user.id if message.from_user else 0
        return TelegramChatIdentity(chat_id=message.chat.id, user_id=user_id)

    async def _ensure_bot_id(self) -> int:
        if self._bot_id is None:
            me = await self._bot.get_me()
            self._bot_id = me.id
        return self._bot_id

    async def _safe_reply(self, message: Message, text: str) -> None:
        await self._answer_with_fallback(message, text, reply_to=message.message_id)

    async def _answer_with_fallback(
        self, message: Message, text: str, reply_to: int | None = None
    ) -> Message:
        parse_mode = self._config.parse_mode
        send_kwargs = {}
        if reply_to is not None:
            send_kwargs = {
                "reply_to_message_id": reply_to,
                "allow_sending_without_reply": True,
            }
        if parse_mode:
            try:
                return await message.answer(text, parse_mode=parse_mode, **send_kwargs)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug("Failed to send with parse mode %s: %s", parse_mode, exc)
        return await message.answer(text, **send_kwargs)

    async def _safe_send(self, send_callable, text: str) -> None:
        if not text:
            return
        max_len = 3900
        payload = text
        if len(payload) > max_len:
            payload = "…" + payload[-(max_len - 1) :]
        parse_mode = self._config.parse_mode
        if parse_mode:
            try:
                await send_callable(payload, parse_mode=parse_mode)
                return
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug("Failed to send with parse mode %s: %s", parse_mode, exc)
        await send_callable(payload, parse_mode=None)

    def _normalize_chunk(self, text: str) -> str:
        if not text:
            return ""

        filtered_lines: list[str] = []
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("🛠 Tool"):
                continue
            filtered_lines.append(raw_line.rstrip())

        if not filtered_lines:
            return ""

        cleaned = "\n".join(filtered_lines).strip()
        if not cleaned:
            return ""

        # Collapse excessive internal whitespace but preserve intentional newlines
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        return cleaned

    def _append_chunk(self, current: str, chunk: str) -> str:
        if not current:
            return chunk

        existing_paragraphs = current.split("\n\n")
        new_paragraphs = chunk.split("\n\n")

        if len(existing_paragraphs) > 1 or len(new_paragraphs) > 1:
            merged = existing_paragraphs[:-1]
            last_existing = existing_paragraphs[-1]
            first_new = new_paragraphs[0]
            combined_last = self._merge_inline(last_existing, first_new)
            merged.append(combined_last)
            merged.extend(new_paragraphs[1:])
            return "\n\n".join(p.strip() for p in merged if p.strip())

        return self._merge_inline(current, chunk)

    @staticmethod
    def _merge_inline(left: str, right: str) -> str:
        left = left.rstrip()
        right = right.lstrip()
        if not left:
            return right
        if not right:
            return left
        if left.endswith((".", "?", "!", ":")):
            return f"{left}\n{right}"
        return f"{left} {right}"

    @staticmethod
    def _is_tool_message(text: str) -> bool:
        return text.strip().startswith("🛠 Tool")


def main() -> None:
    """CLI entry point for triggering the Telegram bot."""
    logging.basicConfig(level=logging.INFO)
    app = TelegramBotApp()
    asyncio.run(app.run_polling())


if __name__ == "__main__":
    main()
