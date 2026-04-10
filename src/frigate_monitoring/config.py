"""Runtime configuration.

Core settings live in the :class:`Config` class.  On startup, call
:func:`load_dotenv` (best-effort, no-op without python-dotenv) then build a
``Config`` via :meth:`Config.from_env` or from YAML values.

The active config is stored once with :func:`init` and retrieved anywhere via
:func:`get_config`.
"""

from __future__ import annotations

import os

import attrs


@attrs.define
class Config:
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_user: str | None = None
    mqtt_password: str | None = None
    mqtt_topic: str = "frigate/reviews"

    frigate_host: str = "localhost"
    frigate_port: int = 5000
    frigate_external_url: str | None = None

    datetime_format: str = "%Y-%m-%d %H:%M:%S"

    @classmethod
    def from_env(cls, *, use_dotenv: bool = True) -> Config:
        """Build a Config from environment variables, with sensible defaults.

        When *use_dotenv* is True (the default), ``.env`` is loaded first so
        its values are available as regular environment variables.
        """
        if use_dotenv:
            load_dotenv()
        return cls(
            mqtt_host=os.environ.get("FRIGATE_MQTT_HOST", "localhost"),
            mqtt_port=int(os.environ.get("FRIGATE_MQTT_PORT", "1883")),
            mqtt_user=os.environ.get("FRIGATE_MQTT_USER"),
            mqtt_password=os.environ.get("FRIGATE_MQTT_PASSWORD"),
            mqtt_topic=os.environ.get("FRIGATE_MQTT_TOPIC", "frigate/reviews"),
            frigate_host=os.environ.get("FRIGATE_HOST", "localhost"),
            frigate_port=int(os.environ.get("FRIGATE_PORT", "5000")),
            frigate_external_url=os.environ.get("FRIGATE_EXTERNAL_URL"),
        )

    @property
    def frigate_base_url(self) -> str:
        return f"http://{self.frigate_host}:{self.frigate_port}"


_active: Config | None = None


def init(config: Config) -> None:
    """Set the active config.  Call once at startup."""
    global _active  # noqa: PLW0603
    _active = config


def get_config() -> Config:
    """Return the active config, or a default if :func:`init` was never called."""
    if _active is None:
        return Config()
    return _active


def load_dotenv() -> None:
    """Best-effort .env load.  No-op if python-dotenv is not installed."""
    try:
        from dotenv import find_dotenv
        from dotenv import load_dotenv as _load

        _load(find_dotenv(usecwd=True))
    except ImportError:
        pass
