"""Enabled-check system: resolve per-action ``enabled`` flags to booleans.

Each action can specify ``enabled: true``, ``enabled: false``, or a dict
describing an HTTP or command-based check.  Dynamic checks (HTTP, command)
are stateful — they cache their last resolved value and expose a
:meth:`refresh` method called by a periodic background task.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

import attrs
import httpx
import trio
from jinja2 import Environment

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60

_env = Environment()

TRUTHY_STRINGS = frozenset({"1", "true", "yes", "on"})


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in TRUTHY_STRINGS
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(value)


@attrs.define
class HttpEnabledCheck:
    """Poll a URL and extract a boolean from the JSON response."""

    url: str
    headers: dict[str, str] = attrs.field(factory=dict[str, str])
    expr: str = ""
    timeout: float = 10.0
    _value: bool = attrs.field(default=True, alias="_value", init=False)

    def __bool__(self) -> bool:
        """Return the last resolved value."""
        return self._value

    async def refresh(self) -> None:
        """Fetch the URL and update the cached enabled state."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(self.url, headers=self.headers)
            resp.raise_for_status()
        body = resp.json()
        if not self.expr:
            new_value = _is_truthy(body)
        else:
            rendered = _env.from_string(self.expr).render(
                body if isinstance(body, dict) else {"_": body}
            )
            new_value = rendered.strip().lower() in TRUTHY_STRINGS
        if new_value != self._value:
            log.info(
                "HTTP enabled check %s changed: %s -> %s",
                self.url,
                self._value,
                new_value,
            )
        self._value = new_value


@attrs.define
class CommandEnabledCheck:
    """Run a shell command; enabled when the exit status is 0 (success)."""

    command: str
    timeout: float = 10.0
    _value: bool = attrs.field(default=True, alias="_value", init=False)

    def __bool__(self) -> bool:
        """Return the last resolved value."""
        return self._value

    async def refresh(self) -> None:
        """Run the command and update the cached enabled state."""
        proc = await trio.to_thread.run_sync(
            lambda: subprocess.run(
                self.command,
                shell=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        )
        new_value = not proc.returncode
        if new_value != self._value:
            log.info(
                "Command enabled check %r changed: %s -> %s",
                self.command,
                self._value,
                new_value,
            )
        self._value = new_value


EnabledCheck = bool | HttpEnabledCheck | CommandEnabledCheck


def structure_enabled(raw: bool | dict[str, Any]) -> EnabledCheck:
    """Convert a raw YAML value into an EnabledCheck."""
    if isinstance(raw, bool):
        return raw
    assert isinstance(
        raw, dict
    ), f"'enabled' must be a bool or a mapping, got {type(raw).__name__}"

    if "url" in raw:
        return HttpEnabledCheck(
            url=raw["url"],
            headers=raw.get("headers", {}),
            expr=raw.get("expr", ""),
            timeout=float(raw.get("timeout", 10.0)),
        )
    if "command" in raw:
        return CommandEnabledCheck(
            command=raw["command"],
            timeout=float(raw.get("timeout", 10.0)),
        )
    raise ValueError(
        f"'enabled' mapping must contain 'url' or 'command', got keys: {sorted(raw)}"
    )
