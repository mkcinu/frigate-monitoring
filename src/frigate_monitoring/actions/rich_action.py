"""RichAction: live-updating rich terminal display for Frigate reviews."""

from __future__ import annotations

import atexit
import logging
import time
from collections import deque

import attrs
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from frigate_monitoring.actions.base import Action
from frigate_monitoring.review import FrigateReview

_OBJECT_ICON: dict[str, str] = {
    "person": "👤",
    "dog": "🐕",
    "cat": "🐈",
    "car": "🚗",
    "truck": "🚛",
    "bicycle": "🚲",
    "motorcycle": "🏍️",
    "bird": "🐦",
    "package": "📦",
    "face": "😶",
    "license_plate": "🔲",
}

_SEVERITY_STYLE: dict[str, str] = {
    "alert": "bold red",
    "detection": "cyan",
}

_LEVEL_STYLE: dict[str, str] = {
    "DEBUG": "dim",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "bold red",
    "CRITICAL": "bold red reverse",
}


class _LogCapture(logging.Handler):
    def __init__(self, maxlen: int = 200) -> None:
        super().__init__()
        self._lines: deque[Text] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        level = record.levelname
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        line = Text(overflow="fold")
        line.append(ts, style="dim")
        line.append(f" {level:<8}", style=_LEVEL_STYLE.get(level, ""))
        line.append(f" {record.name}: ", style="dim")
        line.append(record.getMessage())
        self._lines.append(line)

    def recent(self, n: int) -> list[Text]:
        return list(self._lines)[-n:]


@attrs.define
class RichAction(Action):
    """Live-updating rich terminal display for Frigate reviews with a log panel.

    Each review is rendered as its own card that tracks the review through its
    lifecycle and fades out after ``keep_ended_secs`` seconds once ended.

    Parameters
    ----------
    keep_ended_secs:
        How long ended reviews remain visible before being removed.
    log_lines:
        Number of log lines to show in the log panel.
    """

    keep_ended_secs: float = 8.0
    log_lines: int = 8

    console: Console = attrs.field(init=False, factory=Console)
    _log_handler: _LogCapture = attrs.field(
        init=False, factory=_LogCapture, alias="_log_handler"
    )
    _reviews: dict[str, FrigateReview] = attrs.field(
        init=False, factory=dict[str, FrigateReview], alias="_reviews"
    )
    _ended_at: dict[str, float] = attrs.field(
        init=False, factory=dict[str, float], alias="_ended_at"
    )
    _live: Live | None = attrs.field(default=None, init=False, alias="_live")

    async def handle(self, review: FrigateReview) -> None:
        if self._live is None:
            logging.getLogger().addHandler(self._log_handler)
            self._live = Live(
                self._render(),
                console=self.console,
                refresh_per_second=2,
            )
            self._live.start()
            atexit.register(self._stop)

        self._reviews[review.review_id] = review
        if review.review_type == "end":
            self._ended_at[review.review_id] = time.time()

        cutoff = time.time() - self.keep_ended_secs
        for rid in [r for r, t in self._ended_at.items() if t < cutoff]:
            self._reviews.pop(rid, None)
            self._ended_at.pop(rid, None)

        self._live.update(self._render())

    def _stop(self) -> None:
        if self._live is not None:
            self._live.stop()
        logging.getLogger().removeHandler(self._log_handler)

    def _render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(self._render_reviews(), name="reviews"),
            Layout(self._render_logs(), name="logs", size=self.log_lines + 2),
        )
        return layout

    def _render_reviews(self) -> Panel:
        active = [r for rid, r in self._reviews.items() if rid not in self._ended_at]
        ended = [r for rid, r in self._reviews.items() if rid in self._ended_at]

        active.sort(key=lambda r: r.start_ts, reverse=True)
        ended.sort(key=lambda r: self._ended_at[r.review_id], reverse=True)

        cards = [self._render_card(r) for r in (*active, *ended)]
        content: Group | Text = (
            Group(*cards)
            if cards
            else Text("Waiting for reviews…", style="dim", justify="center")
        )

        subtitle = f"{len(active)} active · {len(ended)} ended"
        return Panel(
            content,
            title="[bold]🎥 Frigate[/bold]",
            subtitle=subtitle,
            border_style="bright_blue",
        )

    def _render_card(self, review: FrigateReview) -> Panel:
        ended = review.review_id in self._ended_at
        is_alert = review.severity == "alert"

        title = Text()
        title.append(f"📷 {review.camera}", style="bold" if not ended else "dim")
        title.append("   ")
        sev_icon = "🚨" if is_alert else "👁️ "
        title.append(
            sev_icon + review.severity.upper(),
            style=_SEVERITY_STYLE.get(review.severity, "") if not ended else "dim",
        )
        title.append("   ")
        if ended:
            title.append("✅ ENDED", style="dim green")
        elif is_alert:
            title.append("🔴 ONGOING", style="bold red")
        else:
            title.append("🟡 ONGOING", style="bold yellow")

        body = Text(overflow="fold")

        try:
            be = review.best_event
            icon = _OBJECT_ICON.get(be.label, "📦")
            label_text = f"{icon} {be.label}"
            if be.sub_label:
                label_text += f" ({be.sub_label})"
            body.append(label_text, style="dim" if ended else "bold")
            body.append(f"  {be.score_pct}", style="dim" if ended else "green")
            if abs(be.top_score - be.score) > 0.005:
                body.append(f" · top {be.top_score_pct}", style="dim")
        except Exception:
            body.append("📦 …", style="dim")

        zones_str = ", ".join(review.zones) if review.zones else "—"
        body.append(f"   📍 {zones_str}", style="dim")
        body.append("\n")

        body.append("⏱  ", style="dim")
        body.append(review.start_time, style="dim")
        if ended and review.end_time:
            body.append(f" → {review.end_time}", style="dim")
        body.append(f"  ({review.duration:.0f}s)", style="dim")
        body.append("\n")

        try:
            be = review.best_event
            if be.has_clip:
                body.append("🎞  ", style="dim")
                body.append(be.gif_url, style="dim")
                body.append("\n")
                body.append("🎬  ", style="dim")
                body.append(be.clip_url, style="dim")
                body.append("\n")
        except Exception:
            pass

        border_style = "dim" if ended else ("red" if is_alert else "yellow")
        return Panel(body, title=title, border_style=border_style, padding=(0, 1))

    def _render_logs(self) -> Panel:
        lines = self._log_handler.recent(self.log_lines)
        content: Group | Text = (
            Group(*lines) if lines else Text("No logs yet.", style="dim")
        )
        return Panel(content, title="Logs", border_style="dim")
