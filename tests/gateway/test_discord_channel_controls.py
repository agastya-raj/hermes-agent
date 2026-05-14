"""Tests for Discord ignored_channels and no_thread_channels config."""

from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import sys

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import ProcessingOutcome


def _ensure_discord_mock():
    """Install a mock discord module when discord.py isn't available."""
    if "discord" in sys.modules and hasattr(sys.modules["discord"], "__file__"):
        return

    discord_mod = MagicMock()
    discord_mod.Intents.default.return_value = MagicMock()
    discord_mod.Client = MagicMock
    discord_mod.File = MagicMock
    discord_mod.DMChannel = type("DMChannel", (), {})
    discord_mod.Thread = type("Thread", (), {})
    discord_mod.ForumChannel = type("ForumChannel", (), {})
    discord_mod.ui = SimpleNamespace(View=object, button=lambda *a, **k: (lambda fn: fn), Button=object)
    discord_mod.ButtonStyle = SimpleNamespace(success=1, primary=2, secondary=2, danger=3, green=1, grey=2, blurple=2, red=3)
    discord_mod.Color = SimpleNamespace(orange=lambda: 1, green=lambda: 2, blue=lambda: 3, red=lambda: 4, purple=lambda: 5)
    discord_mod.Interaction = object
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

import gateway.platforms.discord as discord_platform  # noqa: E402
from gateway.platforms.discord import DiscordAdapter  # noqa: E402


class FakeDMChannel:
    def __init__(self, channel_id: int = 1, name: str = "dm"):
        self.id = channel_id
        self.name = name


class FakeTextChannel:
    def __init__(self, channel_id: int = 1, name: str = "general", guild_name: str = "Hermes Server"):
        self.id = channel_id
        self.name = name
        self.guild = SimpleNamespace(name=guild_name)
        self.topic = None


class FakeThread:
    def __init__(self, channel_id: int = 1, name: str = "thread", parent=None, guild_name: str = "Hermes Server"):
        self.id = channel_id
        self.name = name
        self.parent = parent
        self.parent_id = getattr(parent, "id", None)
        self.guild = getattr(parent, "guild", None) or SimpleNamespace(name=guild_name)
        self.topic = None


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.delenv("BUZZER_QUEUE_ENABLED", raising=False)
    monkeypatch.setattr(discord_platform.discord, "DMChannel", FakeDMChannel, raising=False)
    monkeypatch.setattr(discord_platform.discord, "Thread", FakeThread, raising=False)

    config = PlatformConfig(enabled=True, token="fake-token")
    adapter = DiscordAdapter(config)
    adapter._client = SimpleNamespace(user=SimpleNamespace(id=999))
    adapter._text_batch_delay_seconds = 0  # disable batching for tests
    adapter.handle_message = AsyncMock()
    return adapter


def make_message(*, channel, content: str, mentions=None):
    author = SimpleNamespace(id=42, display_name="TestUser", name="TestUser")
    return SimpleNamespace(
        id=123,
        content=content,
        mentions=list(mentions or []),
        attachments=[],
        reference=None,
        created_at=datetime.now(timezone.utc),
        channel=channel,
        author=author,
    )


# ── ignored_channels ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ignored_channel_blocks_message(adapter, monkeypatch):
    """Messages in ignored channels are silently dropped."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("DISCORD_IGNORED_CHANNELS", "500")
    monkeypatch.delenv("DISCORD_FREE_RESPONSE_CHANNELS", raising=False)

    message = make_message(channel=FakeTextChannel(channel_id=500), content="hello")
    await adapter._handle_message(message)

    adapter.handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignored_channel_blocks_even_with_mention(adapter, monkeypatch):
    """Ignored channels take priority — even @mentions are dropped."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "true")
    monkeypatch.setenv("DISCORD_IGNORED_CHANNELS", "500")

    bot_user = adapter._client.user
    message = make_message(
        channel=FakeTextChannel(channel_id=500),
        content=f"<@{bot_user.id}> hello",
        mentions=[bot_user],
    )
    await adapter._handle_message(message)

    adapter.handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_ignored_channel_processes_normally(adapter, monkeypatch):
    """Channels not in the ignored list process normally."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("DISCORD_IGNORED_CHANNELS", "500,600")
    monkeypatch.delenv("DISCORD_FREE_RESPONSE_CHANNELS", raising=False)

    message = make_message(channel=FakeTextChannel(channel_id=700), content="hello")
    await adapter._handle_message(message)

    adapter.handle_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_ignored_channels_csv_parsing(adapter, monkeypatch):
    """Multiple channel IDs are parsed correctly from CSV."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("DISCORD_IGNORED_CHANNELS", "500, 600 , 700")
    monkeypatch.delenv("DISCORD_FREE_RESPONSE_CHANNELS", raising=False)

    for ch_id in (500, 600, 700):
        adapter.handle_message.reset_mock()
        message = make_message(channel=FakeTextChannel(channel_id=ch_id), content="hello")
        await adapter._handle_message(message)
        adapter.handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignored_channels_empty_string_ignores_nothing(adapter, monkeypatch):
    """Empty DISCORD_IGNORED_CHANNELS means nothing is ignored."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("DISCORD_IGNORED_CHANNELS", "")
    monkeypatch.delenv("DISCORD_FREE_RESPONSE_CHANNELS", raising=False)

    message = make_message(channel=FakeTextChannel(channel_id=500), content="hello")
    await adapter._handle_message(message)

    adapter.handle_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_ignored_channel_thread_parent_match(adapter, monkeypatch):
    """Thread whose parent channel is ignored should also be ignored."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("DISCORD_IGNORED_CHANNELS", "500")
    monkeypatch.delenv("DISCORD_FREE_RESPONSE_CHANNELS", raising=False)

    parent = FakeTextChannel(channel_id=500, name="ignored-channel")
    thread = FakeThread(channel_id=501, name="thread-in-ignored", parent=parent)
    message = make_message(channel=thread, content="hello from thread")
    await adapter._handle_message(message)

    adapter.handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_dms_unaffected_by_ignored_channels(adapter, monkeypatch):
    """DMs should never be affected by ignored_channels."""
    monkeypatch.setenv("DISCORD_IGNORED_CHANNELS", "500")
    monkeypatch.delenv("DISCORD_FREE_RESPONSE_CHANNELS", raising=False)

    message = make_message(channel=FakeDMChannel(channel_id=500), content="dm hello")
    await adapter._handle_message(message)

    adapter.handle_message.assert_awaited_once()


# ── no_thread_channels ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_thread_channel_skips_auto_thread(adapter, monkeypatch):
    """Channels in no_thread_channels should not auto-create threads."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("DISCORD_NO_THREAD_CHANNELS", "800")
    monkeypatch.delenv("DISCORD_AUTO_THREAD", raising=False)
    monkeypatch.delenv("DISCORD_IGNORED_CHANNELS", raising=False)
    monkeypatch.delenv("DISCORD_FREE_RESPONSE_CHANNELS", raising=False)

    adapter._auto_create_thread = AsyncMock(return_value=FakeThread(channel_id=999))

    message = make_message(channel=FakeTextChannel(channel_id=800), content="hello")
    await adapter._handle_message(message)

    adapter._auto_create_thread.assert_not_awaited()
    adapter.handle_message.assert_awaited_once()
    event = adapter.handle_message.await_args.args[0]
    assert event.source.chat_type == "group"


@pytest.mark.asyncio
async def test_normal_channel_still_auto_threads(adapter, monkeypatch):
    """Channels NOT in no_thread_channels still get auto-threading."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("DISCORD_NO_THREAD_CHANNELS", "800")
    monkeypatch.delenv("DISCORD_AUTO_THREAD", raising=False)
    monkeypatch.delenv("DISCORD_IGNORED_CHANNELS", raising=False)
    monkeypatch.delenv("DISCORD_FREE_RESPONSE_CHANNELS", raising=False)

    fake_thread = FakeThread(channel_id=999, name="auto-thread")
    adapter._auto_create_thread = AsyncMock(return_value=fake_thread)

    message = make_message(channel=FakeTextChannel(channel_id=900), content="hello")
    await adapter._handle_message(message)

    adapter._auto_create_thread.assert_awaited_once()
    adapter.handle_message.assert_awaited_once()
    event = adapter.handle_message.await_args.args[0]
    assert event.source.chat_type == "thread"


@pytest.mark.asyncio
async def test_no_thread_channels_csv_parsing(adapter, monkeypatch):
    """Multiple no_thread channel IDs parsed from CSV."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("DISCORD_NO_THREAD_CHANNELS", "800, 900")
    monkeypatch.delenv("DISCORD_AUTO_THREAD", raising=False)
    monkeypatch.delenv("DISCORD_IGNORED_CHANNELS", raising=False)
    monkeypatch.delenv("DISCORD_FREE_RESPONSE_CHANNELS", raising=False)

    adapter._auto_create_thread = AsyncMock(return_value=FakeThread(channel_id=999))

    for ch_id in (800, 900):
        adapter._auto_create_thread.reset_mock()
        adapter.handle_message.reset_mock()
        message = make_message(channel=FakeTextChannel(channel_id=ch_id), content="hello")
        await adapter._handle_message(message)
        adapter._auto_create_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_thread_with_auto_thread_disabled_is_noop(adapter, monkeypatch):
    """no_thread_channels is a no-op when auto_thread is globally disabled."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("DISCORD_AUTO_THREAD", "false")
    monkeypatch.setenv("DISCORD_NO_THREAD_CHANNELS", "800")
    monkeypatch.delenv("DISCORD_IGNORED_CHANNELS", raising=False)
    monkeypatch.delenv("DISCORD_FREE_RESPONSE_CHANNELS", raising=False)

    adapter._auto_create_thread = AsyncMock()

    message = make_message(channel=FakeTextChannel(channel_id=800), content="hello")
    await adapter._handle_message(message)

    adapter._auto_create_thread.assert_not_awaited()
    adapter.handle_message.assert_awaited_once()


# ── config.py bridging ───────────────────────────────────────────────


def test_config_bridges_ignored_channels(monkeypatch, tmp_path):
    """gateway/config.py bridges discord.ignored_channels to env var."""
    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "discord": {
            "ignored_channels": ["111", "222"],
        },
    }))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # Use setenv (not delenv) so monkeypatch registers cleanup even when
    # the var doesn't exist yet — load_gateway_config will overwrite it.
    monkeypatch.setenv("DISCORD_IGNORED_CHANNELS", "")

    from gateway.config import load_gateway_config
    load_gateway_config()

    import os
    assert os.getenv("DISCORD_IGNORED_CHANNELS") == "111,222"


def test_config_bridges_no_thread_channels(monkeypatch, tmp_path):
    """gateway/config.py bridges Discord channel-control settings to env vars."""
    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "discord": {
            "no_thread_channels": ["333"],
            "buzzer_channels": ["444"],
            "buzzer_url": "https://buzzer.example.test",
        },
    }))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("DISCORD_NO_THREAD_CHANNELS", "")
    monkeypatch.delenv("DISCORD_BUZZER_CHANNELS", raising=False)
    monkeypatch.delenv("BUZZER_URL", raising=False)

    from gateway.config import load_gateway_config
    load_gateway_config()

    import os
    assert os.getenv("DISCORD_NO_THREAD_CHANNELS") == "333"
    assert os.getenv("DISCORD_BUZZER_CHANNELS") == "444"
    assert os.getenv("BUZZER_URL") == "https://buzzer.example.test"


def test_config_env_var_takes_precedence(monkeypatch, tmp_path):
    """Env vars should take precedence over config.yaml values."""
    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "discord": {
            "ignored_channels": ["111"],
        },
    }))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("DISCORD_IGNORED_CHANNELS", "999")

    from gateway.config import load_gateway_config
    load_gateway_config()

    import os
    # Env var should NOT be overwritten
    assert os.getenv("DISCORD_IGNORED_CHANNELS") == "999"


@pytest.mark.asyncio
async def test_buzzer_claim_allows_shared_room_message(adapter, monkeypatch):
    """Configured Buzzer channels claim before processing and finish after completion."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("BUZZER_TOKEN_LUNA", "test-token")
    adapter.config.extra["buzzer_channels"] = ["500"]
    calls = []

    def fake_buzzer(endpoint, payload):
        calls.append((endpoint, payload))
        if endpoint == "claim":
            return True, {"allowed": True}, None
        return True, {"ok": True}, None

    monkeypatch.setattr(adapter, "_post_buzzer_sync", fake_buzzer)

    message = make_message(channel=FakeTextChannel(channel_id=500), content="hello")
    await adapter._handle_message(message)

    adapter.handle_message.assert_awaited_once()
    assert calls[0][0] == "observe"
    assert calls[1][0] == "claim"
    assert calls[1][1]["channel_id"] == "500"
    assert calls[1][1]["roomId"].endswith(":500")
    assert calls[1][1]["messageId"] == str(message.id)
    assert calls[1][1]["slot"] == "first"
    assert calls[1][1]["intent"] == "ambient"
    assert calls[1][1]["purpose"] == "other"
    assert calls[1][1]["enthusiasm"] == 2
    assert adapter._buzzer_claimed_messages[str(message.id)]["slot"] == "first"

    await adapter.on_processing_complete(
        SimpleNamespace(raw_message=message),
        ProcessingOutcome.SUCCESS,
    )
    assert calls[-1][0] == "fail"
    assert calls[-1][1]["slot"] == "first"
    assert calls[-1][1]["reason"] == "no_send"
    assert str(message.id) not in adapter._buzzer_claimed_messages


@pytest.mark.asyncio
async def test_buzzer_denial_silences_non_direct_message(adapter, monkeypatch):
    """A denied Buzzer claim stays quiet for ambient room chatter."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("BUZZER_TOKEN_LUNA", "test-token")
    adapter.config.extra["buzzer_channels"] = ["500"]
    calls = []

    def fake_buzzer(endpoint, payload):
        calls.append((endpoint, payload))
        return True, {"allowed": False}, None

    monkeypatch.setattr(adapter, "_post_buzzer_sync", fake_buzzer)

    message = make_message(channel=FakeTextChannel(channel_id=500), content="ambient chat")
    await adapter._handle_message(message)

    adapter.handle_message.assert_not_awaited()
    assert [endpoint for endpoint, _ in calls] == ["observe", "claim", "quiet"]


@pytest.mark.asyncio
async def test_buzzer_direct_address_skips_claim(adapter, monkeypatch):
    """Direct-addressed messages skip Buzzer claims entirely."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("BUZZER_TOKEN_LUNA", "test-token")
    adapter.config.extra["buzzer_channels"] = ["500"]
    calls = []

    def fake_buzzer(endpoint, payload):
        calls.append((endpoint, payload))
        return True, {"allowed": False}, None

    monkeypatch.setattr(adapter, "_post_buzzer_sync", fake_buzzer)

    message = make_message(channel=FakeTextChannel(channel_id=500), content="luna please answer")
    await adapter._handle_message(message)

    adapter.handle_message.assert_awaited_once()
    assert [endpoint for endpoint, _ in calls] == ["observe"]


@pytest.mark.asyncio
async def test_buzzer_mention_skips_claim(adapter, monkeypatch):
    """Explicit bot mentions skip Buzzer claims just like name-addressing."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("BUZZER_TOKEN_LUNA", "test-token")
    adapter.config.extra["buzzer_channels"] = ["500"]
    calls = []

    def fake_buzzer(endpoint, payload):
        calls.append((endpoint, payload))
        return True, {"allowed": False}, None

    monkeypatch.setattr(adapter, "_post_buzzer_sync", fake_buzzer)

    bot_user = adapter._client.user
    message = make_message(
        channel=FakeTextChannel(channel_id=500),
        content=f"<@{bot_user.id}> please answer",
        mentions=[bot_user],
    )
    await adapter._handle_message(message)

    adapter.handle_message.assert_awaited_once()
    assert [endpoint for endpoint, _ in calls] == ["observe"]


@pytest.mark.asyncio
async def test_buzzer_unavailable_direct_message_skips_claim(adapter, monkeypatch):
    """Direct-addressed messages still skip claims even if Buzzer would be unavailable."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("BUZZER_TOKEN_LUNA", "test-token")
    adapter.config.extra["buzzer_channels"] = ["500"]
    calls = []

    def fake_buzzer(endpoint, payload):
        calls.append((endpoint, payload))
        if endpoint == "claim":
            return False, {}, "boom"
        return True, {"ok": True}, None

    monkeypatch.setattr(adapter, "_post_buzzer_sync", fake_buzzer)

    message = make_message(channel=FakeTextChannel(channel_id=500), content="luna please answer")
    await adapter._handle_message(message)

    adapter.handle_message.assert_awaited_once()
    assert [endpoint for endpoint, _ in calls] == ["observe"]


@pytest.mark.asyncio
async def test_buzzer_send_revalidates_and_finishes_after_success(adapter, monkeypatch):
    """Final Discord sends revalidate the claim and finish only after posting."""
    monkeypatch.setenv("BUZZER_TOKEN_LUNA", "test-token")
    calls = []

    def fake_buzzer(endpoint, payload):
        calls.append((endpoint, payload))
        return True, {"ok": True}, None

    monkeypatch.setattr(adapter, "_post_buzzer_sync", fake_buzzer)
    message = make_message(channel=FakeTextChannel(channel_id=500), content="hello")
    payload = adapter._buzzer_payload(message)
    payload["slot"] = "first"
    adapter._remember_buzzer_claim(message, payload, {"claimId": "claim-1"}, "first")

    sent = []

    class FakeChannel:
        async def fetch_message(self, message_id):
            return SimpleNamespace(to_reference=lambda fail_if_not_exists=False: "ref")

        async def send(self, content, reference=None):
            sent.append((content, reference))
            return SimpleNamespace(id=999)

    adapter._client = SimpleNamespace(user=SimpleNamespace(id=999), get_channel=lambda channel_id: FakeChannel())

    result = await adapter.send("500", "hello", reply_to=str(message.id), metadata={"notify": True})

    assert result.success
    assert sent == [("hello", "ref")]
    assert [endpoint for endpoint, _ in calls] == ["revalidate", "finish"]
    assert calls[0][1]["claimId"] == "claim-1"
    assert calls[1][1]["claimId"] == "claim-1"
    assert str(message.id) not in adapter._buzzer_claimed_messages


@pytest.mark.asyncio
async def test_buzzer_send_revalidate_denial_cancels_send_and_fails(adapter, monkeypatch):
    """If revalidate denies, Discord send is cancelled and the claim is failed."""
    monkeypatch.setenv("BUZZER_TOKEN_LUNA", "test-token")
    calls = []

    def fake_buzzer(endpoint, payload):
        calls.append((endpoint, payload))
        if endpoint == "revalidate":
            return True, {"ok": False}, None
        return True, {"ok": True}, None

    monkeypatch.setattr(adapter, "_post_buzzer_sync", fake_buzzer)
    message = make_message(channel=FakeTextChannel(channel_id=500), content="hello")
    payload = adapter._buzzer_payload(message)
    payload["slot"] = "first"
    adapter._remember_buzzer_claim(message, payload, {"claimId": "claim-2"}, "first")

    class FakeChannel:
        async def fetch_message(self, message_id):
            return SimpleNamespace(to_reference=lambda fail_if_not_exists=False: "ref")

        async def send(self, content, reference=None):
            raise AssertionError("send should not be called after revalidate denial")

    adapter._client = SimpleNamespace(user=SimpleNamespace(id=999), get_channel=lambda channel_id: FakeChannel())

    result = await adapter.send("500", "hello", reply_to=str(message.id), metadata={"notify": True})

    assert not result.success
    assert result.error == "buzzer_revalidate_denied"
    assert [endpoint for endpoint, _ in calls] == ["revalidate", "fail"]
    assert calls[1][1]["reason"] == "revalidate_denied"
    assert str(message.id) not in adapter._buzzer_claimed_messages

@pytest.mark.asyncio
async def test_buzzer_queue_mode_allows_generation_without_preclaim(adapter, monkeypatch):
    """Queue mode does not pre-lock the turn; it stores context for final-send arbitration."""
    monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "false")
    monkeypatch.setenv("BUZZER_TOKEN_LUNA", "test-token")
    adapter.config.extra["buzzer_channels"] = ["500"]
    adapter.config.extra["buzzer_queue_enabled"] = True
    calls = []

    def fake_buzzer(endpoint, payload):
        calls.append((endpoint, payload))
        return True, {"ok": True}, None

    monkeypatch.setattr(adapter, "_post_buzzer_sync", fake_buzzer)

    message = make_message(channel=FakeTextChannel(channel_id=500), content="ambient chat")
    await adapter._handle_message(message)

    adapter.handle_message.assert_awaited_once()
    assert [endpoint for endpoint, _ in calls] == ["observe"]
    stored = adapter._buzzer_queue_messages[str(message.id)]
    assert stored["messageId"] == str(message.id)
    assert stored["intent"] == "ambient"


@pytest.mark.asyncio
async def test_buzzer_queue_submit_deliver_sends_candidate(adapter, monkeypatch):
    """Final sends POST generated text to /v1/queue/submit and deliver on status=deliver."""
    monkeypatch.setenv("BUZZER_TOKEN_LUNA", "test-token")
    adapter.config.extra["buzzer_queue_enabled"] = True
    message = make_message(channel=FakeTextChannel(channel_id=500), content="hello")
    payload = adapter._buzzer_payload(message)
    payload.update({"intent": "ambient", "enthusiasm": 2, "directAddressed": False})
    adapter._buzzer_queue_messages[str(message.id)] = payload
    queue_calls = []

    def fake_queue(payload):
        queue_calls.append(payload)
        return True, {"status": "deliver", "publishToken": "pub-1", "winnerAgent": "luna"}, None

    monkeypatch.setattr(adapter, "_post_buzzer_queue_sync", fake_queue)
    sent = []

    class FakeChannel:
        async def fetch_message(self, message_id):
            return SimpleNamespace(to_reference=lambda fail_if_not_exists=False: "ref")

        async def send(self, content, reference=None):
            sent.append((content, reference))
            return SimpleNamespace(id=999)

    adapter._client = SimpleNamespace(user=SimpleNamespace(id=999), get_channel=lambda channel_id: FakeChannel())

    result = await adapter.send("500", "hello", reply_to=str(message.id), metadata={"notify": True})

    assert result.success
    assert sent == [("hello", "ref")]
    assert queue_calls[0]["roomId"].endswith(":500")
    assert queue_calls[0]["messageId"] == str(message.id)
    assert queue_calls[0]["agent"] == "luna"
    assert queue_calls[0]["candidateText"] == "hello"
    assert queue_calls[0]["intent"] == "ambient"
    assert "generatedAt" in queue_calls[0]


@pytest.mark.asyncio
async def test_buzzer_queue_submit_superseded_suppresses_candidate(adapter, monkeypatch):
    """status=superseded cancels the Discord send and retains winnerText for follow-up logic."""
    monkeypatch.setenv("BUZZER_TOKEN_LUNA", "test-token")
    adapter.config.extra["buzzer_queue_enabled"] = True
    message = make_message(channel=FakeTextChannel(channel_id=500), content="hello")
    payload = adapter._buzzer_payload(message)
    payload.update({"intent": "ambient", "enthusiasm": 2, "directAddressed": False})
    adapter._buzzer_queue_messages[str(message.id)] = payload

    def fake_queue(payload):
        return True, {
            "status": "superseded",
            "winnerAgent": "ramona",
            "winnerText": "First answer",
            "winnerIntent": "ambient",
        }, None

    monkeypatch.setattr(adapter, "_post_buzzer_queue_sync", fake_queue)

    class FakeChannel:
        async def fetch_message(self, message_id):
            return SimpleNamespace(to_reference=lambda fail_if_not_exists=False: "ref")

        async def send(self, content, reference=None):
            raise AssertionError("send should be suppressed after queue superseded")

    adapter._client = SimpleNamespace(user=SimpleNamespace(id=999), get_channel=lambda channel_id: FakeChannel())

    result = await adapter.send("500", "Second answer", reply_to=str(message.id), metadata={"notify": True})

    assert result.success
    assert result.raw_response["suppressed"] is True
    assert result.raw_response["reason"] == "superseded"
    assert adapter._buzzer_superseded_messages[str(message.id)]["winnerText"] == "First answer"
    assert adapter._buzzer_superseded_messages[str(message.id)]["candidateText"] == "Second answer"


@pytest.mark.asyncio
async def test_buzzer_queue_submit_includes_followup_fields(adapter, monkeypatch):
    """Follow-up sends include followUpOf and followUpReason in the queue payload."""
    monkeypatch.setenv("BUZZER_TOKEN_LUNA", "test-token")
    adapter.config.extra["buzzer_queue_enabled"] = True
    msg_id = "123:followup:luna"
    adapter._buzzer_queue_messages[msg_id] = {
        "roomId": "discord:500",
        "messageId": msg_id,
        "intent": "follow_up",
        "enthusiasm": 4,
        "directAddressed": False,
    }
    queue_calls = []

    def fake_queue(payload):
        queue_calls.append(payload)
        return True, {"status": "deliver", "publishToken": "pub-follow"}, None

    monkeypatch.setattr(adapter, "_post_buzzer_queue_sync", fake_queue)

    decision, data = await adapter._submit_buzzer_queue(
        msg_id,
        "Actually, one small correction...",
        {"followUpOf": "123", "followUpReason": "correction"},
    )

    assert decision == "deliver"
    assert data["status"] == "deliver"
    assert queue_calls[0]["followUpOf"] == "123"
    assert queue_calls[0]["followUpReason"] == "correction"
