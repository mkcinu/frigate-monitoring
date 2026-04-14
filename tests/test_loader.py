"""Tests for YAML config loader."""

from __future__ import annotations

import os
from datetime import time
from pathlib import Path
from unittest.mock import patch

from frigate_monitoring.actions.log_action import LogAction
from frigate_monitoring.actions.print_action import PrintAction
from frigate_monitoring.actions.webhook import WebhookAction
from frigate_monitoring.loader import from_yaml
from frigate_monitoring.types import Weekday


def test_load_minimal_config(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
mqtt:
  host: 10.0.0.1
  port: 1884

actions:
  - type: print
    template: "[{camera}] {objects}"
    filter:
      cameras: [front_door]
      alerts_only: true
""")
    listener = from_yaml(config_file)
    assert listener.mqtt_host == "10.0.0.1"
    assert listener.mqtt_port == 1884
    assert len(listener._actions) == 1
    action, filt, _ = listener._actions[0]
    assert isinstance(action, PrintAction)
    assert action.template == "[{camera}] {objects}"
    assert filt.cameras == ["front_door"]
    assert filt.alerts_only is True


def test_webhook_action_from_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
actions:
  - type: webhook
    url: https://example.com/hook
    method: PUT
    body:
      msg: "{label} on {camera}"
    headers:
      X-Custom: test
    filter:
      triggers: [best]
""")
    listener = from_yaml(config_file)
    action, filt, _ = listener._actions[0]
    assert isinstance(action, WebhookAction)
    assert action.method == "PUT"
    assert action.body == {"msg": "{label} on {camera}"}
    assert action.headers == {"X-Custom": "test"}
    assert filt.triggers == ["best"]


def test_env_var_expansion(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
actions:
  - type: webhook
    url: https://example.com/hook
    headers:
      Authorization: "Bearer ${TEST_SECRET_TOKEN}"
""")
    with patch.dict(os.environ, {"TEST_SECRET_TOKEN": "s3cret"}):
        listener = from_yaml(config_file)
    action, _, _ = listener._actions[0]
    assert isinstance(action, WebhookAction)
    assert action.headers["Authorization"] == "Bearer s3cret"


def test_multiple_actions(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
actions:
  - type: print
  - type: webhook
    url: https://example.com/a
  - type: webhook
    url: https://example.com/b
    filter:
      alerts_only: true
""")
    listener = from_yaml(config_file)
    assert len(listener._actions) == 3


def test_log_action_string_level_from_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
actions:
  - type: log
    level: INFO
    template: "[{camera}] {label}"
""")
    listener = from_yaml(config_file)
    action, _, _ = listener._actions[0]
    assert isinstance(action, LogAction)
    assert action.level == 20


def test_time_range_filter_from_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
actions:
  - type: print
    filter:
      time_range: ["22:00", "06:00"]
""")
    listener = from_yaml(config_file)
    _, filt, _ = listener._actions[0]
    assert filt.time_range == (time(22, 0), time(6, 0))


def test_weekday_filter_from_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
actions:
  - type: print
    filter:
      weekdays: [Monday, wed, 4]
""")
    listener = from_yaml(config_file)
    _, filt, _ = listener._actions[0]
    assert filt.weekdays == [Weekday.MON, Weekday.WED, Weekday.FRI]


def test_record_section(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"""
actions:
  - type: print

record:
  path: {tmp_path}/recording.jsonl
""")
    listener = from_yaml(config_file)
    assert len(listener._recorders) == 1
    assert listener._recorders[0].path == Path(f"{tmp_path}/recording.jsonl")
