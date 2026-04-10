"""Record and replay MQTT messages for dry-run testing and unit tests.

Messages are stored as newline-delimited JSON (JSONL).  Each line contains::

    {"ts": <unix-timestamp>, "topic": "<mqtt-topic>", "payload": <original-json>}

Usage — recording::

    listener = FrigateListener()
    listener.add_recorder(MqttRecorder(Path("recording.jsonl")))
    listener.run()

Usage — replay::

    listener = FrigateListener()
    listener.add_action(PrintAction())
    replay(Path("recording.jsonl"), listener)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

import trio

from frigate_monitoring.review import FrigateReview

if TYPE_CHECKING:
    from frigate_monitoring.listener import FrigateListener

log = logging.getLogger(__name__)


class MqttRecorder:
    """Append every incoming MQTT payload to a JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: IO[str] | None = None

    def open(self) -> None:
        """Open the recording file for appending, creating parent dirs as needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a")
        log.info("Recording MQTT messages to %s", self.path)

    def record(self, topic: str, payload: dict[str, Any]) -> None:
        """Append a single MQTT message as a JSON line."""
        if self._file is None:
            self.open()
        line = json.dumps({"ts": time.time(), "topic": topic, "payload": payload})
        assert self._file is not None
        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        """Flush and close the recording file."""
        if self._file is not None:
            self._file.close()
            self._file = None


def load_recording(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL recording file and return a list of message dicts."""
    messages: list[dict[str, Any]] = []
    with path.open() as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError as exc:
                log.warning("Skipping malformed line %d in %s: %s", line_no, path, exc)
    return messages


async def replay(
    path: Path,
    listener: FrigateListener,
    *,
    realtime: bool = False,
) -> list[FrigateReview]:
    """Replay recorded messages through a listener's action pipeline.

    Parameters
    ----------
    path:
        Path to the JSONL recording file.
    listener:
        A :class:`~listener.FrigateListener` instance with actions registered.
    realtime:
        When ``True``, sleep between messages to match original timing.

    Returns
    -------
    list:
        The :class:`~review.FrigateReview` objects that were dispatched.
    """
    messages = load_recording(path)
    if not messages:
        log.warning("No messages found in %s", path)
        return []

    reviews: list[FrigateReview] = []
    prev_ts = messages[0].get("ts", 0.0)

    for msg in messages:
        if realtime:
            delay = msg.get("ts", 0.0) - prev_ts
            if delay > 0:
                await trio.sleep(delay)
            prev_ts = msg.get("ts", 0.0)

        payload = msg.get("payload", {})
        try:
            review = FrigateReview.from_payload(payload)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            log.warning("Could not build FrigateReview during replay: %s", exc)
            continue

        reviews.append(review)
        await listener.dispatch(review)

    log.info(
        "Replayed %d messages (%d reviews) from %s", len(messages), len(reviews), path
    )
    return reviews
