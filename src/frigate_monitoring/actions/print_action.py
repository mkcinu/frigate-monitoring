"""PrintAction: print a formatted line to stdout for each matching review."""

from __future__ import annotations

from typing import ClassVar

import attrs

from frigate_monitoring.actions.base import DEFAULT_TEMPLATE, Action
from frigate_monitoring.review import FrigateReview


@attrs.define
class PrintAction(Action):
    """Print a formatted line to stdout for each matching review.

    Parameters
    ----------
    template:
        A Python format string using the variables listed in
        :mod:`review` module docstring.
        Example: ``"[{camera}] {severity}: {objects} — {score_pct}"``
    """

    DEFAULT_TEMPLATE: ClassVar[str] = DEFAULT_TEMPLATE

    template: str = DEFAULT_TEMPLATE

    async def handle(self, review: FrigateReview) -> None:
        """Print the rendered template to stdout."""
        try:
            msg = self.template.format_map(review.as_template_vars())
        except KeyError as exc:
            msg = f"[template error: unknown variable {exc}] raw: {review}"
        print(msg)
