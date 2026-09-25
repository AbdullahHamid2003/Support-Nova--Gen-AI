"""Repository paths. All data/config folders are resolved relative to the repository root."""

from __future__ import annotations

import os
from pathlib import Path

# backend/src/supportnova/core/paths.py -> repository root is four parents up.
_DEFAULT_ROOT = Path(__file__).resolve().parents[4]
REPO_ROOT = Path(os.environ.get("SUPPORTNOVA_ROOT", _DEFAULT_ROOT)).resolve()

CONFIG_DIR = REPO_ROOT / "config"
RULES_DIR = REPO_ROOT / "rules"
PROMPTS_DIR = REPO_ROOT / "prompts"
SCHEMAS_DIR = REPO_ROOT / "schemas"
KNOWLEDGE_BASE_DIR = REPO_ROOT / "knowledge_base"
DATA_DIR = REPO_ROOT / "data"
FRONTEND_DIST_DIR = REPO_ROOT / "frontend" / "dist"


def storage_dir() -> Path:
    """Directory for uploaded files (documents, attachments). Created on demand, never committed."""
    path = Path(os.environ.get("STORAGE_DIR", REPO_ROOT / "storage")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
