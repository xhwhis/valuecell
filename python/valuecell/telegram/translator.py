"""Utilities to translate ValueCell responses into Telegram-friendly text."""

from __future__ import annotations

from typing import Optional

from valuecell.core.agent.responses import EventPredicates
from valuecell.core.types import (
    BaseResponse,
    CommonResponseEvent,
    StreamResponseEvent,
    SystemResponseEvent,
)


def extract_text(response: BaseResponse) -> Optional[str]:
    """Return a textual representation of a core response for Telegram."""
    event = response.event
    data = response.data

    if EventPredicates.is_message(event):
        payload = getattr(data, "payload", None)
        if payload and getattr(payload, "content", None):
            return payload.content
        if hasattr(data, "content") and data.content:
            return data.content
        return None

    if EventPredicates.is_reasoning(event):
        payload = getattr(data, "payload", None)
        content = None
        if payload and getattr(payload, "content", None):
            content = payload.content
        elif hasattr(data, "content"):
            content = data.content
        if content:
            return f"💡 Reasoning: {content}"
        return None

    if event == SystemResponseEvent.PLAN_REQUIRE_USER_INPUT:
        payload = getattr(data, "payload", None)
        prompt = None
        if payload and getattr(payload, "content", None):
            prompt = payload.content
        elif hasattr(data, "content"):
            prompt = data.content
        if prompt:
            return f"📝 The agent needs more info:\n{prompt}"
        return "📝 The agent needs more information."

    if event == SystemResponseEvent.PLAN_FAILED:
        payload = getattr(data, "payload", None)
        detail = None
        if payload and getattr(payload, "content", None):
            detail = payload.content
        elif hasattr(data, "content"):
            detail = data.content
        if detail:
            return f"⚠️ Plan failed:\n{detail}"
        return "⚠️ Plan failed."

    if event == SystemResponseEvent.DONE:
        return "✅ Done."

    if EventPredicates.is_tool_call(event):
        payload = getattr(data, "payload", None)
        tool_name = None
        if payload and getattr(payload, "tool_name", None):
            tool_name = payload.tool_name
        status = (
            "started" if event == StreamResponseEvent.TOOL_CALL_STARTED else "completed"
        )
        if tool_name:
            return f"🛠 Tool {tool_name} {status}."
        return f"🛠 Tool call {status}."

    if event == CommonResponseEvent.COMPONENT_GENERATOR:
        payload = getattr(data, "payload", None)
        component_type = None
        if payload and getattr(payload, "component_type", None):
            component_type = payload.component_type
        if payload and getattr(payload, "content", None):
            return f"📦 Component ({component_type or 'unknown'}):\n{payload.content}"
        return f"📦 Component generated ({component_type or 'unknown'})."

    return None
