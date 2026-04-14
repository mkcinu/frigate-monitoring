"""SlackAction: send Slack messages for Frigate reviews."""

from __future__ import annotations

from typing import Any

import attrs
import httpx

from frigate_monitoring.actions.base import Action, render_template
from frigate_monitoring.review import FrigateReview

_CHAT_POST_URL = "https://slack.com/api/chat.postMessage"
_FILES_GET_UPLOAD_URL = "https://slack.com/api/files.getUploadURLExternal"
_FILES_COMPLETE_URL = "https://slack.com/api/files.completeUploadExternal"


@attrs.define
class SlackAction(Action):
    """Send a Slack message for each matching Frigate review.

    Required environment variables
    ------------------------------
    Set these before running, then reference them in your YAML config::

        export SLACK_BOT_TOKEN=xoxb-...
        export SLACK_CHANNEL=C0123456789   # channel ID or "#channel-name"

    The bot token must have the following OAuth scopes:

    * ``chat:write``   — post messages
    * ``files:write``  — upload snapshot/GIF images (only when
      ``attach_snapshot`` or ``attach_gif`` is ``True``)

    .. note::
        ``channel`` must be a **channel ID** (e.g. ``C0123456789``), not a
        name like ``#alerts``.  ``chat.postMessage`` accepts names, but
        ``files.completeUploadExternal`` requires the ID.  Find it in Slack
        by clicking the channel name → *View channel details* → bottom of
        the *About* tab.

    YAML example::

        actions:
          - type: slack
            bot_token: ${SLACK_BOT_TOKEN}
            channel: ${SLACK_CHANNEL}   # must be a channel ID, e.g. C0123456789
            title: "Frigate alert on {{ camera }}"
            message: "{{ events | map(attribute='label') | join(', ') }} detected"
            attach_gif: true
            filter:
              alerts_only: true
              triggers: [best]

    All string fields are Jinja2 templates and support the same variables as
    :class:`~actions.print_action.PrintAction`.  The ``message`` field supports
    Slack *mrkdwn* formatting (``*bold*``, ``_italic_``, ``<url|text>`` links,
    etc.).

    When ``attach_snapshot`` and/or ``attach_gif`` are ``True``, files are
    uploaded via the Slack Files API (``files.getUploadURLExternal`` → upload →
    ``files.completeUploadExternal``).  With ``attach_snapshot``, one image is
    uploaded per event that has a snapshot available.  Both can be enabled at
    once; they are posted together as a multi-file message with ``message`` as
    the caption.  When neither is enabled, a Block Kit message with a header
    and body section is sent instead.

    Parameters
    ----------
    bot_token:
        Slack bot token (``xoxb-…``).  Set ``SLACK_BOT_TOKEN`` in the
        environment and reference it as ``${SLACK_BOT_TOKEN}`` in YAML.
    channel:
        Slack channel ID (e.g. ``C0123456789``).  Must be an ID, not a
        name — ``files.completeUploadExternal`` rejects names.
        Set ``SLACK_CHANNEL`` in the environment and reference it as
        ``${SLACK_CHANNEL}`` in YAML.
    title:
        Notification title template.
    message:
        Notification body template.  Supports Slack *mrkdwn* formatting.
    attach_snapshot:
        When ``True``, upload the cropped snapshot for each event that has
        one available.
    attach_gif:
        When ``True``, fetch and upload the review-level animated GIF.
    username:
        Override the bot display name for this message.
    icon_emoji:
        Override the bot icon with an emoji, e.g. ``":camera:"``.
    """

    bot_token: str
    channel: str
    title: str = "Frigate alert on {{ camera }}"
    message: str = "{{ events | map(attribute='label') | join(', ') }} detected"
    attach_snapshot: bool = True
    attach_gif: bool = False
    username: str = ""
    icon_emoji: str = ""

    async def handle(self, review: FrigateReview) -> None:
        """Send the Slack notification."""
        tpl_vars = review.as_template_vars()
        title_text = render_template(self.title, tpl_vars)
        message_text = render_template(self.message, tpl_vars)

        headers = {"Authorization": f"Bearer {self.bot_token}"}

        async with httpx.AsyncClient() as client:
            if self.attach_snapshot or self.attach_gif:
                await self._post_with_files(
                    client, headers, title_text, message_text, review
                )
            else:
                await self._post_blocks(client, headers, title_text, message_text)

    async def _post_blocks(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        title: str,
        message: str,
    ) -> None:
        payload: dict[str, Any] = {
            "channel": self.channel,
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": title, "emoji": True},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                },
            ],
        }
        if self.username:
            payload["username"] = self.username
        if self.icon_emoji:
            payload["icon_emoji"] = self.icon_emoji

        resp = await client.post(_CHAT_POST_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack chat.postMessage error: {data.get('error')}")

    async def _upload_file(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        content: bytes,
        filename: str,
        content_type: str,
        alt_txt: str = "",
    ) -> str:
        """Upload a file via the Slack Files API and return its file ID."""
        get_url_payload: dict[str, Any] = {
            "filename": filename,
            "length": len(content),
        }
        if alt_txt:
            get_url_payload["alt_txt"] = alt_txt

        url_resp = await client.post(
            _FILES_GET_UPLOAD_URL,
            headers=headers,
            data=get_url_payload,
        )
        url_resp.raise_for_status()
        url_data = url_resp.json()
        if not url_data.get("ok"):
            raise RuntimeError(
                f"Slack files.getUploadURLExternal error: {url_data.get('error')}"
            )

        upload_resp = await client.post(
            url_data["upload_url"],
            files={
                "filename": (None, filename),
                "file": (filename, content, content_type),
            },
            timeout=30.0,
        )
        upload_resp.raise_for_status()

        return str(url_data["file_id"])

    async def _post_with_files(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        title: str,
        message: str,
        review: FrigateReview,
    ) -> None:
        file_entries: list[dict[str, str]] = []

        if self.attach_snapshot:
            for ev in review.events:
                if ev.snapshot_bytes is None:
                    continue
                alt = f"{ev.label} snapshot"
                fid = await self._upload_file(
                    client,
                    headers,
                    ev.snapshot_bytes,
                    f"snapshot_{ev.event_id}.jpg",
                    "image/jpeg",
                    alt,
                )
                file_entries.append({"id": fid, "title": alt})

        if self.attach_gif:
            resp = await client.get(review.gif_url, timeout=30.0)
            resp.raise_for_status()
            fid = await self._upload_file(
                client, headers, resp.content, "review.gif", "image/gif", title
            )
            file_entries.append({"id": fid, "title": title})

        if not file_entries:
            await self._post_blocks(client, headers, title, message)
            return

        complete_payload: dict[str, Any] = {
            "files": file_entries,
            "channel_id": self.channel,
            "initial_comment": message,
        }
        complete_resp = await client.post(
            _FILES_COMPLETE_URL,
            headers=headers,
            json=complete_payload,
        )
        complete_resp.raise_for_status()
        complete_data = complete_resp.json()
        if not complete_data.get("ok"):
            raise RuntimeError(
                f"Slack files.completeUploadExternal error: {complete_data.get('error')}"
            )
