"""Disk-backed storage for uploaded client rulebooks (cycle 0087).

`rulebook.py` turns a `.xlsx` file *already on disk* into a `Rulebook`; it has
no opinion about where that file came from or how long it lives. This module
is the missing piece for the HTTP layer: an operator uploads a rulebook once,
it is validated and kept, and a build request references it by id instead of
re-uploading the file on every call.

One `.xlsx` plus one JSON metadata sidecar per record, under one directory -
the same shape `DiskJobStore` uses for a job's record and result, for the same
reason: a crash between the two writes must never leave a record that
advertises a file it does not have.

IDOR posture is the same stance `DiskJobStore` already takes for jobs: the
store persists whatever `org_id` it is given and answers `get()`/`list_all()`
for any id, without itself filtering by caller. Enforcing that a caller only
reads or deletes *its own* records is the API layer's job - see
`get_job`/`get_result` in `src/api/server.py`, which this store's callers are
required to mirror exactly rather than re-deriving their own check.
"""

from __future__ import annotations

import os
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.modules.seo.deliverables.rulebook import Rulebook

__all__ = [
    "MAX_RULEBOOK_LABEL_LENGTH",
    "RulebookNotFoundError",
    "RulebookRecord",
    "RulebookStore",
]

_logger = get_logger(__name__)

MAX_RULEBOOK_LABEL_LENGTH: Final[int] = 200
"""An operator-supplied name for a list, not free text - bounded generously."""


class RulebookNotFoundError(KeyError):
    """No rulebook exists with the given id."""


class RulebookRecord(StrictModel):
    """Metadata for one uploaded rulebook. The `.xlsx` itself lives beside it.

    Attributes:
        id: Opaque identifier, minted by the store. Never accepted from a
            caller - the same reasoning as `JobRecord.id`: an id becomes a
            filename, so a caller-supplied one is a path-traversal parameter.
        org_id: Organization that owns this rulebook. Enforced by the API
            layer, not by this store (see the module docstring).
        label: Operator-facing name shown in a list. May be blank.
        rule_count: Rows parsed from the uploaded workbook, for display only.
        size_bytes: Size of the stored `.xlsx`, for display only.
        created_at: When the upload was accepted.
    """

    id: str = Field(min_length=1)
    org_id: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    label: str = Field(default="", max_length=MAX_RULEBOOK_LABEL_LENGTH)
    rule_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    created_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _atomic_write(path: Path, payload: str) -> None:
    """Write `payload` to `path` so a crash cannot leave it half-written.

    Duplicated from `state_store._atomic_write` rather than imported: that
    name is private, and importing a private helper across a module boundary
    would tie this file to `core.state_store`'s internals rather than its
    public contract. The implementation is nine lines and unlikely to drift.
    """
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class RulebookStore:
    """One `.xlsx` plus a metadata sidecar per uploaded rulebook.

    Single-process only, the same limitation `DiskJobStore` carries (ADR
    0004): the lock below serialises this process's own threads and does
    nothing across two processes sharing a directory.
    """

    def __init__(self, root: Path | str) -> None:
        """Create the store, making its directory if absent.

        Args:
            root: Directory to hold rulebook files and their metadata.
        """
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        """Directory holding the rulebook files."""
        return self._root

    def _meta_path(self, rulebook_id: str) -> Path:
        return self._root / f"{rulebook_id}.json"

    def _file_path(self, rulebook_id: str) -> Path:
        return self._root / f"{rulebook_id}.xlsx"

    def create(self, org_id: str, label: str, content: bytes) -> RulebookRecord:
        """Validate `content` as a rulebook workbook, then persist it.

        Validation happens here, not in the API layer, so "a rulebook is
        stored" and "a rulebook parses" can never disagree later: `create()`
        calls the same `Rulebook.from_xlsx` a build will call, on the exact
        bytes that get saved.

        Args:
            org_id: Organization that will own this rulebook.
            label: Operator-facing name, truncated to `MAX_RULEBOOK_LABEL_LENGTH`.
            content: The raw `.xlsx` bytes.

        Returns:
            The persisted record.

        Raises:
            RulebookError: `content` is not a readable rulebook workbook -
                no `Rulebook` sheet, no header row, or a row that fails to
                parse. Propagated from `Rulebook.from_xlsx`.
        """
        rulebook_id = uuid.uuid4().hex
        target = self._file_path(rulebook_id)
        # `.xlsx`, not `.tmp`: `openpyxl.load_workbook` validates the file
        # *extension* before it looks at a single byte
        # (`openpyxl.reader.excel._validate_archive`), so `Rulebook.from_xlsx`
        # below would refuse even genuinely valid content staged under a
        # `.tmp` name.
        handle, tmp_name = tempfile.mkstemp(dir=str(self._root), suffix=".upload.xlsx")
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(content)
            # Raises RulebookError on unreadable/malformed content, before
            # anything is kept under the rulebook's real id.
            parsed = Rulebook.from_xlsx(tmp_path)
            with self._lock:
                os.replace(tmp_path, target)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

        record = RulebookRecord(
            id=rulebook_id,
            org_id=org_id,
            label=label[:MAX_RULEBOOK_LABEL_LENGTH],
            rule_count=len(parsed.rules),
            size_bytes=len(content),
            created_at=_now(),
        )
        with self._lock:
            _atomic_write(self._meta_path(rulebook_id), record.model_dump_json())
        _logger.info(
            "rulebook_stored",
            extra={"rulebook_id": rulebook_id, "org": org_id, "rules": record.rule_count},
        )
        return record

    def get(self, rulebook_id: str) -> RulebookRecord:
        """Read one rulebook's metadata.

        Raises:
            RulebookNotFoundError: If no such rulebook exists.
        """
        path = self._meta_path(rulebook_id)
        with self._lock:
            if not path.exists():
                raise RulebookNotFoundError(f"no rulebook with id {rulebook_id!r}")
            return RulebookRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list_all(self) -> list[RulebookRecord]:
        """Every rulebook, newest first, for every organization.

        Mirrors `DiskJobStore.list_jobs()`: unfiltered here, filtered by the
        caller against the requesting `org_id` (see the module docstring). A
        record that fails to parse is skipped rather than raised, so one
        corrupt file cannot make the whole list unavailable.
        """
        records: list[RulebookRecord] = []
        with self._lock:
            for path in self._root.glob("*.json"):
                try:
                    records.append(
                        RulebookRecord.model_validate_json(path.read_text(encoding="utf-8"))
                    )
                except (ValueError, OSError) as exc:
                    _logger.warning(
                        "rulebook_record_unreadable", extra={"path": path.name, "error": str(exc)}
                    )
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def path_for(self, rulebook_id: str) -> Path:
        """Path to the stored `.xlsx`, after confirming the record exists.

        Raises:
            RulebookNotFoundError: No such record, or its file is missing.
        """
        self.get(rulebook_id)
        path = self._file_path(rulebook_id)
        if not path.is_file():
            raise RulebookNotFoundError(f"rulebook {rulebook_id!r} has no stored file")
        return path

    def delete(self, rulebook_id: str) -> None:
        """Remove a rulebook's file and metadata.

        Raises:
            RulebookNotFoundError: If no such rulebook exists.
        """
        self.get(rulebook_id)  # Fail before touching disk for an id that is gone.
        with self._lock:
            self._file_path(rulebook_id).unlink(missing_ok=True)
            self._meta_path(rulebook_id).unlink(missing_ok=True)
        _logger.info("rulebook_deleted", extra={"rulebook_id": rulebook_id})
