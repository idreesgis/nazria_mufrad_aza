"""Read a KEY=value file (e.g. /etc/nazria/nazria.env) into the environment, without a shell.

Sourcing such a file with bash breaks on values containing & $ ; or spaces (a database URL with two options, a
password with special characters). systemd's EnvironmentFile and this reader take each value literally.
Variables already set in the environment win."""
from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | os.PathLike) -> int:
    n = 0
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            n += 1
    return n
