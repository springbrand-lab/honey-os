"""Read the agent's durable memory files as companion-facing memory cards."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from honeyos.tools.memory_tool import MemoryStore


@dataclass(frozen=True)
class PersistentMemoryItem:
    id: str
    kind: str
    content: str
    status: str
    evidence: str
    importance: str
    created_by: str
    source_session_id: str
    source_message_ids: tuple[int, ...]
    created_at: datetime
    updated_at: datetime
    expires_at: None = None


def _item_id(target: str, content: str) -> str:
    digest = hashlib.sha256(f"{target}\0{content}".encode("utf-8")).hexdigest()[:24]
    return f"persistent_{target}_{digest}"


def _file_time(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.now(timezone.utc)


def _target_from_id(item_id: str) -> str | None:
    if item_id.startswith("persistent_memory_"):
        return "memory"
    if item_id.startswith("persistent_user_"):
        return "user"
    return None


def _path_for(home: Path, target: str) -> Path:
    filename = "USER.md" if target == "user" else "MEMORY.md"
    return Path(home).expanduser().resolve() / "memories" / filename


def list_persistent_memories(home: Path) -> tuple[PersistentMemoryItem, ...]:
    """Return all readable MEMORY.md and USER.md entries without modifying them."""

    items: list[PersistentMemoryItem] = []
    for target in ("memory", "user"):
        path = _path_for(home, target)
        entries, read_ok = MemoryStore._read_entries_checked(path)
        if not read_ok:
            continue
        changed_at = _file_time(path)
        evidence = "persistent_user" if target == "user" else "persistent_memory"
        for entry in dict.fromkeys(entries):
            items.append(
                PersistentMemoryItem(
                    id=_item_id(target, entry),
                    kind="long_term_memory",
                    content=entry,
                    status="active",
                    evidence=evidence,
                    importance="high",
                    created_by="memory_file",
                    source_session_id="",
                    source_message_ids=(),
                    created_at=changed_at,
                    updated_at=changed_at,
                )
            )
    return tuple(items)


def forget_persistent_memory(home: Path, item_id: str) -> bool:
    """Remove the exact durable entry represented by *item_id*, if it still exists."""

    target = _target_from_id(item_id)
    if target is None:
        return False
    path = _path_for(home, target)
    store = MemoryStore()
    with store._file_lock(path):
        entries, read_ok = store._read_entries_checked(path)
        if not read_ok:
            return False
        match = next(
            (index for index, entry in enumerate(entries) if _item_id(target, entry) == item_id),
            None,
        )
        if match is None:
            return False
        entries.pop(match)
        path.parent.mkdir(parents=True, exist_ok=True)
        store._write_file(path, entries)
    return True
