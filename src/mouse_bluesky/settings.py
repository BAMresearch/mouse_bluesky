from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    root_path: Path
    config_root: Path

    @staticmethod
    def from_env(*, root_default: str = "/data/mouse", config_default: str = "/data/mouse_configs") -> "Settings":
        root = Path(os.environ.get("MOUSE_DATA_ROOT", root_default)).expanduser()
        cfg = Path(os.environ.get("MOUSE_CONFIG_ROOT", config_default)).expanduser()
        return Settings(root_path=root, config_root=cfg)
