import pytest

from hermes_cli.commands import gateway_command_records

pytestmark = pytest.mark.anyio("asyncio")


def _record(name: str, records: list[dict]):
    return next(record for record in records if record["name"] == name)


async def test_gateway_command_records_include_gateway_commands():
    records = gateway_command_records(include_plugins=False)
    names = {record["name"] for record in records}
    assert "help" in names
    assert "status" in names
    assert "model" in names
    assert "approve" in names
    assert "clear" not in names
    status = _record("status", records)
    assert status["enabled"] is True
    assert status["risk"] == "read_only"
    approve = _record("approve", records)
    assert approve["supported"] is True
    assert approve["enabled"] is False
    assert approve["risk"] == "dangerous"
    background = _record("background", records)
    assert "bg" in background["aliases"]


def test_gateway_command_records_have_phase1_schema():
    records = gateway_command_records(include_plugins=False)
    required = {
        "name",
        "aliases",
        "description",
        "category",
        "args_hint",
        "subcommands",
        "source",
        "risk",
        "gateway_supported",
        "api_supported",
        "enabled",
        "disabled_reason",
        "mid_run",
        "input_mode",
        "execution_mode",
    }
    assert records
    for record in records:
        assert required.issubset(record), record
    assert _record("status", records)["input_mode"] == "none"
    assert _record("status", records)["execution_mode"] == "sync"
    assert _record("new", records)["execution_mode"] == "confirmation_required"
    assert _record("new", records)["disabled_reason"]


def test_gateway_command_records_include_plugin_commands_as_metadata_only(monkeypatch):
    import hermes_cli.commands as commands_mod

    monkeypatch.setattr(
        commands_mod,
        "_iter_plugin_command_entries",
        lambda: [("example-plugin", "Example plugin command", "<target>")],
    )

    records = gateway_command_records(include_plugins=True)
    plugin = _record("example-plugin", records)
    assert plugin["source"] == "plugin"
    assert plugin["gateway_supported"] is True
    assert plugin["api_supported"] is False
    assert plugin["enabled"] is False
    assert plugin["execution_mode"] == "metadata_only"
    assert plugin["input_mode"] == "text"
    assert "not exposed" in plugin["disabled_reason"]


def test_gateway_command_records_include_skill_commands_without_paths(monkeypatch):
    import agent.skill_commands as skill_commands

    monkeypatch.setattr(
        skill_commands,
        "get_skill_commands",
        lambda: {
            "/demo-skill": {
                "name": "Demo Skill",
                "description": "Invoke demo skill",
                "skill_md_path": "/tmp/secret/SKILL.md",
                "skill_dir": "/tmp/secret",
            }
        },
    )

    records = gateway_command_records(include_plugins=False, include_skills=True)
    skill = _record("demo-skill", records)
    assert skill["source"] == "skill"
    assert skill["risk"] == "agent_execution"
    assert skill["gateway_supported"] is True
    assert skill["api_supported"] is False
    assert skill["enabled"] is False
    assert skill["execution_mode"] == "run"
    assert skill["input_mode"] == "text"
    assert "skill_md_path" not in skill
    assert "skill_dir" not in skill
    assert "/tmp/secret" not in repr(skill)
    assert "Invoke demo skill" not in skill["description"]
    assert skill["description"] == "Invoke the Demo Skill skill"


async def test_api_server_exposes_command_routes_in_capabilities():
    import json
    from types import SimpleNamespace

    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={"key": ""}))
    response = await adapter._handle_capabilities(SimpleNamespace(headers={}))
    payload = json.loads(response.text)

    assert payload["features"]["slash_command_registry"] is True
    assert payload["features"]["slash_command_dispatch"] == "metadata_and_read_only_subset"
    assert payload["endpoints"]["commands"] == {"method": "GET", "path": "/v1/commands"}
    assert payload["endpoints"]["command_execute"] == {"method": "POST", "path": "/v1/commands/{name}"}
    assert hasattr(adapter, "_handle_commands")
    assert hasattr(adapter, "_handle_command_execute")
