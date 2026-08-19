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
    [switch]$Fix
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

    Push-Location $ui
    try {
        & (Join-Path $ui 'node_modules/.bin/vitest.cmd') run --reporter=dot
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
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
