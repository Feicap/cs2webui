"""Minimal Source RCON TCP client used by core console operations."""

from dataclasses import dataclass
import socket
import struct

SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0


class RconError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RconResponse:
    body: str


class RconClient:
    """Execute one authenticated command per TCP connection."""

    def execute(self, host: str, port: int, password: str, command: str) -> RconResponse:
        with socket.create_connection((host, port), timeout=5) as connection:
            connection.settimeout(5)
            self._send(connection, 1, SERVERDATA_AUTH, password)
            request_id, response_type, _ = self._receive(connection)
            if response_type == SERVERDATA_RESPONSE_VALUE and request_id == 1:
                request_id, response_type, _ = self._receive(connection)
            if request_id == -1 or response_type != SERVERDATA_AUTH_RESPONSE:
                raise RconError("RCON authentication failed")
            self._send(connection, 2, SERVERDATA_EXECCOMMAND, command)
            self._send(connection, 3, SERVERDATA_RESPONSE_VALUE, "")
            parts = []
            while True:
                request_id, response_type, body = self._receive(connection)
                if request_id == 3 and response_type == SERVERDATA_RESPONSE_VALUE:
                    break
                if request_id != 2 or response_type != SERVERDATA_RESPONSE_VALUE:
                    raise RconError("Unexpected RCON response")
                parts.append(body)
            return RconResponse(body="".join(parts))

    @staticmethod
    def _send(connection: socket.socket, request_id: int, kind: int, body: str) -> None:
        payload = struct.pack("<ii", request_id, kind) + body.encode() + b"\x00\x00"
        connection.sendall(struct.pack("<i", len(payload)) + payload)

    @staticmethod
    def _receive(connection: socket.socket) -> tuple[int, int, str]:
        size = struct.unpack("<i", RconClient._read_exact(connection, 4))[0]
        if size < 10 or size > 4 * 1024 * 1024:
            raise RconError("Invalid RCON packet size")
        packet = RconClient._read_exact(connection, size)
        request_id, kind = struct.unpack("<ii", packet[:8])
        return request_id, kind, packet[8:-2].decode(errors="replace")

    @staticmethod
    def _read_exact(connection: socket.socket, size: int) -> bytes:
        chunks = []
        remaining = size
        while remaining:
            chunk = connection.recv(remaining)
            if not chunk:
                raise RconError("RCON connection closed unexpectedly")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
