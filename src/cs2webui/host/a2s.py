"""Valve A2S_INFO UDP query client."""

from dataclasses import asdict, dataclass
import socket
import struct

A2S_INFO_REQUEST = b"\xff\xff\xff\xffTSource Engine Query\x00"


class A2sError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ServerInfo:
    name: str
    map_name: str
    players: int
    max_players: int
    bots: int
    version: str

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


class A2sClient:
    def query_info(self, host: str, port: int) -> ServerInfo:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(2)
            client.sendto(A2S_INFO_REQUEST, (host, port))
            packet, _ = client.recvfrom(65535)
            if packet.startswith(b"\xff\xff\xff\xffA"):
                if len(packet) < 9:
                    raise A2sError("A2S_INFO challenge is truncated")
                client.sendto(A2S_INFO_REQUEST + packet[5:9], (host, port))
                packet, _ = client.recvfrom(65535)
        if not packet.startswith(b"\xff\xff\xff\xffI"):
            raise A2sError("Unexpected A2S_INFO response")
        return self._parse_info(packet[5:])

    @staticmethod
    def _parse_info(payload: bytes) -> ServerInfo:
        if not payload:
            raise A2sError("A2S_INFO response is empty")
        offset = 1  # protocol version
        name, offset = A2sClient._read_string(payload, offset)
        map_name, offset = A2sClient._read_string(payload, offset)
        _, offset = A2sClient._read_string(payload, offset)  # folder
        _, offset = A2sClient._read_string(payload, offset)  # game
        if len(payload) < offset + 8:
            raise A2sError("A2S_INFO response is truncated")
        offset += 2  # app id
        players, max_players, bots = struct.unpack_from("<BBB", payload, offset)
        offset += 6  # players, slots, bots, type, environment, visibility
        offset += 1  # VAC
        version, _ = A2sClient._read_string(payload, offset)
        return ServerInfo(
            name=name,
            map_name=map_name,
            players=players,
            max_players=max_players,
            bots=bots,
            version=version,
        )

    @staticmethod
    def _read_string(payload: bytes, offset: int) -> tuple[str, int]:
        end = payload.find(b"\x00", offset)
        if end == -1:
            raise A2sError("A2S_INFO string is truncated")
        return payload[offset:end].decode(errors="replace"), end + 1
