"""Test fixtures. Every test gets its OWN empty storage folder, so tests never touch real data."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

RESULTS = []  # collected for the final test report


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Fresh storage root + freshly created database."""
    monkeypatch.setenv("MSES_STORAGE_ROOT", str(tmp_path / "store"))
    for var in ("MSES_DATA_DIR", "MSES_DB_PATH", "MSES_UPLOADS_DIR", "MSES_CERTIFICATES_DIR", "MSES_BACKUPS_DIR",
                "MSES_ASSETS_DIR", "MSES_LOGS_DIR", "MSES_SETUP_CODE", "MSES_PUBLIC_URL", "MSES_DB_TIMEOUT_MS"):
        monkeypatch.delenv(var, raising=False)
    import database
    database.init_db()
    from services import backup_service
    backup_service._last_auto_check = 0.0
    return tmp_path / "store"


@pytest.fixture()
def school(env):
    from helpers import build_school
    return build_school()


def pytest_runtest_makereport(item, call):
    if call.when != "call" and not (call.when == "setup" and call.excinfo):
        return
    doc = (item.function.__doc__ or "").strip() if hasattr(item, "function") else ""
    parts = [p.strip() for p in doc.split("|")]
    outcome = "PASS" if call.excinfo is None else ("SKIP" if call.excinfo.typename == "Skipped" else "FAIL")
    case_id = parts[0] if parts and parts[0] else item.name
    if "[" in item.name:
        case_id += item.name[item.name.index("["):]
    RESULTS.append({
        "id": case_id,
        "description": parts[1] if len(parts) > 1 else item.name,
        "expected": parts[2] if len(parts) > 2 else "Behaves as described",
        "outcome": outcome,
        "actual": ("As expected" if outcome == "PASS" else
                   (str(call.excinfo.value)[:300].replace("\n", " ") if call.excinfo else "")),
        "node": item.nodeid,
    })


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("MSES_RESULTS_JSON")
    if out and RESULTS:
        path = Path(out)
        existing = json.loads(path.read_text()) if path.exists() else []
        path.write_text(json.dumps(existing + RESULTS, indent=1))
