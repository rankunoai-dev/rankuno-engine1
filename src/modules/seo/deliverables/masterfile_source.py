"""Where a masterfile service's Screaming Frog CSVs come from.

The 21 masterfile services were written against a directory of loose CSVs
(`read_csv_safe(self.sf_export_dir / filename)`), and no producer in this
repository ever writes one: a native crawl stores a JSON result, and a
Screaming Frog worker uploads a single zip that is *encrypted at rest* and
never extracted (ADR 0015 condition 11). The services therefore had no
reachable input at all - build-log 0107.

This module is the seam that fixes that without weakening the encryption
stance. A service asks a `MasterfileSource` for a CSV by name and gets a
DataFrame or `None`; whether that name is a file on disk or a member of a
zip held only in memory is not the service's business.

Two rules the implementations share, because a masterfile is a *report* and a
missing input must never read as "no issues found" nor as a crash:

* **Absent is `None`, not an error** - matching `_bundle.Bundle`'s own
  convention and `screaming_frog_adapter`'s "not measured" distinction.
* **Unreadable is an error**, and one type: `MasterfileSourceError`, a
  `ValueError` subclass so `build_runner.run_masterfile` already reports it
  as a failed build without importing it by name.

Reuses `_bundle.open_bundle`/`open_bundle_bytes` for the zip case rather than
a second zip reader: every hostile thing an archive can do - traversal names,
symlinks, duplicate basenames, zip bombs, encrypted or exotically compressed
members - is already refused there, before a byte is parsed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pandas as pd  # type: ignore[import-untyped]

from src.core.logger import get_logger
from src.modules.seo.deliverables._bundle import Bundle, open_bundle, open_bundle_bytes

__all__ = [
    "BundleMasterfileSource",
    "DirectoryMasterfileSource",
    "MasterfileSource",
    "MasterfileSourceError",
    "read_csv_safe",
    "source_for_bundle_bytes",
    "source_for_path",
]

_logger = get_logger(__name__)

_DEFAULT_ENCODING: str = "utf-8-sig"
"""`-sig`, not bare `utf-8`: Screaming Frog writes its CSVs with a UTF-8 BOM,
and bare `utf-8` leaves it glued to the first header cell (`﻿Address`),
which `gc()` then cannot find - a real export would produce empty reports
rather than an error. `utf-8-sig` reads BOM-less UTF-8 identically, so this is
strictly more tolerant than the encoding it replaces."""

_ENCODING_FALLBACKS: tuple[str, ...] = ("latin-1", "iso-8859-1", "cp1252")
"""Real client exports are not all UTF-8. Tried in order, first win."""


class MasterfileSourceError(ValueError):
    """A named CSV exists but could not be read or parsed.

    A `ValueError` for the reason `build_runner`'s module docstring gives:
    every build-failure type that module can see shares that base, so one
    `except ValueError` reports all of them without an import list to
    hand-maintain.
    """


def read_csv_safe(csv_path: str | Path, encoding: str = _DEFAULT_ENCODING) -> pd.DataFrame | None:
    """Read a CSV with fallback encodings; return None if the file is missing.

    Args:
        csv_path: Path to the CSV file.
        encoding: Encoding to try first (default UTF-8 with optional BOM).

    Returns:
        A DataFrame, or `None` when the file does not exist.

    Raises:
        ValueError: No candidate encoding could read the file.
    """
    path = Path(csv_path)
    if not path.exists():
        return None

    for enc in (encoding, *_ENCODING_FALLBACKS):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    msg = f"Could not read {path} with any encoding"
    raise ValueError(msg)


class MasterfileSource(Protocol):
    """A set of Screaming Frog export CSVs, addressed by filename."""

    def read_csv(self, filename: str) -> pd.DataFrame | None:
        """Return `filename` as a DataFrame, or `None` when it is absent."""
        ...

    def names(self) -> frozenset[str]:
        """Every CSV filename this source holds.

        Needed because one export is dynamic: Screaming Frog writes one
        `custom_extraction_<name>.csv` per configured extractor, so the set
        is only knowable from the source itself.
        """
        ...

    def close(self) -> None:
        """Release any archive handle. Idempotent; safe on a directory."""
        ...


class DirectoryMasterfileSource:
    """Loose CSVs in a directory - what `scripts/build_deliverable.py` reads.

    Deliberately *not* routed through `_bundle._DirectoryBundle`: that class
    decodes strict UTF-8-with-BOM only, and a client's export directory is
    the one case where the encoding fallbacks above have to stay.
    """

    def __init__(self, root: Path | str) -> None:
        """Bind to `root`, without requiring it to exist yet."""
        self.root = Path(root)

    def read_csv(self, filename: str) -> pd.DataFrame | None:
        """One CSV from the directory, or `None` when it is absent or empty."""
        try:
            frame = read_csv_safe(self.root / filename)
        except pd.errors.EmptyDataError:
            # A zero-byte export is "nothing measured", the same as an
            # absent one - never a failed build.
            return None
        except ValueError as exc:
            raise MasterfileSourceError(str(exc)) from exc
        if frame is None:
            _logger.debug("masterfile_csv_absent", extra={"filename": filename})
        return frame

    def names(self) -> frozenset[str]:
        """Every file in the directory. Empty when it does not exist."""
        if not self.root.is_dir():
            return frozenset()
        return frozenset(entry.name for entry in self.root.iterdir() if entry.is_file())

    def close(self) -> None:
        """Nothing to release: a directory holds no handle."""


class BundleMasterfileSource:
    """A zip of CSVs, on disk or in memory, read through `_bundle`.

    Members are streamed and parsed one at a time; nothing is extracted to
    disk, which is what lets a worker bundle stay encrypted at rest and still
    feed a masterfile build.
    """

    def __init__(self, bundle: Bundle) -> None:
        """Take ownership of `bundle`; `close()` releases it."""
        self._bundle = bundle

    def read_csv(self, filename: str) -> pd.DataFrame | None:
        """One CSV member, streamed, or `None` when absent or empty.

        Raises:
            MasterfileSourceError: The member exists and cannot be decoded
                or parsed.
        """
        stream = self._bundle.open_text(filename)
        if stream is None:
            _logger.debug("masterfile_csv_absent", extra={"filename": filename})
            return None
        try:
            with stream:
                return pd.read_csv(stream)
        except pd.errors.EmptyDataError:
            return None
        except (UnicodeDecodeError, pd.errors.ParserError, OSError) as exc:
            # No encoding retry: the stream is consumed, and a zip member is
            # decoded strictly by `_bundle` on purpose. Name the file and the
            # rule, never the content (Step 5 audit, item 6).
            msg = f"{filename}: unreadable-csv"
            raise MasterfileSourceError(msg) from exc

    def names(self) -> frozenset[str]:
        """Every member of the archive, by basename."""
        return self._bundle.names()

    def close(self) -> None:
        """Close the archive, releasing its handle and its buffers."""
        self._bundle.close()


def source_for_path(path: Path) -> MasterfileSource:
    """A source for an export directory or a zip on disk.

    Raises:
        ScreamingFrogBundleError: `path` is neither a directory nor a zip.
    """
    if path.is_dir():
        return DirectoryMasterfileSource(path)
    return BundleMasterfileSource(open_bundle(path))


def source_for_bundle_bytes(data: bytes, display_name: str) -> MasterfileSource:
    """A source for a decrypted bundle held in memory.

    Args:
        data: The plaintext zip archive. Never written to disk.
        display_name: What an error message may name - a job id or a fixed
            label, never a member name or a URL.

    Raises:
        ScreamingFrogBundleError: `data` is not a zip, or fails pre-flight.
    """
    return BundleMasterfileSource(open_bundle_bytes(data, display_name))
