import os
import tempfile
from pathlib import Path

import pytest

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="dealproof-test-data-"))
os.environ["DEALPROOF_DATA_DIR"] = str(TEST_DATA_DIR)


@pytest.fixture(autouse=True)
def isolate_local_side_effects(monkeypatch):
    from app import db
    from app import settings as app_settings

    monkeypatch.setattr(db, "DATA_DIR", TEST_DATA_DIR)
    monkeypatch.setattr(db, "DB_PATH", TEST_DATA_DIR / db.DATABASE_FILENAME)
    monkeypatch.setattr(app_settings, "DATA_DIR", TEST_DATA_DIR)
    monkeypatch.setattr(app_settings, "SETTINGS_PATH", TEST_DATA_DIR / "settings.json")
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in TEST_DATA_DIR.glob(f"{db.DATABASE_FILENAME}*"):
        path.unlink(missing_ok=True)
    (TEST_DATA_DIR / "settings.json").unlink(missing_ok=True)
    db.init_db()
    monkeypatch.setattr("app.graph.collect_public_web_evidence", lambda company, profile, claims, on_progress=None, **kwargs: [])
