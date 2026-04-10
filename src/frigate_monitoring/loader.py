"""Load a FrigateListener from a YAML configuration file.

Example ``config.yaml``::

    mqtt:
      host: 192.168.1.100
      port: 1883

    frigate:
      host: 192.168.1.100
      port: 5000
      external_url: https://frigate.example.com

    actions:
      - type: print
        template: "[{camera}] {severity}: {objects} ({score_pct})"
        filter:
          cameras: [front_door, back_door]
          alerts_only: true

      - type: webhook
        url: https://hooks.example.com/alert
        method: POST
        body:
          text: "{label} on {camera} ({score_pct})"
        filter:
          alerts_only: true

      - type: pushover
        token: ${PUSHOVER_TOKEN}
        user_key: ${PUSHOVER_USER}
        options:
          sound: siren
          priority: 1
        filter:
          alerts_only: true
          review_types: [end]

    record:
      path: recordings/mqtt.jsonl
"""

from __future__ import annotations

import importlib
import logging
import os
import re
from datetime import time
from pathlib import Path
from typing import Any, cast

import cattrs
import yaml

from frigate_monitoring.actions.base import Action
from frigate_monitoring.config import Config, init, load_dotenv
from frigate_monitoring.filter import ReviewFilter
from frigate_monitoring.listener import FrigateListener

log = logging.getLogger(__name__)

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")

_ACTION_REGISTRY: dict[str, tuple[str, str]] = {
    "print": ("frigate_monitoring.actions.print_action", "PrintAction"),
    "log": ("frigate_monitoring.actions.log_action", "LogAction"),
    "webhook": ("frigate_monitoring.actions.webhook", "WebhookAction"),
    "pushover": ("frigate_monitoring.actions.pushover", "PushoverAction"),
    "rich": ("frigate_monitoring.actions.rich_action", "RichAction"),
}

_converter = cattrs.Converter()
_converter.register_structure_hook(
    time,
    lambda v, _: v if isinstance(v, time) else time.fromisoformat(str(v)),
)


def _expand_env(value: str) -> str:
    """Replace ``${VAR}`` placeholders with environment variable values."""

    def _replace(m: re.Match[str]) -> str:
        name = m.group(1)
        val = os.environ.get(name)
        if val is None:
            raise ValueError(f"Environment variable ${{{name}}} is not set")
        return val

    return _ENV_VAR_RE.sub(_replace, value)


def _expand_env_recursive(obj: Any) -> Any:
    if isinstance(obj, str):
        return _expand_env(obj)
    if isinstance(obj, dict):
        return {k: _expand_env_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_recursive(v) for v in obj]
    return obj


def _resolve_action_class(name: str) -> type[Action]:
    if name not in _ACTION_REGISTRY:
        raise ValueError(
            f"Unknown action type: {name!r}. "
            f"Available: {', '.join(sorted(_ACTION_REGISTRY))}"
        )
    module_path, class_name = _ACTION_REGISTRY[name]
    module = importlib.import_module(module_path)
    return cast(type[Action], getattr(module, class_name))


def _build_action(raw: dict[str, Any]) -> tuple[Action, ReviewFilter]:
    raw = dict(raw)
    action_type = raw.pop("type")
    filter_raw = raw.pop("filter", None)
    filt = _converter.structure(filter_raw or {}, ReviewFilter)
    cls = _resolve_action_class(action_type)
    action = _converter.structure(raw, cls)
    return action, filt


def load_config(path: str | Path) -> dict[str, Any]:
    """Parse a YAML config file and return the raw dict (with env vars expanded)."""
    text = Path(path).read_text(encoding="utf-8")
    raw: dict[str, Any] = yaml.safe_load(text)
    result: dict[str, Any] = _expand_env_recursive(raw)
    return result


def _config_from_yaml(raw: dict[str, Any]) -> Config:
    """Build a :class:`Config` from parsed YAML, falling back to env-based defaults."""
    env = Config.from_env()
    mqtt = raw.get("mqtt", {})
    frigate = raw.get("frigate", {})
    return Config(
        mqtt_host=mqtt.get("host", env.mqtt_host),
        mqtt_port=int(mqtt.get("port", env.mqtt_port)),
        mqtt_user=mqtt.get("user", env.mqtt_user),
        mqtt_password=mqtt.get("password", env.mqtt_password),
        mqtt_topic=mqtt.get("topic", env.mqtt_topic),
        frigate_host=frigate.get("host", env.frigate_host),
        frigate_port=int(frigate.get("port", env.frigate_port)),
        frigate_external_url=frigate.get("external_url", env.frigate_external_url),
    )


def from_yaml(path: str | Path) -> FrigateListener:
    """Build a fully configured :class:`FrigateListener` from a YAML file.

    Environment variables (including from ``.env`` if loaded) serve as defaults.
    Explicit values in the YAML file override those defaults.  Secrets can
    reference environment variables via ``${VAR}`` syntax.
    """
    load_dotenv()
    raw = load_config(path)
    cfg = _config_from_yaml(raw)
    init(cfg)

    listener = FrigateListener(cfg)

    for action_raw in raw.get("actions", []):
        action, filt = _build_action(action_raw)
        listener.add_action(action, filter=filt)

    record = raw.get("record")
    if record:
        from frigate_monitoring.recorder import MqttRecorder

        rec_path = (
            record
            if isinstance(record, str)
            else record.get("path", "recordings/mqtt.jsonl")
        )
        recorder = MqttRecorder(Path(rec_path))
        listener.add_recorder(recorder)

    log.info(
        "Loaded config from %s with %d action(s)", path, len(raw.get("actions", []))
    )
    return listener
