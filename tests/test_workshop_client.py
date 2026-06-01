"""Steam Workshop metadata boundary tests."""

import asyncio

import httpx
import pytest

from cs2webui.modules.builtin.workshop import SteamWorkshopClient


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"response": {"publishedfiledetails": []}}


class _FakeAsyncClient:
    def __init__(self, **_kwargs: object) -> None:
        return None

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, *_args: object, **_kwargs: object) -> _FakeResponse:
        return _FakeResponse()


def test_fetch_rejects_invalid_workshop_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    with pytest.raises(ValueError, match="Workshop map response is invalid"):
        asyncio.run(SteamWorkshopClient().fetch("3070290869"))
