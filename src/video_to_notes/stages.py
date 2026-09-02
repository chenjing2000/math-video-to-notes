from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class StageContext:
    stage: str
    workspace_root: Path
    config: dict[str, Any]
    logger: logging.Logger
