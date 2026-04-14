"""FrigateListener: MQTT client that dispatches Frigate reviews to actions."""

from __future__ import annotations

import json
import logging
from typing import Any

import attrs
import paho.mqtt.client as mqtt
import trio

from frigate_monitoring.actions.base import Action
from frigate_monitoring.config import Config, get_config
from frigate_monitoring.enabled import POLL_INTERVAL_SECONDS, EnabledCheck
from frigate_monitoring.event import FrigateEvent
from frigate_monitoring.filter import ReviewFilter
from frigate_monitoring.recorder import MqttRecorder
from frigate_monitoring.review import FrigateReview
from frigate_monitoring.tracker import ReviewTracker

log = logging.getLogger(__name__)

_RECONNECT_MIN_DELAY = 1.0
_RECONNECT_MAX_DELAY = 120.0


def _with_events(review: FrigateReview, events: list[FrigateEvent]) -> FrigateReview:
    """Return a copy of *review* with its resolved events replaced."""
    copy = attrs.evolve(review)
    copy.events = events
    return copy


class FrigateListener:
    """Connect to the MQTT broker, subscribe to Frigate reviews, and dispatch them.

    Every MQTT message updates the :class:`ReviewTracker` so event scores
    accumulate across the review lifecycle.  Actions using ``triggers`` fire
    at the right moment:

    * ``"start"`` — first time the review matches the action's filter,
      including having at least one event satisfying event-level criteria
    * ``"best"`` — once at review end, with all events at their final scores

    Parameters
    ----------
    config:
        A :class:`Config` instance.  Falls back to :func:`get_config` if omitted.
    """

    def __init__(self, config: Config | None = None) -> None:
        cfg = config or get_config()
        self.mqtt_host = cfg.mqtt_host
        self.mqtt_port = cfg.mqtt_port
        self.mqtt_user = cfg.mqtt_user
        self.mqtt_password = cfg.mqtt_password
        self.topic = cfg.mqtt_topic
        self._actions: list[tuple[Action, ReviewFilter, EnabledCheck]] = []
        self._recorders: list[MqttRecorder] = []
        self._reconnect_delay = _RECONNECT_MIN_DELAY
        self._tracker = ReviewTracker()

        api = mqtt.CallbackAPIVersion.VERSION2  # type: ignore[attr-defined]
        self._client = mqtt.Client(api)
        if self.mqtt_user:
            self._client.username_pw_set(self.mqtt_user, self.mqtt_password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    def add_action(  # pylint: disable=redefined-builtin
        self,
        action: Action,
        filter: ReviewFilter | None = None,
        enabled: EnabledCheck = True,
    ) -> "FrigateListener":
        """Register an action handler.  Returns ``self`` to allow method chaining."""
        self._actions.append((action, filter or ReviewFilter(), enabled))
        return self

    def add_recorder(self, recorder: MqttRecorder) -> "FrigateListener":
        """Register an MQTT recorder.  Returns ``self`` to allow method chaining."""
        self._recorders.append(recorder)
        return self

    async def run(self) -> None:
        """Connect to the broker and run until a :exc:`KeyboardInterrupt`.

        Messages are bridged from the paho thread into trio via a memory channel.
        Actions for each review run concurrently inside a trio nursery.
        Reconnects on initial connection failure with exponential backoff (1 s → 120 s).
        """
        log.info("Connecting to MQTT broker %s:%s …", self.mqtt_host, self.mqtt_port)
        await self._connect_with_backoff()

        send_chan, recv_chan = trio.open_memory_channel[mqtt.MQTTMessage](100)

        def _on_message(
            _client: mqtt.Client,
            _userdata: Any,
            msg: mqtt.MQTTMessage,
        ) -> None:
            try:
                trio.from_thread.run_sync(send_chan.send_nowait, msg)
            except (trio.WouldBlock, trio.ClosedResourceError):
                log.warning("MQTT message dropped (channel full or shutting down)")

        self._client.on_message = _on_message

        try:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._mqtt_loop_task, send_chan)
                nursery.start_soon(self._poll_enabled_checks)
                async with recv_chan:
                    async for msg in recv_chan:
                        nursery.start_soon(self._handle_raw_message, msg)
        finally:
            for rec in self._recorders:
                rec.close()
            self._client.disconnect()

    async def _connect_with_backoff(self) -> None:
        while True:
            try:
                await trio.to_thread.run_sync(
                    lambda: self._client.connect(
                        self.mqtt_host, self.mqtt_port, keepalive=60
                    ),
                    abandon_on_cancel=True,
                )
                self._reconnect_delay = _RECONNECT_MIN_DELAY
                return
            except OSError as exc:
                log.warning(
                    "Could not connect to %s:%s (%s). Retrying in %.0fs …",
                    self.mqtt_host,
                    self.mqtt_port,
                    exc,
                    self._reconnect_delay,
                )
                await trio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, _RECONNECT_MAX_DELAY
                )

    async def _poll_enabled_checks(self) -> None:
        """Periodically refresh dynamic enabled checks (HTTP, command)."""
        dynamic = [ec for _, _, ec in self._actions if not isinstance(ec, bool)]
        if not dynamic:
            return
        while True:
            for check in dynamic:
                try:
                    await check.refresh()
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    log.warning(
                        "Enabled check refresh failed for %s: %s",
                        type(check).__name__,
                        exc,
                    )
            await trio.sleep(POLL_INTERVAL_SECONDS)

    async def _mqtt_loop_task(
        self, send_chan: trio.MemorySendChannel[mqtt.MQTTMessage]
    ) -> None:
        """Run paho's blocking loop in a thread; close the channel when it exits."""
        await trio.to_thread.run_sync(self._client.loop_forever, abandon_on_cancel=True)
        await send_chan.aclose()

    async def _handle_raw_message(self, msg: mqtt.MQTTMessage) -> None:
        try:
            payload: dict[str, Any] = json.loads(msg.payload)
        except json.JSONDecodeError as exc:
            log.warning("Could not parse MQTT message: %s", exc)
            return

        for rec in self._recorders:
            try:
                rec.record(msg.topic, payload)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                log.warning("Recorder error: %s", exc)

        try:
            review = FrigateReview.from_payload(payload)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            log.warning("Could not build FrigateReview: %s — payload: %s", exc, payload)
            return

        await self.dispatch(review)

    async def dispatch(self, review: FrigateReview) -> None:
        """Update the tracker, resolve events, and run matching actions.

        On every message the tracker accumulates event state.  Actions with
        ``triggers`` fire at the right moment:

        * ``"start"`` — checked on every message; fires the first time the
          review matches a given action's filter, including having at least one
          event that satisfies the action's event-level criteria (e.g. labels).
        * ``"best"`` — fires once when ``review_type == "end"``.
        * Filters without ``triggers`` fire on every matching message.

        Each action receives a review whose events are pre-filtered to only
        those satisfying that action's event-level criteria.  If no events
        match, the action is skipped for this message.
        """
        tracked = self._tracker.update(review)

        try:
            await self._tracker.resolve_events(tracked)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            log.warning(
                "Could not resolve events for review %s: %s",
                review.review_id,
                exc,
            )
            return

        if not review.events:
            if review.review_type == "end":
                self._tracker.end(review.review_id)
            return

        is_end = review.review_type == "end"

        async with trio.open_nursery() as nursery:
            for action_idx, (action, filt, enabled) in enumerate(self._actions):
                if not enabled:
                    continue
                filtered_events = filt.filter_events(review.events)
                if not filtered_events:
                    continue
                filtered_review = _with_events(review, filtered_events)
                if filt.triggers is not None:
                    if filt.matches(filtered_review, trigger="start"):
                        if self._tracker.should_fire_start(
                            review.review_id, action_idx
                        ):
                            filtered_review.trigger = "start"
                            nursery.start_soon(
                                self._safe_handle, action, filtered_review
                            )
                    if is_end and filt.matches(filtered_review, trigger="best"):
                        filtered_review.trigger = "best"
                        nursery.start_soon(self._safe_handle, action, filtered_review)
                else:
                    if filt.matches(filtered_review):
                        nursery.start_soon(self._safe_handle, action, filtered_review)

        if is_end:
            self._tracker.end(review.review_id)

    async def _safe_handle(self, action: Action, review: FrigateReview) -> None:
        try:
            await action.handle(review)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            try:
                await action.on_error(review, exc)
            except Exception as err:  # pylint: disable=broad-exception-caught
                log.error("on_error raised in %s: %s", type(action).__name__, err)

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _connect_flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        if reason_code.is_failure:
            log.error("Connection refused: %s", reason_code)
        else:
            log.info("Connected.  Subscribing to '%s'.", self.topic)
            self._reconnect_delay = _RECONNECT_MIN_DELAY
            client.subscribe(self.topic)

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        if reason_code.is_failure:
            log.warning(
                "Unexpected disconnect (%s). Reconnecting in %.0fs …",
                reason_code,
                self._reconnect_delay,
            )
