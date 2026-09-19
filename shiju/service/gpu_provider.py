from __future__ import annotations

from typing import Protocol


class GpuProvider(Protocol):
    def ensure_running(self) -> bool: ...

    def status(self) -> str: ...

    def request_stop(self) -> bool: ...


class ManualGpuProvider:
    """MVP provider: lifecycle is operated outside the application."""

    def ensure_running(self) -> bool:
        return False

    def status(self) -> str:
        return "manual"

    def request_stop(self) -> bool:
        return False

