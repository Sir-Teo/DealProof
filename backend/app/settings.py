from __future__ import annotations

import os
from pathlib import Path

from .models import AppSettings

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("DEALPROOF_DATA_DIR", str(ROOT / "data")))
SETTINGS_PATH = DATA_DIR / "settings.json"


def get_app_settings() -> AppSettings:
    if not SETTINGS_PATH.exists():
        return AppSettings()
    try:
        return AppSettings.model_validate_json(SETTINGS_PATH.read_text())
    except Exception:
        return AppSettings()


def save_app_settings(settings: AppSettings) -> AppSettings:
    validated = AppSettings.model_validate(settings.model_dump())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(validated.model_dump_json(indent=2))
    return validated
