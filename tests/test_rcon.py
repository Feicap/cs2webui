"""Source RCON protocol regression tests."""

import socket
import struct

import pytest

from cs2webui.host.rcon import (
    RconClient,
    SERVERDATA_AUTH_RESPONSE,
    SERVERDATA_RESPONSE_VALUE,
)


def _packet(request_id: int, kind: int, body: str) -> bytes:
    payload = struct.pack("<ii", request_id, kind) + body.encode() + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


class _FakeConnection:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent: list[bytes] = []

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def settimeout(self, _timeout: int) -> None:
        return None

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def recv(self, size: int) -> bytes:
        chunk, self.response = self.response[:size], self.response[size:]
        return chunk


def test_execute_joins_multipacket_response(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _FakeConnection(
        _packet(1, SERVERDATA_RESPONSE_VALUE, "")
        + _packet(1, SERVERDATA_AUTH_RESPONSE, "")
        + _packet(2, SERVERDATA_RESPONSE_VALUE, "first ")
        + _packet(2, SERVERDATA_RESPONSE_VALUE, "second")
        + _packet(3, SERVERDATA_RESPONSE_VALUE, "")
    )
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: connection)

    response = RconClient().execute("127.0.0.1", 27015, "password", "status")

    assert response.body == "first second"
    assert len(connection.sent) == 3
    assert struct.unpack("<ii", connection.sent[2][4:12]) == (
        3,
        SERVERDATA_RESPONSE_VALUE,
    )
