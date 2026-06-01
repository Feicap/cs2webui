"""Host diagnostics used by the first-run wizard."""

from dataclasses import asdict, dataclass, field
import platform
import shutil
import socket
import subprocess
import sys
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PortStatus:
    port: int
    available: bool
    process: str | None = None


@dataclass(frozen=True, slots=True)
class HostReport:
    operating_system: str
    firewall: str | None
    ports: tuple[PortStatus, ...]
    firewall_rules: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "operating_system": self.operating_system,
            "firewall": self.firewall,
            "firewall_rules": list(self.firewall_rules),
            "ports": [asdict(port) for port in self.ports],
            "suggested_port": next(
                (port.port for port in self.ports if port.available), None
            ),
        }


class SystemDiagnostics(Protocol):
    def inspect(self, start_port: int, count: int) -> HostReport:
        """Return a non-mutating report for the requested TCP ports."""

    def inspect_udp(self, start_port: int, count: int) -> HostReport:
        """Return a non-mutating report for the requested UDP ports."""


class PortableDiagnostics:
    """Portable fallback used for development and basic availability checks."""

    def inspect(self, start_port: int, count: int) -> HostReport:
        ports = tuple(
            PortStatus(port=port, available=self._is_available(port, socket.SOCK_STREAM))
            for port in range(start_port, start_port + count)
        )
        return HostReport(
            operating_system=platform.platform(),
            firewall=None,
            ports=ports,
        )

    def inspect_udp(self, start_port: int, count: int) -> HostReport:
        ports = tuple(
            PortStatus(port=port, available=self._is_available(port, socket.SOCK_DGRAM))
            for port in range(start_port, start_port + count)
        )
        return HostReport(
            operating_system=platform.platform(),
            firewall=None,
            ports=ports,
        )

    @staticmethod
    def _is_available(port: int, socket_type: int) -> bool:
        with socket.socket(socket.AF_INET, socket_type) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                server.bind(("0.0.0.0", port))
            except OSError:
                return False
        return True


class LinuxDiagnostics(PortableDiagnostics):
    """Linux implementation with best-effort process and firewall discovery."""

    def inspect(self, start_port: int, count: int) -> HostReport:
        report = super().inspect(start_port, count)
        listeners = self._listeners()
        firewall, firewall_rules = self._firewall_report()
        ports = tuple(
            PortStatus(
                port=port.port,
                available=port.available,
                process=listeners.get(port.port),
            )
            for port in report.ports
        )
        return HostReport(
            operating_system=report.operating_system,
            firewall=firewall,
            ports=ports,
            firewall_rules=firewall_rules,
        )

    def inspect_udp(self, start_port: int, count: int) -> HostReport:
        report = super().inspect_udp(start_port, count)
        firewall, firewall_rules = self._firewall_report()
        return HostReport(
            operating_system=report.operating_system,
            firewall=firewall,
            ports=report.ports,
            firewall_rules=firewall_rules,
        )

    @staticmethod
    def _listeners() -> dict[int, str]:
        if not shutil.which("ss"):
            return {}
        result = subprocess.run(
            ["ss", "-H", "-ltnp"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        listeners: dict[int, str] = {}
        for line in result.stdout.splitlines():
            columns = line.split()
            if len(columns) < 4:
                continue
            address = columns[3]
            _, separator, raw_port = address.rpartition(":")
            if not separator or not raw_port.isdigit():
                continue
            listeners[int(raw_port)] = " ".join(columns[5:]) or "unknown"
        return listeners

    @staticmethod
    def _firewall_report() -> tuple[str | None, tuple[str, ...]]:
        commands = (
            ("ufw", ["ufw", "status"]),
            ("firewall-cmd", ["firewall-cmd", "--list-all"]),
            ("nft", ["nft", "list", "ruleset"]),
        )
        for name, arguments in commands:
            if not shutil.which(name):
                continue
            try:
                result = subprocess.run(
                    arguments,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            except (OSError, subprocess.TimeoutExpired):
                return name, ()
            rules = tuple(
                line for line in result.stdout[-12000:].splitlines() if line.strip()
            )
            return name, rules
        return None, ()


def default_diagnostics() -> SystemDiagnostics:
    if sys.platform.startswith("linux"):
        return LinuxDiagnostics()
    return PortableDiagnostics()
