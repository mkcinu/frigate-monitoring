"""ReviewFilter: predicate for selecting which reviews an action receives."""

from __future__ import annotations

from datetime import datetime, time

import attrs

from frigate_monitoring.review import FrigateReview
from frigate_monitoring.types import Trigger, Weekday


@attrs.define
class ReviewFilter:
    """Determines which reviews an :class:`~actions.Action` handler should receive.

    All specified criteria must match (AND logic).  Leave a field as its default
    to match any value for that dimension.

    Examples
    --------
    Immediate alert from the front or back door::

        ReviewFilter(
            cameras=["front_door", "back_door"],
            triggers=["start"],
            alerts_only=True,
        )

    Best-quality notification when a person review ends::

        ReviewFilter(triggers=["best"], objects=["person"])

    Only reviews that start during nighttime hours (wraps midnight)::

        ReviewFilter(
            triggers=["start", "best"],
            time_range=(time(22, 0), time(6, 0)),
        )

    Only reviews on weekends::

        ReviewFilter(weekdays=[Weekday.SAT, Weekday.SUN])
    """

    cameras: list[str] | None = None
    """Restrict to these camera names.  ``None`` matches any camera."""

    labels: list[str] | None = None
    """Restrict to reviews whose best-event label is one of these values
    (e.g. ``["person", "car"]``).  ``None`` matches any label."""

    objects: list[str] | None = None
    """Restrict to reviews containing at least one of these object types."""

    triggers: list[Trigger] | None = None
    """Semantic triggers: ``"start"`` fires on the first matching message,
    ``"best"`` fires once at review end with the best event.
    ``None`` matches on every MQTT message (new, update, end)."""

    alerts_only: bool = False
    """When ``True``, skip detection-severity reviews and only handle alerts."""

    zones: list[str] | None = None
    """Restrict to reviews that include at least one of these zones."""

    weekdays: list[Weekday] | None = None
    """Restrict to reviews starting on these days of the week.
    0 is Monday, 6 is Sunday.
    """

    time_range: tuple[time, time] | None = None
    """Restrict to reviews whose start time falls within this range.

    The tuple is ``(start, end)`` as :class:`datetime.time` objects.
    When *start* > *end* the range wraps midnight, e.g. ``(time(22, 0), time(6, 0))``
    matches 22:00-06:00.
    """

    def matches(self, review: FrigateReview, *, trigger: str | None = None) -> bool:
        """Return ``True`` if *review* satisfies every configured criterion.

        Parameters
        ----------
        trigger:
            When dispatching via the trigger system, pass ``"start"`` or
            ``"best"``.  Filters with :attr:`triggers` set will only match
            when this value is in their trigger list.
        """
        if self.cameras and review.camera not in self.cameras:
            return False
        if self.labels:
            try:
                if review.best_event.label not in self.labels:
                    return False
            except RuntimeError:
                return False
        if self.objects and not set(review.objects).intersection(self.objects):
            return False
        if self.triggers is not None:
            if trigger is None or trigger not in self.triggers:
                return False
        if self.alerts_only and not review.is_alert:
            return False
        if self.zones and not set(review.zones).intersection(self.zones):
            return False
        if (
            self.weekdays is not None
            and datetime.fromtimestamp(review.start_ts).weekday() not in self.weekdays
        ):
            return False
        if self.time_range is not None:
            t = datetime.fromtimestamp(review.start_ts).time()
            start, end = self.time_range
            inside = (start <= t < end) if start <= end else (t >= start or t < end)
            if not inside:
                return False
        return True
