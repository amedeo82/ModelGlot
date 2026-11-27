"""Concrete call signatures shared by the pytest fixture factories."""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypedDict, Unpack

from typing_extensions import TypedDict as ClosedTypedDict

from modelglot.application.code_sessions.models import (
    CodeItem,
    CodePrompt,
    CodeRun,
)
from modelglot.messaging.models import IncomingMessage
from modelglot.runtime.messaging_sqlite import SQLiteMessagingStore
from modelglot.runtime.sqlite_database import SQLiteDatabase


class IncomingMessageOverrides(TypedDict, total=False):
    text: str
    chat_id: str
    user_id: str
    message_id: str
    platform: str
    reply_to_message_id: str | None
    message_thread_id: str | None
    username: str | None
    timestamp: datetime | str
    raw_event: object
    status_message_id: str | None


class IncomingMessageFactory(Protocol):
    def __call__(
        self, **kwargs: Unpack[IncomingMessageOverrides]
    ) -> IncomingMessage: ...


class DatabaseFactory(Protocol):
    def __call__(
        self, path: Path, lock_path: Path, *, legacy_path: Path | None = None
    ) -> SQLiteDatabase: ...


class MessagingStoreFactory(Protocol):
    async def __call__(
        self,
        *,
        storage_path: str | Path | None = None,
        managed_message_cap: int | None = None,
    ) -> SQLiteMessagingStore: ...


class ProgressChanges(ClosedTypedDict, total=False, closed=True):
    run: CodeRun | None
    items: Sequence[CodeItem]
    prompts: Sequence[CodePrompt]
