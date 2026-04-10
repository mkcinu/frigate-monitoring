"""ReviewFilter: predicate for selecting which reviews an action receives."""

from __future__ import annotations

from datetime import datetime, time

import attrs

from frigate_monitoring.review import FrigateReview
from frigate_monitoring.types import ReviewType


@attrs.define
class ReviewFilter:
    """Determines which reviews an :class:`~actions.Action` handler should receive.

    All specified criteria must match (AND logic).  Leave a field as its default
    to match any value for that dimension.

    Examples
    --------
    Only alert reviews from the front or back door::

        ReviewFilter(
            cameras=["front_door", "back_door"],
            alerts_only=True,
        )

    Any completed review that includes a person::

        ReviewFilter(review_types=["end"], objects=["person"])

    Only reviews that start during nighttime hours (wraps midnight)::

        ReviewFilter(time_range=(time(22, 0), time(6, 0)))
    """

    cameras: list[str] | None = None
    """Restrict to these camera names.  ``None`` matches any camera."""

    objects: list[str] | None = None
    """Restrict to reviews containing at least one of these object types."""

    review_types: list[ReviewType] | None = None
    """Restrict to these review lifecycle stages."""

    alerts_only: bool = False
    """When ``True``, skip detection-severity reviews and only handle alerts."""

    zones: list[str] | None = None
    """Restrict to reviews that include at least one of these zones."""

    time_range: tuple[time, time] | None = None
    """Restrict to reviews whose start time falls within this range.

    The tuple is ``(start, end)`` as :class:`datetime.time` objects.
    When *start* > *end* the range wraps midnight, e.g. ``(time(22, 0), time(6, 0))``
    matches 22:00-06:00.
    """

    def matches(self, review: FrigateReview) -> bool:
        """Return ``True`` if *review* satisfies every configured criterion."""
        if self.cameras and review.camera not in self.cameras:
            return False
        if self.objects and not set(review.objects).intersection(self.objects):
            return False
        if self.review_types and review.review_type not in self.review_types:
            return False
        if self.alerts_only and not review.is_alert:
            return False
        if self.zones and not set(review.zones).intersection(self.zones):
            return False
        if self.time_range is not None:
            t = datetime.fromtimestamp(review.start_ts).time()
            start, end = self.time_range
            inside = (start <= t < end) if start <= end else (t >= start or t < end)
            if not inside:
                return False
        return True
