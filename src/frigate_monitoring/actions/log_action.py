"""LogAction: emit a log record for each matching review."""

from __future__ import annotations

import logging

import attrs

from frigate_monitoring.actions.base import DEFAULT_TEMPLATE, Action, render_template
from frigate_monitoring.review import FrigateReview


def _parse_log_level(val: int | str) -> int:
    if isinstance(val, str):
        return getattr(logging, val.upper(), logging.INFO)
    return val


@attrs.define
class LogAction(Action):
    """Emit a log record for each matching review.

    Parameters
    ----------
    template:
        A Python format string using the variables listed in
        :mod:`review` module docstring.
    level:
        Python logging level — either an int or a string like ``"INFO"``.
    """

    template: str = DEFAULT_TEMPLATE
    # Annotated as ``int | str`` so cattrs will pass YAML strings like "INFO"
    # through to attrs, where the converter normalizes them to an int.
    level: int | str = attrs.field(default=logging.INFO, converter=_parse_log_level)

    async def handle(self, review: FrigateReview) -> None:
        """Emit the rendered template as a log record."""
        log = logging.getLogger(__name__)
        msg = render_template(self.template, review.as_template_vars())
        log.log(self.level, msg)  # type: ignore[arg-type]
