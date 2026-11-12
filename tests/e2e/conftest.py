"""Browser tests: start the REAL Streamlit app as a separate process and drive it with Chromium."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "tests" / "_artifacts"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, storage: Path, extra_env: dict | None = None):
        self.storage = storage
        self.port = _free_port()
        self.extra_env = extra_env or {}
        self.proc: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        env = dict(os.environ, MSES_STORAGE_ROOT=str(self.storage), **self.extra_env)
        log = open(self.storage.parent / f"server_{self.port}.log", "ab")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(self.port),
             "--server.headless", "true", "--server.address", "127.0.0.1"],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if urllib.request.urlopen(f"{self.url}/_stcore/health", timeout=2).read() == b"ok":
                    return
            except Exception:
                time.sleep(0.4)
        raise RuntimeError("Streamlit did not start")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def restart(self) -> None:
        self.stop()
        self.start()


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    SHOTS.mkdir(exist_ok=True)
    pw = sync_playwright().start()
    b = pw.chromium.launch()
    yield b
    b.close()
    pw.stop()


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """A running app on a brand-new empty storage folder (module scoped)."""
    storage = tmp_path_factory.mktemp("e2e") / "store"
    mp = pytest.MonkeyPatch()
    mp.setenv("MSES_STORAGE_ROOT", str(storage))
    for var in ("MSES_DATA_DIR", "MSES_DB_PATH", "MSES_UPLOADS_DIR", "MSES_CERTIFICATES_DIR", "MSES_BACKUPS_DIR",
                "MSES_SETUP_CODE", "MSES_PUBLIC_URL"):
        mp.delenv(var, raising=False)
    server = Server(storage)
    server.start()
    yield server
    server.stop()
    mp.undo()


@pytest.fixture()
def page(browser, live):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    ctx.set_default_timeout(25000)
    p = ctx.new_page()
    p.on("pageerror", lambda e: print("PAGE ERROR:", e))
    yield p
    ctx.close()
