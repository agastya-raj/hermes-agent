from gateway.config import Platform
from gateway.run import _discord_streaming_disabled_for_source
from gateway.session import SessionSource


def test_discord_streaming_disabled_for_exact_channel():
    config = {"discord": {"streaming_disabled_channels": ["1503787550941122641"]}}
    source = SessionSource(
        platform=Platform.DISCORD,
        chat_id="1503787550941122641",
        chat_type="channel",
    )

    assert _discord_streaming_disabled_for_source(config, source) is True


def test_discord_streaming_disabled_matches_parent_for_thread():
    config = {"discord": {"streaming_disabled_channels": ["parent-channel"]}}
    source = SessionSource(
        platform=Platform.DISCORD,
        chat_id="thread-id",
        parent_chat_id="parent-channel",
        chat_type="thread",
    )

    assert _discord_streaming_disabled_for_source(config, source) is True


def test_discord_streaming_disabled_does_not_affect_other_discord_channels():
    config = {"discord": {"streaming_disabled_channels": ["living-room"]}}
    source = SessionSource(
        platform=Platform.DISCORD,
        chat_id="other-channel",
        chat_type="channel",
    )

    assert _discord_streaming_disabled_for_source(config, source) is False


def test_discord_streaming_disabled_does_not_affect_other_platforms():
    config = {"discord": {"streaming_disabled_channels": ["1503787550941122641"]}}
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="1503787550941122641",
        chat_type="group",
    )

    assert _discord_streaming_disabled_for_source(config, source) is False
