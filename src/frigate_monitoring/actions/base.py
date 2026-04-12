"""Action base class."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from jinja2 import Environment

from frigate_monitoring.review import FrigateReview

log = logging.getLogger(__name__)

DEFAULT_TEMPLATE = (
    "[{{ camera }}] {{ review_type }}: {{ objects | join(', ') }}"
    " ({{ score_pct }}) — {{ severity }}"
)

_env = Environment()


def render_template(template: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 template string against the given variable dict."""
    return _env.from_string(template).render(context)


class Action(ABC):
    """Base class for Frigate review handlers.

    Subclass this and implement :meth:`handle` to react to reviews.
    Override :meth:`on_error` to customise error handling.
    """

    @abstractmethod
    async def handle(self, review: FrigateReview) -> None:
        """React to a Frigate review.  Must be implemented by subclasses."""

    async def on_error(self, review: FrigateReview, exc: Exception) -> None:
        """Log an error when :meth:`handle` raises.  Override for custom behaviour."""
        log.error(
            "Action %s raised %s for review %s: %s",
            type(self).__name__,
            type(exc).__name__,
            review.review_id,
            exc,
        )
