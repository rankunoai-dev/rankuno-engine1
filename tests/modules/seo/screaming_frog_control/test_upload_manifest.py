"""Tests for ADR 0015 condition 9's untrusted-upload validation."""

from __future__ import annotations

import io
import zipfile
from typing import Final

import pytest
from src.modules.seo.contracts.audit import Coverage
from src.modules.seo.contracts.catalogue import ISSUE_CATALOGUE
from src.modules.seo.deliverables.screaming_frog_adapter import (
    SPINE_FILE,
    load_screaming_frog_bundle,
)
from src.modules.seo.page_classifier.url_rules import normalize_url
from src.modules.seo.screaming_frog_control import worker_daemon
from src.modules.seo.screaming_frog_control.export_manifest import (
    BULK_EXPORT,
    EXPORT_TABS,
    SPINE_TAB,
)
from src.modules.seo.screaming_frog_control.schemas import (
    LicenceStatus,
    ScreamingFrogJobOutput,
)
from src.modules.seo.screaming_frog_control.upload_manifest import (
    ALLOWED_BUNDLE_FILENAMES,
    BundleUploadError,
    _check_member_name,
    validate_and_extract_bundle,
)


class _RecordingClient:
    """Just enough of `WorkerCloudClient` for `_upload_bundle`."""

    def __init__(self) -> None:
        self.uploads: list[bytes] = []
        self.failures: list[str] = []

    def upload_bundle(self, job_id: str, archive_bytes: bytes) -> None:
        self.uploads.append(archive_bytes)

    def report_failure(self, job_id: str, error: str) -> None:
        self.failures.append(error)


def _zip(members: dict[str, bytes], *, raw_names: bool = False) -> bytes:
    """Build a zip.

    `raw_names` bypasses `ZipInfo`'s own name normalisation, the same
    technique `tests/modules/seo/test_screaming_frog_bundle.py`'s
    `make_zip` uses to get a hostile literal name past `zipfile` itself.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for name, data in members.items():
            if raw_names:
                info = zipfile.ZipInfo("placeholder.csv")
                info.filename = name
                archive.writestr(info, data)
            else:
                archive.writestr(name, data)
    return buffer.getvalue()


def _set_encryption_flag(data: bytes) -> bytes:
    """Flip the general-purpose encryption bit in both zip header copies.

    `zipfile` recomputes `flag_bits` on write and will not honour a
    caller-set encryption bit, so the only way to produce a
    zipfile-readable "encrypted" entry for this test is to patch the raw
    bytes after writing — the same technique
    `test_screaming_frog_bundle.py`'s `patch_headers` uses.
    """
    buffer = bytearray(data)
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        index = buffer.find(signature)
        while index >= 0:
            buffer[index + offset] |= 0x1
            index = buffer.find(signature, index + 1)
    return bytes(buffer)


def test_allowed_filenames_includes_the_mandatory_spine_file():
    assert "internal_all.csv" in ALLOWED_BUNDLE_FILENAMES


def test_valid_bundle_extracts_allowed_members():
    data = _zip({"internal_all.csv": b"Address\nhttps://example.com/\n"})
    extracted = validate_and_extract_bundle(data, max_total_bytes=10_000)
    assert extracted == {"internal_all.csv": b"Address\nhttps://example.com/\n"}


def test_bundle_missing_optional_files_is_not_an_error():
    """`export_manifest.py`'s own convention: absent means 'not measured'."""
    data = _zip({"internal_all.csv": b"spine only"})
    extracted = validate_and_extract_bundle(data, max_total_bytes=10_000)
    assert set(extracted) == {"internal_all.csv"}


def test_rejects_a_member_not_in_the_allowlist():
    data = _zip({"internal_all.csv": b"ok", "evil.exe": b"MZ..."})
    with pytest.raises(BundleUploadError, match="not an expected export file"):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_a_traversal_member_name():
    data = _zip({"../../../etc/passwd": b"pwned"})
    with pytest.raises(BundleUploadError, match="traversal"):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_an_absolute_member_name():
    data = _zip({"/etc/passwd": b"pwned"})
    with pytest.raises(BundleUploadError, match="absolute"):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_a_windows_drive_prefixed_member_name():
    data = _zip({"C:/Windows/System32/evil.dll": b"pwned"})
    with pytest.raises(BundleUploadError):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_a_backslash_member_name():
    """A backslash-containing member name is refused, in principle.

    `zipfile` itself rewrites a backslash to `/` when it parses the
    central directory (confirmed against this stdlib, matching
    `tests/modules/seo/test_screaming_frog_bundle.py`'s own documented
    finding for `_bundle.py`'s identical guard) — so a real round-tripped
    archive can never carry one through to `_check_member_name`. The guard
    is exercised directly, the same way that sibling test suite does, so it
    still holds on a platform or zipfile version where the rewrite does not
    happen.
    """
    with pytest.raises(BundleUploadError, match="forbidden character"):
        _check_member_name("..\\..\\evil.csv")


def test_rejects_not_a_zip():
    with pytest.raises(BundleUploadError, match="not a valid zip"):
        validate_and_extract_bundle(b"this is not a zip file at all", max_total_bytes=10_000)


def test_rejects_over_the_total_size_cap():
    data = _zip({"internal_all.csv": b"x" * 1000})
    with pytest.raises(BundleUploadError, match="size cap"):
        validate_and_extract_bundle(data, max_total_bytes=10)


def test_rejects_an_encrypted_member():
    data = _set_encryption_flag(_zip({"internal_all.csv": b"secret"}))
    assert zipfile.ZipFile(io.BytesIO(data)).infolist()[0].flag_bits & 0x1
    with pytest.raises(BundleUploadError, match="encrypted"):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_duplicate_basenames():
    """Two members that would produce the same allow-listed basename."""
    data = _zip({"a/internal_all.csv": b"one", "b/internal_all.csv": b"two"})
    with pytest.raises(BundleUploadError, match="duplicate"):
        validate_and_extract_bundle(data, max_total_bytes=10_000)


def test_rejects_too_many_members():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for i in range(201):
            archive.writestr(f"unexpected_{i}.csv", b"x")
    with pytest.raises(BundleUploadError, match="too many members"):
        validate_and_extract_bundle(buffer.getvalue(), max_total_bytes=10_000_000)


# --- the allow-list itself: what the catalogue reads must be admissible ---------

_SPINE_AND_CATALOGUE_FILES: Final[frozenset[str]] = frozenset(
    {SPINE_FILE} | {name for spec in ISSUE_CATALOGUE for name in spec.sf_sources}
)

_THRESHOLD_AND_AMPERSAND_FILES: Final[frozenset[str]] = frozenset(
    {
        "h1_over_70_characters.csv",
        "meta_description_below_400_pixels.csv",
        "meta_description_over_985_pixels.csv",
        "page_titles_below_200_pixels.csv",
        "page_titles_over_561_pixels.csv",
        "hreflang_incorrect_language_region_codes.csv",
        "hreflang_inconsistent_language_region_return_links.csv",
    }
)
"""The seven filenames the `--export-tabs` argument strings cannot produce.
Verified present in 45/45 real Screaming Frog 19.4 export folders."""

_CLI_ARGUMENT_CORRECTIONS: Final[dict[str, str]] = {
    "h1_over_x_characters.csv": "h1_over_70_characters.csv",
    "meta_description_below_x_pixels.csv": "meta_description_below_400_pixels.csv",
    "meta_description_over_x_pixels.csv": "meta_description_over_985_pixels.csv",
    "page_titles_below_x_pixels.csv": "page_titles_below_200_pixels.csv",
    "page_titles_over_x_pixels.csv": "page_titles_over_561_pixels.csv",
    "hreflang_incorrect_language__region_codes.csv": (
        "hreflang_incorrect_language_region_codes.csv"
    ),
    "hreflang_inconsistent_language__region_return_links.csv": (
        "hreflang_inconsistent_language_region_return_links.csv"
    ),
}
"""What the naming transform yields for those same seven arguments, mapped to
what the export really contains. Every key appears in 0/45 real export
folders: Screaming Frog never writes these."""

_CLI_ARGUMENT_FORMS: Final[frozenset[str]] = frozenset(_CLI_ARGUMENT_CORRECTIONS)


def test_allow_list_admits_every_filename_the_catalogue_reads():
    """The missing test. Its absence, not the seven strings, is the defect.

    A name `ISSUE_CATALOGUE` reads that the gate refuses is data that can never
    reach a deliverable, and — because the worker filters on the same list —
    fails silently rather than loudly.
    """
    assert _SPINE_AND_CATALOGUE_FILES <= ALLOWED_BUNDLE_FILENAMES


def test_allow_list_admits_nothing_beyond_the_spine_and_the_catalogue():
    """The gate is exactly the consumable set: no name no consumer reads."""
    assert ALLOWED_BUNDLE_FILENAMES == _SPINE_AND_CATALOGUE_FILES


def test_allow_list_admits_the_seven_filenames_the_cli_arguments_cannot_produce():
    assert _THRESHOLD_AND_AMPERSAND_FILES <= ALLOWED_BUNDLE_FILENAMES


def test_allow_list_refuses_the_placeholder_forms_screaming_frog_never_writes():
    assert not ALLOWED_BUNDLE_FILENAMES & _CLI_ARGUMENT_FORMS


def test_allow_list_refuses_the_analytics_and_extraction_exports():
    """A different sensitivity class, needing its own security review.

    These carry analytics identifiers and operator-defined extraction output.
    Deriving the gate from the catalogue must not quietly admit them.
    """
    assert not ALLOWED_BUNDLE_FILENAMES & {
        "search_console_all.csv",
        "analytics_all.csv",
        "custom_extraction_all.csv",
    }


def _cli_argument_filename(argument: str, *, bulk: bool) -> str:
    """Screaming Frog's documented `--export-tabs`/`--bulk-export` transform.

    Kept here rather than in `upload_manifest.py` on purpose: it is a
    cross-check on the argument manifest, not the source of the allow-list,
    because for seven arguments it is provably wrong (`_CLI_ARGUMENT_FORMS`).
    """
    segment = argument.rsplit(":", 1)[-1] if bulk else argument
    for char in ("-", "<", ">", "&"):
        segment = segment.replace(char, "")
    segment = segment.replace(".", "_").replace(" ", "_").replace(":", "_")
    return f"{segment.lower()}.csv"


def test_the_cli_manifest_and_the_allow_list_still_describe_one_export():
    """Catches drift in either direction between the two lists.

    An `--export-tabs` argument added without a catalogue row, or a catalogue
    row whose file this engine never asks Screaming Frog to write, fails here.
    The seven known-wrong transform outputs are mapped to the filenames the
    real export carries; every other argument must transform exactly.
    """
    produced = (
        {f"{SPINE_TAB.replace(':', '_').lower()}.csv"}
        | {_cli_argument_filename(arg, bulk=False) for arg in EXPORT_TABS}
        | {_cli_argument_filename(arg, bulk=True) for arg in BULK_EXPORT}
    )
    corrected = {_CLI_ARGUMENT_CORRECTIONS.get(name, name) for name in produced}
    assert corrected == ALLOWED_BUNDLE_FILENAMES


# --- the observable symptom: worker -> engine -> adapter coverage ---------------


def test_a_real_export_reaches_the_adapter_as_measured(tmp_path):
    """The end-to-end behaviour the wrong names produced: silent NOT_MEASURED.

    The worker filters `bundle_dir` on the same allow-list the engine validates
    against, so a name missing from it was never rejected — it was dropped
    before upload, and the seven issues it feeds reported `NOT_MEASURED`
    forever with nobody told.
    """
    url = "https://example.com/a"
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / SPINE_FILE).write_text(f"Address\n{url}\n", encoding="utf-8")
    for name in _THRESHOLD_AND_AMPERSAND_FILES:
        (bundle_dir / name).write_text(f"Address\n{url}\n", encoding="utf-8")

    client = _RecordingClient()
    worker_daemon._upload_bundle(
        client,  # type: ignore[arg-type]
        "job-1",
        ScreamingFrogJobOutput(
            bundle_dir=bundle_dir, licence=LicenceStatus(active=True), elapsed_s=1.0
        ),
        max_bytes=1_000_000,
    )
    assert client.failures == []
    extracted = validate_and_extract_bundle(client.uploads[0], max_total_bytes=1_000_000)
    assert set(extracted) >= _THRESHOLD_AND_AMPERSAND_FILES

    store = tmp_path / "store"
    store.mkdir()
    for name, raw in extracted.items():
        (store / name).write_bytes(raw)
    dataset = load_screaming_frog_bundle(store, normalize=normalize_url)

    affected = [
        spec.id for spec in ISSUE_CATALOGUE if set(spec.sf_sources) & _THRESHOLD_AND_AMPERSAND_FILES
    ]
    assert len(affected) == 7
    assert all(dataset.coverage[issue_id] is Coverage.MEASURED for issue_id in affected)
