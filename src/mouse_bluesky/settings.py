from __future__ import annotations

import os
from pathlib import Path

import attrs


@attrs.frozen(slots=True)
class Settings:
    """Holds default filesystem roots used by planning and CLI commands."""
    root_path: Path
    config_root: Path

    @classmethod
    def from_env(cls, *, root_default: str = "/data/mouse", config_default: str = "/data/mouse_configs") -> "Settings":
        """Build settings from environment variables with fallback defaults."""
        root = Path(os.environ.get("MOUSE_DATA_ROOT", root_default)).expanduser()
        cfg = Path(os.environ.get("MOUSE_CONFIG_ROOT", config_default)).expanduser()
        return cls(root_path=root, config_root=cfg)
