"""Файловый mailbox команды: inbox на агента, блокировка, атомарная запись JSON."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO

from ailit_cli.user_paths import GlobalDirResolver


def _has_fcntl() -> bool:
    return sys.platform != "win32"


if _has_fcntl():
    import fcntl
else:
    fcntl = None  # type: ignore[assignment]


class _InboxFileLock:
    """Блокировка файла inbox (``flock`` на POSIX; на Windows только mkdir родителя)."""

    def __init__(self, lock_path: Path) -> None:
        """Запомнить путь к sidecar ``*.lock``."""
        self._lock_path = lock_path
        self._fp: BinaryIO | None = None

    def __enter__(self) -> None:
        """Захватить эксклюзивную блокировку."""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(self._lock_path, "a+b")
        if fcntl is not None:
            fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Отпустить блокировку."""
        if self._fp is not None:
            if fcntl is not None:
                fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
            self._fp.close()
            self._fp = None


@dataclass(frozen=True, slots=True)
class TeamMessageRecord:
    """Одно сообщение в inbox (поля как в плане L.1)."""

    from_agent: str
    to_agent: str
    text: str
    ts: str
    read: bool = False

    def to_json_row(self) -> dict[str, Any]:
        """Сериализация в JSON-объект с ключами ``from`` / ``to``."""
        return {
            "from": self.from_agent,
            "to": self.to_agent,
            "text": self.text,
            "ts": self.ts,
            "read": self.read,
        }

    @classmethod
    def from_json_row(cls, row: Mapping[str, Any]) -> TeamMessageRecord:
        """Разбор строки из файла inbox."""
        return cls(
            from_agent=str(row["from"]),
            to_agent=str(row["to"]),
            text=str(row["text"]),
            ts=str(row["ts"]),
            read=bool(row.get("read", False)),
        )


class TeamRootSelector:
    """Корень каталога ``teams`` (родитель ``<team_id>``)."""

    @staticmethod
    def for_project(project_root: Path) -> Path:
        """``<project_root>/.ailit/teams`` (состояние команды в проекте)."""
        return (project_root.expanduser().resolve() / ".ailit" / "teams").resolve()

    @staticmethod
    def for_global_state(
        environ: Mapping[str, str] | None = None,
    ) -> Path:
        """``<global_state_dir>/teams`` (под ``AILIT_STATE_DIR`` / XDG и т.д.)."""
        return (GlobalDirResolver(environ).global_state_dir() / "teams").resolve()


class _InboxJsonCodec:
    """Чтение/запись списка сообщений в один inbox-файл."""

    @staticmethod
    def load(path: Path) -> list[TeamMessageRecord]:
        """Прочитать inbox; отсутствующий файл — пустой список."""
        if not path.is_file():
            return []
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return []
        data = json.loads(raw)
        if not isinstance(data, dict):
            return []
        items = data.get("messages")
        if not isinstance(items, list):
            return []
        out: list[TeamMessageRecord] = []
        for it in items:
            if isinstance(it, dict):
                out.append(TeamMessageRecord.from_json_row(it))
        return out

    @staticmethod
    def dump(path: Path, messages: list[TeamMessageRecord]) -> None:
        """Атомарно перезаписать inbox (temp + ``os.replace``)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: MutableMapping[str, Any] = {
            "messages": [m.to_json_row() for m in messages],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)


class TeamInboxStore:
    """Хранилище входящих для одного team-каталога."""

    def __init__(self, team_dir: Path) -> None:
        """``team_dir`` = ``.../teams/<team_id>``."""
        self._team_dir = team_dir.resolve()
        self._inboxes = self._team_dir / "inboxes"

    @property
    def inboxes_dir(self) -> Path:
        """Каталог ``inboxes``."""
        return self._inboxes

    def _inbox_path(self, recipient: str) -> Path:
        safe = recipient.replace(os.sep, "_").replace("..", "_")
        return (self._inboxes / f"{safe}.json").resolve()

    def _lock_path(self, inbox_path: Path) -> Path:
        return inbox_path.parent / f"{inbox_path.name}.lock"

    def append_for_recipient(self, recipient: str, message: TeamMessageRecord) -> None:
        """Добавить сообщение во входящие ``recipient``."""
        inbox = self._inbox_path(recipient)
        lock = self._lock_path(inbox)
        with _InboxFileLock(lock):
            cur = _InboxJsonCodec.load(inbox)
            cur.append(message)
            _InboxJsonCodec.dump(inbox, cur)

    def read_inbox(self, recipient: str) -> tuple[TeamMessageRecord, ...]:
        """Прочитать входящие без изменения."""
        inbox = self._inbox_path(recipient)
        lock = self._lock_path(inbox)
        with _InboxFileLock(lock):
            return tuple(_InboxJsonCodec.load(inbox))

    def mark_read(
        self,
        recipient: str,
        *,
        predicate: Callable[[TeamMessageRecord], bool] | None = None,
    ) -> int:
        """Пометить сообщения прочитанными; вернуть число изменённых.

        Args:
            recipient: агент-получатель.
            predicate: если задан, помечаются только строки с ``predicate(msg)``.
        """
        inbox = self._inbox_path(recipient)
        lock = self._lock_path(inbox)
        with _InboxFileLock(lock):
            cur = _InboxJsonCodec.load(inbox)
            changed = 0
            new_list: list[TeamMessageRecord] = []
            for m in cur:
                if not m.read and (predicate is None or predicate(m)):
                    new_list.append(
                        TeamMessageRecord(
                            from_agent=m.from_agent,
                            to_agent=m.to_agent,
                            text=m.text,
                            ts=m.ts,
                            read=True,
                        ),
                    )
                    changed += 1
                else:
                    new_list.append(m)
            if changed:
                _InboxJsonCodec.dump(inbox, new_list)
            return changed


class TeamSession:
    """Сессия команды: корень ``teams``, идентификатор ``team_id``, операции над inbox."""

    def __init__(self, teams_parent: Path, team_id: str) -> None:
        """``teams_parent`` — каталог, внутри которого лежат ``<team_id>/``."""
        self._teams_parent = teams_parent.expanduser().resolve()
        self._team_id = team_id.strip()
        if not self._team_id:
            raise ValueError("team_id must be non-empty")
        self._team_dir = (self._teams_parent / self._team_id).resolve()
        self._store = TeamInboxStore(self._team_dir)

    @property
    def team_id(self) -> str:
        """Идентификатор команды."""
        return self._team_id

    @property
    def team_dir(self) -> Path:
        """Каталог данных команды."""
        return self._team_dir

    def send(self, from_agent: str, to_agent: str, text: str) -> TeamMessageRecord:
        """Отправить текст от одного агента другому (запись во inbox получателя)."""
        ts = datetime.now(timezone.utc).isoformat()
        msg = TeamMessageRecord(
            from_agent=from_agent.strip(),
            to_agent=to_agent.strip(),
            text=text,
            ts=ts,
            read=False,
        )
        self._store.append_for_recipient(to_agent.strip(), msg)
        return msg

    def inbox(self, agent: str) -> tuple[TeamMessageRecord, ...]:
        """Все входящие для агента."""
        return self._store.read_inbox(agent.strip())

    def mark_all_read(self, agent: str) -> int:
        """Пометить все входящие агента прочитанными."""
        return self._store.mark_read(agent.strip())

    def list_inbox_files(self) -> tuple[Path, ...]:
        """Пути ``inboxes/*.json`` (для отладки и UI)."""
        inbox_dir = self._store.inboxes_dir
        if not inbox_dir.is_dir():
            return ()
        return tuple(sorted(p for p in inbox_dir.glob("*.json") if p.is_file()))

    def iter_recipient_names(self) -> Iterator[str]:
        """Имена агентов, у которых есть файл inbox."""
        for p in self.list_inbox_files():
            if p.suffix == ".json":
                yield p.stem
