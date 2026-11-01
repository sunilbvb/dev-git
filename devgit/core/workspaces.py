"""Persistent list of saved workspaces, stored in ~/.devgit/workspaces.json."""
import json
import os
import threading
from pathlib import Path
from typing import List

_LOCK = threading.Lock()


def _store_file() -> Path:
    base = os.environ.get("DEVGIT_CONFIG_DIR")
    root = Path(base).expanduser() if base else Path.home() / ".devgit"
    return root / "workspaces.json"


def _read() -> List[str]:
    try:
        data = json.loads(_store_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("workspaces") if isinstance(data, dict) else None
    return [p for p in items if isinstance(p, str)] if isinstance(items, list) else []


def _write(paths: List[str]) -> None:
    f = _store_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"workspaces": paths}, indent=2), encoding="utf-8")
    tmp.replace(f)


def list_workspaces() -> List[dict]:
    with _LOCK:
        paths = _read()
    return [{"path": p, "name": Path(p).name or p, "exists": Path(p).is_dir()} for p in paths]


def add_workspace(path) -> None:
    p = str(Path(path).expanduser().resolve())
    with _LOCK:
        paths = _read()
        if p not in paths:
            paths.append(p)
            _write(paths)


def remove_workspace(path) -> None:
    p = str(Path(path).expanduser().resolve())
    with _LOCK:
        paths = _read()
        if p in paths:
            paths.remove(p)
            _write(paths)
