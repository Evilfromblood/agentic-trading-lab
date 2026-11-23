"""User-controlled paper trading kill switch evaluating environment variables and sentinel files."""
from __future__ import annotations

import os
from pathlib import Path


class KillSwitchError(RuntimeError):
    """Raised when an operation is attempted while the trading desk kill switch is active."""


class KillSwitch:
    """Deterministic, user-controlled kill switch halting desk execution immediately."""

    def __init__(
        self,
        env_var: str = "TRADING_DESK_STOP",
        stop_file: Path | str = Path("STOP"),
    ) -> None:
        if not isinstance(env_var, str) or not env_var.strip():
            raise ValueError("env_var must be a non-empty string")
        self.env_var = env_var.strip()
        self.stop_file = Path(stop_file)

    def is_active(self) -> bool:
        try:
            env_val = os.environ.get(self.env_var, "").strip().upper()
            if env_val in {"1", "TRUE", "YES", "ON"}:
                return True
        except (KeyError, TypeError):
            return True
        try:
            if self.stop_file.exists():
                return True
        except OSError:
            return True
        return False

    def reason(self) -> str | None:
        try:
            env_val = os.environ.get(self.env_var, "").strip().upper()
            if env_val in {"1", "TRUE", "YES", "ON"}:
                return f"Environment variable {self.env_var}={env_val} is active"
        except (KeyError, TypeError):
            return f"Environment variable {self.env_var} check failed (failing closed)"
        try:
            if self.stop_file.exists():
                return f"Stop file {self.stop_file} exists"
        except OSError:
            return f"Stop file {self.stop_file} inaccessible (failing closed)"
        return None

    def assert_clear(self) -> None:
        if self.is_active():
            raise KillSwitchError(self.reason() or "Trading desk kill switch is active")
