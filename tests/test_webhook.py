"""Tests for WebhookAction."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.conftest import make_payload

from frigate_monitoring.actions.webhook import WebhookAction
from frigate_monitoring.event import FrigateEvent
from frigate_monitoring.review import FrigateReview


def _review_with_event(event: FrigateEvent) -> FrigateReview:
    review = FrigateReview.from_payload(make_payload())
    review.events = [event]
    return review


def _make_mock_client(status_code: int = 200) -> tuple[AsyncMock, MagicMock]:
    """Return (mock_httpx_client_instance, mock_response)."""
    mock_response = MagicMock(status_code=status_code)
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    return mock_client, mock_response


@pytest.mark.trio
async def test_sends_post_with_template_vars(fake_event: FrigateEvent) -> None:
    mock_client, _ = _make_mock_client()
    with patch(
        "frigate_monitoring.actions.webhook.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        action = WebhookAction(
            url="https://example.com/hook",
            body={
                "text": "{{ events[0].label }} on {{ camera }}",
                "cam": "{{ camera }}",
            },
        )
        await action.handle(_review_with_event(fake_event))

    mock_client.request.assert_called_once()
    call_kwargs = mock_client.request.call_args
    assert call_kwargs.kwargs["method"] == "POST"
    assert call_kwargs.kwargs["url"] == "https://example.com/hook"
    body = json.loads(call_kwargs.kwargs["content"])
    assert body["text"] == "person on front_door"
    assert body["cam"] == "front_door"


@pytest.mark.trio
async def test_url_template_expansion(fake_event: FrigateEvent) -> None:
    mock_client, _ = _make_mock_client()
    with patch(
        "frigate_monitoring.actions.webhook.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        action = WebhookAction(url="https://example.com/{{ camera }}/alert")
        await action.handle(_review_with_event(fake_event))

    assert (
        mock_client.request.call_args.kwargs["url"]
        == "https://example.com/front_door/alert"
    )


@pytest.mark.trio
async def test_custom_method_and_headers(fake_event: FrigateEvent) -> None:
    mock_client, _ = _make_mock_client()
    with patch(
        "frigate_monitoring.actions.webhook.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        action = WebhookAction(
            url="https://example.com/hook",
            method="PUT",
            headers={"Authorization": "Bearer tok123"},
        )
        await action.handle(_review_with_event(fake_event))

    assert mock_client.request.call_args.kwargs["method"] == "PUT"
    assert (
        mock_client.request.call_args.kwargs["headers"]["Authorization"]
        == "Bearer tok123"
    )


@pytest.mark.trio
async def test_default_body_sends_all_vars(fake_event: FrigateEvent) -> None:
    mock_client, _ = _make_mock_client()
    with patch(
        "frigate_monitoring.actions.webhook.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        action = WebhookAction(url="https://example.com/hook")
        await action.handle(_review_with_event(fake_event))

    body = json.loads(mock_client.request.call_args.kwargs["content"])
    assert "camera" in body
    assert "events" in body
    assert body["camera"] == "front_door"
