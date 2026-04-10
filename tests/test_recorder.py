"""Tests for MQTT recording and replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from tests.conftest import make_payload

from frigate_monitoring.actions.base import Action
from frigate_monitoring.event import FrigateEvent
from frigate_monitoring.filter import ReviewFilter
from frigate_monitoring.listener import FrigateListener
from frigate_monitoring.recorder import MqttRecorder, load_recording, replay
from frigate_monitoring.review import FrigateReview


def _write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    with path.open("w") as f:
        for i, p in enumerate(payloads):
            f.write(
                json.dumps(
                    {"ts": 1700000000.0 + i, "topic": "frigate/reviews", "payload": p}
                )
                + "\n"
            )


def test_record_and_load(tmp_path: Path) -> None:
    rec = MqttRecorder(tmp_path / "sub" / "test.jsonl")
    payload = make_payload()
    rec.record("frigate/reviews", payload)
    rec.record("frigate/reviews", make_payload(camera="garage"))
    rec.close()

    messages = load_recording(tmp_path / "sub" / "test.jsonl")
    assert len(messages) == 2
    assert messages[0]["payload"]["after"]["camera"] == "front_door"
    assert messages[1]["payload"]["after"]["camera"] == "garage"
    assert "ts" in messages[0]


@pytest.mark.trio
async def test_replay_dispatches_to_actions(
    tmp_path: Path, fake_event: FrigateEvent
) -> None:
    recording = tmp_path / "test.jsonl"
    _write_jsonl(
        recording,
        [
            make_payload(camera="front_door", severity="alert"),
            make_payload(camera="garage", severity="detection"),
            make_payload(camera="back_door", severity="alert"),
        ],
    )

    handled: list[FrigateReview] = []

    class CollectorAction(Action):
        async def handle(self, review: FrigateReview) -> None:
            handled.append(review)

    listener = FrigateListener()
    listener.add_action(CollectorAction(), filter=ReviewFilter(alerts_only=True))

    with patch.object(FrigateEvent, "fetch", new=AsyncMock(return_value=fake_event)):
        reviews = await replay(recording, listener)

    assert len(reviews) == 3
    assert len(handled) == 2
    assert {r.camera for r in handled} == {"front_door", "back_door"}


@pytest.mark.trio
async def test_replay_skips_malformed_lines(
    tmp_path: Path, fake_event: FrigateEvent
) -> None:
    recording = tmp_path / "mixed.jsonl"
    with recording.open("w") as f:
        f.write("not json\n")
        f.write(json.dumps({"ts": 1.0, "topic": "t", "payload": make_payload()}) + "\n")
        f.write("\n")

    listener = FrigateListener()
    with patch.object(FrigateEvent, "fetch", new=AsyncMock(return_value=fake_event)):
        reviews = await replay(recording, listener)
    assert len(reviews) == 1


@pytest.mark.trio
async def test_replay_returns_empty_for_missing_file(tmp_path: Path) -> None:
    recording = tmp_path / "empty.jsonl"
    recording.write_text("")
    listener = FrigateListener()
    reviews = await replay(recording, listener)
    assert reviews == []
