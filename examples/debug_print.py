"""Print every review with a simple template, plus the raw MQTT payload."""

import json

import trio

from frigate_monitoring.actions.callback import CallbackAction
from frigate_monitoring.actions.print_action import PrintAction
from frigate_monitoring.config import Config, init
from frigate_monitoring.listener import FrigateListener
from frigate_monitoring.review import FrigateReview


async def print_raw(review: FrigateReview) -> None:
    """Dump the raw MQTT payload as formatted JSON."""
    print(json.dumps(review.raw, indent=2, default=str))


def main() -> None:
    """Run the listener and print review summaries and raw payloads."""
    init(Config.from_env())
    listener = FrigateListener()
    listener.add_action(PrintAction("[{camera}] {review_type}: {objects} — {severity}"))
    listener.add_action(CallbackAction(print_raw))
    trio.run(listener.run)


if __name__ == "__main__":
    main()
