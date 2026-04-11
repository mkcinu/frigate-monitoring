"""ReviewTracker: accumulate review state across MQTT messages.

Frigate publishes multiple messages per review (new, update, end).  The tracker
maintains a living view of each active review so that trigger-based actions can
fire at the right moment — e.g. ``start`` fires on the first message that
matches a given action's filter, and ``best`` fires once at review end.

Events are accumulated across all messages for a review and ranked by their
scores to determine the best event at any point in time.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import attrs
import trio

from frigate_monitoring.event import FrigateEvent
from frigate_monitoring.review import FrigateReview

log = logging.getLogger(__name__)


def event_rank(event: FrigateEvent) -> tuple[float, float, int, int]:
    """Return a sort key for ranking events — higher is better.

    Criteria (in order of importance):
    1. Top score (best confidence seen during tracking)
    2. Current score
    3. Has snapshot available
    4. Not stationary (moving objects are more interesting)
    """
    return (
        event.top_score,
        event.score,
        int(event.has_snapshot),
        int(not event.stationary),
    )


def pick_best(events: Sequence[FrigateEvent]) -> FrigateEvent | None:
    """Return the highest-ranked event, or ``None`` if *events* is empty."""
    if not events:
        return None
    return max(events, key=event_rank)


@attrs.define
class TrackedReview:
    """State accumulated for a single review across its MQTT lifecycle.

    A Frigate review spans multiple MQTT messages (new → update… → end).
    This class holds the living state so we can:

    * accumulate all events and continuously pick the best by score
    * remember which actions already fired their ``"start"`` trigger,
      so each action fires at most once per review (keyed by the
      action's index in the listener's action list)
    * remember the best event at ``"start"`` time so ``"best"`` can be
      skipped when the best event hasn't changed
    """

    review: FrigateReview
    events: dict[str, FrigateEvent] = attrs.field(factory=dict[str, FrigateEvent])
    best_event: FrigateEvent | None = attrs.field(default=None)
    _started_actions: dict[int, bool] = attrs.field(factory=dict[int, bool])
    _start_event_ids: dict[int, str] = attrs.field(factory=dict[int, str])

    def mark_started(self, action_idx: int) -> None:
        """Record that action *action_idx* has fired its ``"start"`` trigger."""
        self._started_actions[action_idx] = True
        if self.best_event is not None:
            self._start_event_ids[action_idx] = self.best_event.event_id

    def has_started(self, action_idx: int) -> bool:
        """Return whether action *action_idx* already fired ``"start"``."""
        return self._started_actions.get(action_idx, False)

    def best_changed_since_start(self, action_idx: int) -> bool:
        """Return whether the best event differs from what it was at ``"start"`` time."""
        start_eid = self._start_event_ids.get(action_idx)
        if start_eid is None:
            return True
        if self.best_event is None:
            return True
        return self.best_event.event_id != start_eid

    def add_events(self, new_events: list[FrigateEvent]) -> None:
        """Merge newly fetched events and re-evaluate the best."""
        for ev in new_events:
            self.events[ev.event_id] = ev
        self.best_event = pick_best(list(self.events.values()))


@attrs.define
class ReviewTracker:
    """Track active reviews and gate trigger firing.

    Plain synchronous class (except for :meth:`resolve_events` which is async
    because it fetches events over HTTP).  The tracker is owned by the listener
    and called from its message-processing loop.
    """

    _max_tracked: int = 10_000
    _reviews: dict[str, TrackedReview] = attrs.field(factory=dict[str, TrackedReview])

    def update(self, review: FrigateReview) -> TrackedReview:
        """Create or update the tracked state for *review*.

        Always call this for every incoming MQTT message so the tracker has
        the latest review state (severity, event_ids, etc.).
        Returns the tracked review for further operations.
        """
        tracked = self._reviews.get(review.review_id)
        if tracked is None:
            log.debug(
                "New review %s [%s] camera=%s severity=%s events=%s",
                review.review_id,
                review.review_type,
                review.camera,
                review.severity,
                review.event_ids,
            )
            tracked = TrackedReview(review=review)
            self._reviews[review.review_id] = tracked
            self._evict()
        else:
            log.debug(
                "Update review %s [%s] severity=%s events=%s",
                review.review_id,
                review.review_type,
                review.severity,
                review.event_ids,
            )
            tracked.review = review
        return tracked

    def get(self, review_id: str) -> TrackedReview | None:
        """Return the tracked state for *review_id*, or ``None``."""
        return self._reviews.get(review_id)

    async def resolve_events(self, tracked: TrackedReview) -> None:
        """Fetch events and re-evaluate the best.

        On intermediate messages (new/update): only fetches event IDs not yet
        cached, since we just need to discover new detections.

        On end: re-fetches all events to pick up final scores and snapshots
        (Frigate continuously improves these while the object is tracked).
        """
        review = tracked.review
        if not review.event_ids:
            return

        is_end = review.review_type == "end"
        if is_end:
            ids_to_fetch = review.event_ids
        else:
            ids_to_fetch = [
                eid for eid in review.event_ids if eid not in tracked.events
            ]

        if not ids_to_fetch:
            if tracked.best_event is not None:
                review.best_event = tracked.best_event
            return

        new_events: list[FrigateEvent] = []

        async def _fetch(eid: str) -> None:
            try:
                ev = await FrigateEvent.fetch(eid)
                new_events.append(ev)
                log.debug(
                    "Fetched event %s: label=%s top_score=%.3f"
                    " score=%.3f snapshot=%s stationary=%s",
                    ev.event_id,
                    ev.label,
                    ev.top_score,
                    ev.score,
                    ev.has_snapshot,
                    ev.stationary,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                log.warning("Could not fetch event %s: %s", eid, exc)

        async with trio.open_nursery() as nursery:
            for eid in ids_to_fetch:
                nursery.start_soon(_fetch, eid)

        old_best = tracked.best_event
        tracked.add_events(new_events)

        if tracked.best_event is not None:
            review.best_event = tracked.best_event
            if old_best is None or old_best.event_id != tracked.best_event.event_id:
                be = tracked.best_event
                log.debug(
                    "Best event updated for review %s: %s (label=%s top_score=%.3f)",
                    review.review_id,
                    be.event_id,
                    be.label,
                    be.top_score,
                )
            elif old_best.top_score != tracked.best_event.top_score:
                log.debug(
                    "Best event %s score improved: %.3f → %.3f",
                    tracked.best_event.event_id,
                    old_best.top_score,
                    tracked.best_event.top_score,
                )

    def should_fire_start(self, review_id: str, action_idx: int) -> bool:
        """Return ``True`` the first time ``start`` is requested for *(review, action)*.

        Returns ``False`` on subsequent calls (deduplication) or if the review
        is not tracked.
        """
        tracked = self._reviews.get(review_id)
        if tracked is None:
            return False
        if tracked.has_started(action_idx):
            return False
        tracked.mark_started(action_idx)
        return True

    def end(self, review_id: str) -> None:
        """Remove a review from tracking and evict overflow if needed."""
        tracked = self._reviews.pop(review_id, None)
        if tracked is not None:
            best = tracked.best_event
            log.debug(
                "Review ended %s: %d events tracked, best=%s",
                review_id,
                len(tracked.events),
                (
                    f"{best.event_id} (label={best.label} top_score={best.top_score:.3f})"
                    if best
                    else "none"
                ),
            )
        self._evict()

    def _evict(self) -> None:
        while len(self._reviews) > self._max_tracked:
            oldest = next(iter(self._reviews))
            log.debug("Evicting stale tracked review %s", oldest)
            del self._reviews[oldest]
