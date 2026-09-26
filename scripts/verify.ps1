<#
.SYNOPSIS
    SDLC Step 7 - Automated Verification.

.DESCRIPTION
    Runs the full quality gate: format check, lint, type check, tests with
    coverage. This is the exact set of checks CI runs, so a green run here means
    a green run there.

    No task may be reported as complete until this script exits zero.

.EXAMPLE
    .\scripts\verify.ps1
    .\scripts\verify.ps1 -Fix    # auto-fix formatting and lint issues first
#>
[CmdletBinding()]
param(
    [switch]$Fix,

    # Wall-clock ceiling for the UI test stage, in seconds.
    #
    # Not a performance budget - the whole suite measured 67-71s per run on a
    # 20-core workstation, so this is roughly 8x headroom. It exists because a
    # hanging gate is worse than a failing one: `NewCrawlWizard.test.tsx`
    # shipped with a store mock that
    # re-entered a useEffect forever, the Vitest worker was killed at ~3 GB, and
    # Vitest does not exit after `Worker exited unexpectedly` - it waits on a
    # worker that is gone. This script then never printed a verdict and never
    # returned, so no operator and no CI job could tell a slow run from a dead
    # one. Raise it if the suite genuinely grows; do not remove it.
    [int]$UiTimeoutSeconds = 600
)

$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Error 'No .venv found. Run .\scripts\bootstrap.ps1 first.'
}

$failures = @()

function Invoke-Gate {
    param([string]$Name, [string[]]$Arguments)

    Write-Host ''
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) {
        $script:failures += $Name
        Write-Host "FAILED: $Name" -ForegroundColor Red
    } else {
        Write-Host "PASSED: $Name" -ForegroundColor Green
    }
}

if ($Fix) {
    Write-Host 'Applying automatic fixes...' -ForegroundColor Yellow
    & $python -m ruff format .
    & $python -m ruff check . --fix
}

function Invoke-UiGate {
    <#
      Component tests for the React app.

      A separate function because `Invoke-Gate` runs everything through the
      venv's python, and this needs node. Kept in the same gate because the two
      halves of this product ship together: `tsc` and `vite build` verify types
      and bundling and are blind to a component that throws on mount, which is
      how cycle 0021 blanked the whole dashboard and cycle 0029 shipped an
      upload control wired to nothing.

      Skipped rather than failed when node is absent. A Python-only contributor
      should not be blocked by a missing toolchain — but the skip is announced
      in yellow and is not counted as a pass, because a check that did not run
      has not protected anything.
    #>
    $ui = Join-Path $RepoRoot 'rankuno-ui'
    Write-Host ''
    Write-Host '=== UI Component Tests ===' -ForegroundColor Cyan

    # `node` is frequently not on PATH on Windows even when it is installed;
    # the default installer puts it here and does not always update the
    # environment for non-interactive shells.
    $node = (Get-Command node -ErrorAction SilentlyContinue).Source
    if (-not $node) {
        $fallback = Join-Path $env:LOCALAPPDATA 'Programs/nodejs/node.exe'
        if (Test-Path $fallback) {
            $node = $fallback
            $env:PATH = (Split-Path $fallback) + ';' + $env:PATH
        }
    }

    if (-not $node) {
        Write-Host 'SKIPPED: UI Component Tests (node not found)' -ForegroundColor Yellow
        return
    }
    if (-not (Test-Path (Join-Path $ui 'node_modules/vitest'))) {
        Write-Host 'SKIPPED: UI Component Tests (run npm install in rankuno-ui)' -ForegroundColor Yellow
        return
    }

    # Run as a child process we hold the handle to, rather than with the call
    # operator. `&` blocks with no way back, so a hanging test file hangs the
    # gate — which is what this replaces.
    #
    # Built through `ProcessStartInfo` and not `Start-Process -PassThru`,
    # because that cmdlet does not keep the process handle and the object it
    # returns reports `$null` for `ExitCode` even after a clean exit. Measured:
    # a 473-test run that passed came back with `ExitCode` null, `$null -ne 0`
    # was true, and this stage announced FAILED on a green suite. Owning the
    # handle is what makes the exit code real (verified 0 on pass, 1 on fail).
    #
    # No stream redirection: the child inherits this console, so test progress
    # and any failure detail appear live exactly as they did before. (The
    # `--reporter=dot` argument is carried over unchanged from the previous
    # invocation; note that the `reporters` setting in vite.config.ts appears to
    # win over it in Vitest 2.1, so the output is verbose either way. That was
    # true before this change too.)
    #
    # The heap cap turns a runaway render loop into a fast OOM instead of a
    # process that grows until the workstation swaps; the timeout then collects
    # it. Both are needed: the cap bounds the damage, the timeout bounds the
    # wait.
    $previousNodeOptions = $env:NODE_OPTIONS
    if ([string]::IsNullOrWhiteSpace($previousNodeOptions)) {
        $env:NODE_OPTIONS = '--max-old-space-size=2048'
    } else {
        $env:NODE_OPTIONS = "$previousNodeOptions --max-old-space-size=2048"
    }

    try {
        $vitest = Join-Path $ui 'node_modules\.bin\vitest.cmd'
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        # A .cmd is not an executable image, so it goes through the shell. `/s`
        # with the whole command in one outer pair of quotes is the form cmd
        # parses correctly when the path itself is quoted.
        $psi.FileName = $env:ComSpec
        $psi.Arguments = '/s /c "' + '"' + $vitest + '" run --reporter=dot"'
        $psi.WorkingDirectory = $ui
        $psi.UseShellExecute = $false
        $proc = [System.Diagnostics.Process]::Start($psi)

        if ($proc.WaitForExit($UiTimeoutSeconds * 1000)) {
            $code = $proc.ExitCode
        } else {
            # Kill the tree, not just the launcher: cmd -> node -> one tinypool
            # worker per file. Stopping the cmd shell alone would orphan a
            # multi-gigabyte node process that then starves every later stage of
            # this same gate, and survives the run that spawned it.
            & taskkill.exe /T /F /PID $proc.Id 2>&1 | Out-Null
            $code = 124
            Write-Host ''
            Write-Host ("TIMED OUT after ${UiTimeoutSeconds}s - UI test process tree killed (PID " + $proc.Id + ').') -ForegroundColor Red
            Write-Host 'A hanging test file is a defect, not a slow one. Bisect with: npx vitest run <file>' -ForegroundColor Yellow
        }
    } finally {
        $env:NODE_OPTIONS = $previousNodeOptions
    }

    if ($code -ne 0) {
        $script:failures += 'UI Component Tests'
        Write-Host 'FAILED: UI Component Tests' -ForegroundColor Red
    } else {
        Write-Host 'PASSED: UI Component Tests' -ForegroundColor Green
    }
}

Invoke-Gate 'Format'      @('-m', 'ruff', 'format', '--check', '.')
Invoke-Gate 'Lint'        @('-m', 'ruff', 'check', '.')
Invoke-Gate 'Type check'  @('-m', 'mypy', 'src')
Invoke-Gate 'Tests'       @('-m', 'pytest', '--cov=src', '--cov-report=term-missing')
Invoke-UiGate

Write-Host ''
if ($failures.Count -gt 0) {
    Write-Host ('VERIFICATION FAILED: ' + ($failures -join ', ')) -ForegroundColor Red
    Write-Host 'Do not report this task as complete.' -ForegroundColor Red
    exit 1
}

Write-Host 'ALL GATES PASSED.' -ForegroundColor Green
Write-Host 'Next: SDLC Step 8 - README & architecture drift audit.' -ForegroundColor Cyan
exit 0
