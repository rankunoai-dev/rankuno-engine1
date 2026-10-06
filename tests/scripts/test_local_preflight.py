"""`scripts/local_preflight.py`: the guards behind `scripts/run_local.ps1`.

What is proven here: a dotenv file naming any production-reaching key refuses
the launch in every spelling pydantic-settings and python-dotenv accept; no
value ever reaches the output; the memory budget is 40% of RAM, clamped; and an
empty process-env value really does override a dotenv `DATABASE_URL`, with a
control case showing the same setup *without* the blanks is configured. No
database, no network.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import scripts.local_preflight as preflight
from src.core.postgres_config import get_postgres_settings, reset_postgres_settings_cache

SENTINEL = "postgresql://leaky:hunter2@db.prod.invalid:5432/rankuno"
BLANKED = ("DATABASE_URL", "POSTGRES_URL", "DATABASE_PRIVATE_URL", "POSTGRES_PASSWORD")


@pytest.fixture(autouse=True)
def _isolate_postgres_cache() -> Iterator[None]:
    reset_postgres_settings_cache()
    yield
    reset_postgres_settings_cache()


def _write(root: Path, text: str, name: str = ".env") -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


# -- scan ---------------------------------------------------------------------


def test_clean_files_pass(tmp_path: Path) -> None:
    _write(tmp_path, "LOG_LEVEL=INFO\nGEMINI_API_KEY=abc\n")
    _write(tmp_path, "WORKER_ID=w1\nWORKER_DISPATCH_SIGNING_SECRET=x\n", ".env.local")
    assert preflight.main(["scan", "--root", str(tmp_path)]) == 0


def test_missing_files_pass(tmp_path: Path) -> None:
    assert preflight.scan_dotenv(tmp_path).refusals == []


@pytest.mark.parametrize("key", preflight.FORBIDDEN_KEYS)
def test_each_forbidden_key_is_refused(tmp_path: Path, key: str) -> None:
    _write(tmp_path, f"{key}={SENTINEL}\n", ".env.local")
    result = preflight.scan_dotenv(tmp_path)
    assert len(result.refusals) == 1
    assert key in result.refusals[0]


@pytest.mark.parametrize(
    "line",
    [
        f"database_url={SENTINEL}",
        f"export DATABASE_URL={SENTINEL}",
        f"  Database_Url = {SENTINEL}",
        "DATABASE_URL=",
    ],
)
def test_every_spelling_settings_accept_is_refused(tmp_path: Path, line: str) -> None:
    _write(tmp_path, line + "\n")
    assert preflight.scan_dotenv(tmp_path).refusals


def test_commented_line_passes(tmp_path: Path) -> None:
    _write(tmp_path, f"# DATABASE_URL={SENTINEL}\n#ENVIRONMENT=production\n")
    assert preflight.scan_dotenv(tmp_path).refusals == []


def test_environment_refusal_says_how_to_fix(tmp_path: Path) -> None:
    path = _write(tmp_path, "ENVIRONMENT=development\n")
    (refusal,) = preflight.scan_dotenv(tmp_path).refusals
    assert f"comment out or delete the ENVIRONMENT line in {path}" in refusal


@pytest.mark.parametrize("value", ["postgres", '"postgres"', "POSTGRES  # cloud"])
def test_postgres_worker_store_is_refused(tmp_path: Path, value: str) -> None:
    _write(tmp_path, f"WORKER_STORE_BACKEND={value}\n")
    assert preflight.scan_dotenv(tmp_path).refusals


def test_disk_worker_store_passes(tmp_path: Path) -> None:
    _write(tmp_path, "WORKER_STORE_BACKEND=disk\n")
    assert preflight.scan_dotenv(tmp_path).refusals == []


def test_budget_key_is_a_notice_not_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, "CRAWL_MEMORY_BUDGET_MIB=3072\n")
    assert preflight.main(["scan", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "CRAWL_MEMORY_BUDGET_MIB" in out
    assert "3072" not in out


def test_no_value_reaches_the_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    lines = "".join(f"{key}={SENTINEL}\n" for key in preflight.FORBIDDEN_KEYS)
    _write(tmp_path, lines)
    assert preflight.main(["scan", "--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    for stream in (captured.out, captured.err, caplog.text):
        assert "hunter2" not in stream
        assert "db.prod.invalid" not in stream


TOKEN_SENTINEL = "f00d" * 16


@pytest.mark.parametrize(
    "line",
    [
        f"AUTH_LOCAL_AUTOSIGNIN_TOKEN={TOKEN_SENTINEL}",
        f"auth_local_autosignin_token = {TOKEN_SENTINEL}",
        f"export AUTH_LOCAL_AUTOSIGNIN_TOKEN='{TOKEN_SENTINEL}'",
        "AUTH_LOCAL_AUTOSIGNIN_TOKEN=",
    ],
)
@pytest.mark.parametrize("name", preflight.DOTENV_FILES)
def test_a_stored_signin_token_is_refused_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], line: str, name: str
) -> None:
    _write(tmp_path, line + "\n", name)
    assert preflight.main(["scan", "--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "AUTH_LOCAL_AUTOSIGNIN_TOKEN" in captured.err
    assert TOKEN_SENTINEL not in captured.out + captured.err


def test_the_signin_operator_ids_are_not_refused(tmp_path: Path) -> None:
    _write(tmp_path, "AUTH_LOCAL_AUTOSIGNIN_OPERATOR_ID=local\n")
    assert preflight.scan_dotenv(tmp_path).refusals == []


# -- budget -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("total_bytes", "expected"),
    [
        (34_053_414_912, 12_990),  # this workstation, 31.7 GiB
        (512 * preflight.MIB, 256),  # clamped up to the Settings floor
        (1024**4, 65_536),  # 1 TiB, clamped down to the Settings ceiling
    ],
)
def test_budget_is_forty_percent_clamped(total_bytes: int, expected: int) -> None:
    assert preflight.compute_budget_mib(total_bytes) == expected


def test_valid_override_wins() -> None:
    assert preflight.compute_budget_mib(34_053_414_912, "8000") == 8000


@pytest.mark.parametrize("override", ["255", "65537", "abc", "1.5", "-300"])
def test_bad_override_is_refused(override: str, capsys: pytest.CaptureFixture[str]) -> None:
    code = preflight.main(["budget", "--total-bytes", "1000000000", "--override", override])
    assert code == 1
    assert "REFUSED" in capsys.readouterr().err


def test_non_positive_ram_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        preflight.compute_budget_mib(0)


def test_budget_command_prints_the_value(capsys: pytest.CaptureFixture[str]) -> None:
    assert preflight.main(["budget", "--total-bytes", "34053414912"]) == 0
    assert capsys.readouterr().out.strip() == "12990"


# -- verify -------------------------------------------------------------------


@pytest.fixture
def server_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp cwd whose `.env` names a production database, as a careless copy would."""
    _write(tmp_path, f"DATABASE_URL={SENTINEL}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("WORKER_STORE_BACKEND", "disk")
    monkeypatch.setenv("CRAWL_MEMORY_BUDGET_MIB", "12990")
    monkeypatch.setenv("AUTH_OPERATOR_STORE_PATH", str(tmp_path / ".operators"))
    return tmp_path


def test_control_without_blanks_the_dotenv_database_is_configured(server_env: Path) -> None:
    """Fail-before: the guard is what turns this False, not the test setup."""
    assert get_postgres_settings().is_configured() is True
    assert preflight.main(["verify", "--expect-budget", "12990"]) == 1


def test_empty_process_values_override_the_dotenv_database(
    server_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for key in BLANKED:
        monkeypatch.setenv(key, "")
    assert get_postgres_settings().is_configured() is False
    reset_postgres_settings_cache()
    assert preflight.main(["verify", "--expect-budget", "12990"]) == 0
    captured = capsys.readouterr()
    facts = json.loads(captured.out)
    assert facts["postgres_configured"] is False
    assert facts["crawl_memory_budget_mib"] == 12990
    assert facts["fair_share_mib"] == 12990 // facts["max_concurrent_crawls"]
    assert facts["operator_store_empty"] is True
    assert "hunter2" not in captured.out + captured.err


def test_budget_mismatch_is_refused(server_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in BLANKED:
        monkeypatch.setenv(key, "")
    assert preflight.main(["verify", "--expect-budget", "4096"]) == 1


def test_production_environment_is_refused(
    server_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for key in BLANKED:
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert preflight.main(["verify", "--expect-budget", "12990"]) == 1
    assert "hunter2" not in capsys.readouterr().err


def test_postgres_worker_store_in_env_is_refused(
    server_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in BLANKED:
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("WORKER_STORE_BACKEND", "postgres")
    assert preflight.main(["verify", "--expect-budget", "12990"]) == 1


# -- ui-deps ------------------------------------------------------------------


def _ui_dir(root: Path, *, installed: bool, lock_newer: bool) -> Path:
    """A `rankuno-ui` with a real `node_modules`, current or stale."""
    import os

    ui = root / "ui"
    modules = ui / "node_modules"
    modules.mkdir(parents=True)
    lock = ui / "package-lock.json"
    lock.write_text("{}", encoding="utf-8")
    if installed:
        marker = modules / ".package-lock.json"
        marker.write_text("{}", encoding="utf-8")
        older, newer = 1_700_000_000, 1_700_000_100
        os.utime(marker, (older, older) if lock_newer else (newer, newer))
        os.utime(lock, (newer, newer) if lock_newer else (older, older))
    return ui


def _junction_ui(root: Path, *, installed: bool, lock_newer: bool) -> Path:
    """A `rankuno-ui` whose `node_modules` is a junction to a real folder elsewhere."""
    import _winapi  # type: ignore[import-not-found]

    target_ui = _ui_dir(root / "target", installed=installed, lock_newer=False)
    ui = root / "linked"
    ui.mkdir()
    lock = ui / "package-lock.json"
    lock.write_text("{}", encoding="utf-8")
    import os

    stamp = 1_700_000_200 if lock_newer else 1_600_000_000
    os.utime(lock, (stamp, stamp))
    _winapi.CreateJunction(str(target_ui / "node_modules"), str(ui / "node_modules"))
    return ui


def test_current_dependencies_need_no_install(tmp_path: Path) -> None:
    ui = _ui_dir(tmp_path, installed=True, lock_newer=False)
    assert preflight.ui_dependency_action(ui) == preflight.UI_DEPS_CURRENT


@pytest.mark.parametrize(("installed", "lock_newer"), [(False, False), (True, True)])
def test_stale_real_folder_is_installed(tmp_path: Path, installed: bool, lock_newer: bool) -> None:
    ui = _ui_dir(tmp_path, installed=installed, lock_newer=lock_newer)
    assert preflight.ui_dependency_action(ui) == preflight.UI_DEPS_INSTALL


def test_missing_node_modules_is_installed(tmp_path: Path) -> None:
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "package-lock.json").write_text("{}", encoding="utf-8")
    assert preflight.ui_dependency_action(ui) == preflight.UI_DEPS_INSTALL


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_stale_junction_is_refused_and_its_target_left_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The incident: npm ci through a junction emptied the target checkout."""
    ui = _junction_ui(tmp_path, installed=True, lock_newer=True)
    target_files = sorted(p.name for p in (tmp_path / "target" / "ui" / "node_modules").iterdir())
    with pytest.raises(preflight.LinkedNodeModulesError, match="link to another folder"):
        preflight.ui_dependency_action(ui)
    assert preflight.main(["ui-deps", "--ui-dir", str(ui)]) == 1
    captured = capsys.readouterr()
    assert "refusing to reinstall through it" in captured.err
    assert "install" not in captured.out
    assert sorted(p.name for p in (tmp_path / "target" / "ui" / "node_modules").iterdir()) == (
        target_files
    )


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_broken_junction_is_refused(tmp_path: Path) -> None:
    ui = _junction_ui(tmp_path, installed=False, lock_newer=False)
    with pytest.raises(preflight.LinkedNodeModulesError):
        preflight.ui_dependency_action(ui)


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_current_junction_is_used_as_is(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A build only reads node_modules, so a current link needs nothing done to it."""
    ui = _junction_ui(tmp_path, installed=True, lock_newer=False)
    assert preflight.main(["ui-deps", "--ui-dir", str(ui)]) == 0
    assert capsys.readouterr().out.strip() == preflight.UI_DEPS_CURRENT


def test_launcher_installs_only_on_the_preflight_answer() -> None:
    """Parse-level guard: the old in-PowerShell staleness rule must not come back."""
    script = (Path(preflight.__file__).parent / "run_local.ps1").read_text(encoding="utf-8")
    assert "(Get-Item $installed).LastWriteTimeUtc" not in script
    assert script.count("'ui-deps'") == 2
    install_branch = script.index("if ($deps.Out -eq 'install') {")
    assert script.index("@('ci')") > install_branch
    assert script.count("@('ci')") == 1


# -- the launcher itself --------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell parser is Windows-only here")
def test_launcher_parses_without_errors() -> None:
    import subprocess

    script = Path(preflight.REPO_ROOT) / "scripts" / "run_local.ps1"
    command = (
        "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{script}', [ref]$null, [ref]$e); $e.Count"
    )
    result = subprocess.run(  # noqa: S603 - fixed command, no user input
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert result.stdout.strip() == "0"
