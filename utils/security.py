"""Password hashing, safe file names and safe paths."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import unicodedata
from pathlib import Path

_N, _R, _P = 2 ** 14, 8, 1
_MAXMEM = 64 * 1024 * 1024
MAX_PASSWORD_LENGTH = 128


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    """Return a salted scrypt hash. The plain password is never stored."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32, maxmem=_MAXMEM
    )
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt),
            n=int(n), r=int(r), p=int(p), dklen=32, maxmem=_MAXMEM,
        )
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except Exception:
        return False


def new_token(nbytes: int = 16) -> str:
    return secrets.token_hex(nbytes)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]")


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """Make a user-supplied file name safe to display and store.

    Removes folders (so ../../x becomes x), control characters and odd symbols.
    """
    name = unicodedata.normalize("NFKC", str(name or ""))
    name = name.replace("\\", "/").split("/")[-1]
    name = _CONTROL.sub("", name)
    name = _UNSAFE.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        return "file"
    if len(name) > max_len:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 8:
            name = stem[: max_len - len(ext) - 1] + "." + ext
        else:
            name = name[:max_len]
    return name


def safe_join(base: Path, *parts: str) -> Path:
    """Join paths but refuse to leave the base folder (path traversal guard)."""
    base_resolved = Path(base).resolve()
    target = base_resolved.joinpath(*[str(p) for p in parts]).resolve()
    if target != base_resolved and not target.is_relative_to(base_resolved):
        raise ValueError("Unsafe path")
    return target
