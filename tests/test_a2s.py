"""Valve A2S_INFO protocol regression tests."""

import socket
import struct

import pytest

from cs2webui.host.a2s import A2S_INFO_REQUEST, A2sClient, A2sError


def _info_packet() -> bytes:
    return (
        b"\xff\xff\xff\xffI"
        b"\x11"
        b"CS2 Test Server\x00"
        b"de_mirage\x00"
        b"csgo\x00"
        b"Counter-Strike 2\x00"
        + struct.pack("<H", 730)
        + bytes((5, 16, 1, ord("d"), ord("l"), 0, 1))
        + b"1.0.0\x00"
    )


class _FakeSocket:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = responses
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def __enter__(self) -> "_FakeSocket":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def settimeout(self, _timeout: int) -> None:
        return None

    def sendto(self, payload: bytes, address: tuple[str, int]) -> None:
        self.sent.append((payload, address))

    def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
        return self.responses.pop(0), ("127.0.0.1", 27015)


def test_query_info_repeats_request_with_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    challenge = b"\x01\x02\x03\x04"
    fake_socket = _FakeSocket([b"\xff\xff\xff\xffA" + challenge, _info_packet()])
    monkeypatch.setattr(socket, "socket", lambda *_args: fake_socket)

    info = A2sClient().query_info("127.0.0.1", 27015)

    assert info.name == "CS2 Test Server"
    assert info.map_name == "de_mirage"
    assert info.players == 5
    assert info.max_players == 16
    assert info.bots == 1
    assert fake_socket.sent == [
        (A2S_INFO_REQUEST, ("127.0.0.1", 27015)),
        (A2S_INFO_REQUEST + challenge, ("127.0.0.1", 27015)),
    ]


def test_query_info_rejects_truncated_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_socket = _FakeSocket([b"\xff\xff\xff\xffA\x01"])
    monkeypatch.setattr(socket, "socket", lambda *_args: fake_socket)

    with pytest.raises(A2sError, match="challenge is truncated"):
        A2sClient().query_info("127.0.0.1", 27015)
