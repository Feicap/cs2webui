"""Best-effort host metrics for the optional dashboard."""

from dataclasses import asdict, dataclass
from pathlib import Path
import os
import shutil


@dataclass(frozen=True, slots=True)
class HostMetrics:
    disk_total_bytes: int
    disk_free_bytes: int
    memory_total_bytes: int | None
    memory_available_bytes: int | None
    load_average_1m: float | None

    def as_dict(self) -> dict[str, int | float | None]:
        return asdict(self)


class MetricsClient:
    def __init__(self, data_path: Path) -> None:
        self._data_path = data_path

    def read(self) -> HostMetrics:
        disk = shutil.disk_usage(self._data_path)
        memory = self._linux_memory()
        try:
            load_average = os.getloadavg()[0]
        except (AttributeError, OSError):
            load_average = None
        return HostMetrics(
            disk_total_bytes=disk.total,
            disk_free_bytes=disk.free,
            memory_total_bytes=memory.get("MemTotal"),
            memory_available_bytes=memory.get("MemAvailable"),
            load_average_1m=load_average,
        )

    @staticmethod
    def _linux_memory() -> dict[str, int]:
        meminfo = Path("/proc/meminfo")
        if not meminfo.is_file():
            return {}
        values = {}
        for line in meminfo.read_text().splitlines():
            key, _, value = line.partition(":")
            raw_kib = value.strip().split()[0]
            if raw_kib.isdigit():
                values[key] = int(raw_kib) * 1024
        return values
