import sys
import types
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gateway.config import PlatformConfig


def _ensure_discord_mock():
    if "discord" in sys.modules and hasattr(sys.modules["discord"], "__file__"):
        return
    discord_mod = types.ModuleType("discord")
    discord_mod.Intents = MagicMock()
    discord_mod.Intents.default.return_value = MagicMock()
    discord_mod.DMChannel = type("DMChannel", (), {})
    discord_mod.Thread = type("Thread", (), {})
    discord_mod.ForumChannel = type("ForumChannel", (), {})
    discord_mod.Interaction = object
    discord_mod.ui = SimpleNamespace(
        View=object,
        button=lambda *args, **kwargs: (lambda fn: fn),
        Button=object,
    )
    discord_mod.ButtonStyle = SimpleNamespace(
        success=1, primary=2, secondary=2, danger=3, green=1, grey=2, blurple=2, red=3
    )
    discord_mod.Color = SimpleNamespace(
        orange=lambda: 1, green=lambda: 2, blue=lambda: 3, red=lambda: 4, purple=lambda: 5
    )
    discord_mod.Embed = MagicMock
    discord_mod.app_commands = SimpleNamespace(
        describe=lambda **kwargs: (lambda fn: fn),
        choices=lambda **kwargs: (lambda fn: fn),
        Choice=lambda **kwargs: SimpleNamespace(**kwargs),
    )

    ext_mod = MagicMock()
    commands_mod = MagicMock()
    commands_mod.Bot = MagicMock
    ext_mod.commands = commands_mod

    sys.modules.setdefault("discord", discord_mod)
    sys.modules.setdefault("discord.ext", ext_mod)
    sys.modules.setdefault("discord.ext.commands", commands_mod)


_ensure_discord_mock()

from gateway.platforms.discord import DiscordAdapter  # noqa: E402


class _HistoryChannel:
    def __init__(self, messages):
        self.id = 1503787550
        self.parent_id = None
        self._messages = messages

    def history(self, *, limit, before):
        async def _iter():
            for message in self._messages[:limit]:
                yield message

        return _iter()


def _prior(idx, content, *, bot=False, attachment=None):
    attachments = []
    if attachment:
        attachments.append(SimpleNamespace(filename=attachment))
    return SimpleNamespace(
        id=idx,
        created_at=datetime(2026, 5, 15, 12, 0, 0) + timedelta(seconds=idx),
        author=SimpleNamespace(display_name=f"User {idx}", name=f"user{idx}", bot=bot),
        content=content,
        attachments=attachments,
    )


def _current_message(channel):
    return SimpleNamespace(
        id=99,
        created_at=datetime(2026, 5, 15, 12, 10, 0),
        channel=channel,
    )


@pytest.mark.asyncio
async def test_recent_context_is_injected_for_configured_channel():
    channel = _HistoryChannel([
        _prior(1, "Ramona was here"),
        _prior(2, "Luna answered", bot=True),
    ])
    adapter = DiscordAdapter(
        PlatformConfig(
            enabled=True,
            token="***",
            extra={
                "recent_context_channels": ["discord:channel:1503787550"],
                "recent_context_limit": 3,
                "recent_context_include_bots": True,
            },
        )
    )

    context = await adapter._recent_discord_context_for_message(
        _current_message(channel),
        {"1503787550"},
    )

    assert context is not None
    assert "Recent Discord channel context" in context
    assert "Ramona was here" in context
    assert "Luna answered" in context
    assert "bot/agent" in context


@pytest.mark.asyncio
async def test_recent_context_is_not_injected_for_other_channels():
    channel = _HistoryChannel([_prior(1, "old news")])
    adapter = DiscordAdapter(
        PlatformConfig(
            enabled=True,
            token="***",
            extra={"recent_context_channels": ["123"]},
        )
    )

    context = await adapter._recent_discord_context_for_message(
        _current_message(channel),
        {"1503787550"},
    )

    assert context is None


@pytest.mark.asyncio
async def test_recent_context_can_exclude_bots():
    channel = _HistoryChannel([
        _prior(1, "human line"),
        _prior(2, "bot line", bot=True),
    ])
    adapter = DiscordAdapter(
        PlatformConfig(
            enabled=True,
            token="***",
            extra={
                "recent_context_channels": ["1503787550"],
                "recent_context_include_bots": False,
            },
        )
    )

    context = await adapter._recent_discord_context_for_message(
        _current_message(channel),
        {"1503787550"},
    )

    assert context is not None
    assert "human line" in context
    assert "bot line" not in context


@pytest.mark.asyncio
async def test_recent_context_prefers_newest_messages_within_character_budget():
    channel = _HistoryChannel([
        _prior(1, "old " + "a" * 80),
        _prior(2, "middle " + "b" * 80),
        _prior(3, "newest marker " + "c" * 80),
    ])
    adapter = DiscordAdapter(
        PlatformConfig(
            enabled=True,
            token="***",
            extra={
                "recent_context_channels": ["1503787550"],
                "recent_context_limit": 3,
                "recent_context_max_chars": 180,
            },
        )
    )

    context = await adapter._recent_discord_context_for_message(
        _current_message(channel),
        {"1503787550"},
    )

    assert context is not None
    assert len(context) <= 180
    assert "newest marker" in context
    assert "old " not in context
