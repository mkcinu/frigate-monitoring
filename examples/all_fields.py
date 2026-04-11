"""Print every field available in a FrigateReview, once per completed review.

Note: as_template_vars() fetches the best event from the Frigate HTTP API
on first access, so Frigate must be reachable when this runs.
"""

import trio

from frigate_monitoring.actions.callback import CallbackAction
from frigate_monitoring.config import Config, init
from frigate_monitoring.filter import ReviewFilter
from frigate_monitoring.listener import FrigateListener
from frigate_monitoring.review import FrigateReview


async def print_all_fields(review: FrigateReview) -> None:
    """Print all template variables for the review."""
    print(f"\n{'─' * 40}")
    for key, value in review.as_template_vars().items():
        print(f"  {key:<24} {value}")


def main() -> None:
    """Run the listener and print all fields for each completed review."""
    init(Config.from_env())
    listener = FrigateListener()
    listener.add_action(
        CallbackAction(print_all_fields),
        filter=ReviewFilter(triggers=["best"]),
    )
    trio.run(listener.run)


if __name__ == "__main__":
    main()
