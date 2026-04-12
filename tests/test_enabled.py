"""Tests for enabled-check system."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from frigate_monitoring.enabled import (
    CommandEnabledCheck,
    HttpEnabledCheck,
    structure_enabled,
)


def test_structure_bool() -> None:
    assert structure_enabled(True) is True
    assert structure_enabled(False) is False


def test_structure_http() -> None:
    spec = structure_enabled(
        {
            "url": "http://ha:8123/api/states/input_boolean.alerts",
            "headers": {"Authorization": "Bearer tok123"},
            "expr": "{{ state }}",
            "timeout": 5.0,
        }
    )
    assert isinstance(spec, HttpEnabledCheck)
    assert spec.headers == {"Authorization": "Bearer tok123"}
    assert spec.expr == "{{ state }}"
    assert spec.timeout == 5.0


def test_structure_command() -> None:
    spec = structure_enabled({"command": "test -f /tmp/armed"})
    assert isinstance(spec, CommandEnabledCheck)
    assert spec.command == "test -f /tmp/armed"


def test_structure_invalid_type() -> None:
    with pytest.raises(ValueError, match="must be a bool or a mapping"):
        structure_enabled("yes")


def test_structure_missing_url_and_command() -> None:
    with pytest.raises(ValueError, match="must contain 'url' or 'command'"):
        structure_enabled({"headers": {}})


async def test_http_refresh_truthy() -> None:
    check = HttpEnabledCheck(
        url="http://fake/state",
        expr="{{ state }}",
    )
    mock_get = AsyncMock()

    class FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, str]:
            return {"state": "on"}

    mock_get.return_value = FakeResp()

    with patch("httpx.AsyncClient.get", mock_get):
        await check.refresh()

    mock_get.assert_awaited_once()
    assert bool(check) is True


async def test_http_refresh_falsy() -> None:
    check = HttpEnabledCheck(
        url="http://fake/state",
        expr="{{ state }}",
    )
    mock_get = AsyncMock()

    class FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, str]:
            return {"state": "off"}

    mock_get.return_value = FakeResp()

    with patch("httpx.AsyncClient.get", mock_get):
        await check.refresh()

    mock_get.assert_awaited_once()
    assert bool(check) is False


async def test_http_refresh_no_expr() -> None:
    check = HttpEnabledCheck(url="http://fake/state")
    mock_get = AsyncMock()

    class FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> bool:
            return False

    mock_get.return_value = FakeResp()

    with patch("httpx.AsyncClient.get", mock_get):
        await check.refresh()

    mock_get.assert_awaited_once()
    assert bool(check) is False


async def test_command_refresh_success() -> None:
    check = CommandEnabledCheck(command="true")
    await check.refresh()
    assert bool(check) is True


async def test_command_refresh_failure() -> None:
    check = CommandEnabledCheck(command="false")
    await check.refresh()
    assert bool(check) is False


def test_loader_enabled_false(tmp_path: Path) -> None:
    from frigate_monitoring.loader import from_yaml

    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
actions:
  - type: print
    enabled: false
""")
    listener = from_yaml(config_file)
    _, _, enabled = listener._actions[0]
    assert enabled is False


def test_loader_enabled_http(tmp_path: Path) -> None:
    from frigate_monitoring.loader import from_yaml

    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
actions:
  - type: print
    enabled:
      url: http://ha:8123/api/states/input_boolean.alerts
      headers:
        Authorization: "Bearer ${HA_TOKEN}"
      expr: "{{ state }}"
""")
    with patch.dict("os.environ", {"HA_TOKEN": "secret-tok-123"}):
        listener = from_yaml(config_file)
    _, _, enabled = listener._actions[0]
    assert isinstance(enabled, HttpEnabledCheck)
    assert enabled.headers["Authorization"] == "Bearer secret-tok-123"
