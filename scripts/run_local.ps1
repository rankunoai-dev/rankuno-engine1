<#
.SYNOPSIS
    Run the full Rankuno site (API plus built React UI) on this workstation for
    large crawls, against a local-only job store.

.DESCRIPTION
    One command, one process, one origin: uvicorn serves the API and the built
    UI on 127.0.0.1. The Railway container caps memory; this workstation does
    not, so the crawl memory budget is sized from physical RAM (40%, clamped to
    256-65536 MiB) instead of the container default.

    The guard matters more than the convenience. A server that saw a production
    DATABASE_URL would pick PostgresJobStore, and its startup orphan recovery
    would mark every crawl running on Railway as interrupted. So, in order:

      1. Refuse if .env / .env.local names a production-reaching key (by name,
         never printing a value).
      2. Compute the memory budget.
      3. Build the child environment: production database keys set to "" (an
         empty process value beats dotenv and counts as unset), development,
         disk worker store, the budget.
      4. Prove it: run Python in that exact environment and require
         is_configured() == False before anything listens.
      5. Build the UI if it is missing or stale, then check no secret name was
         inlined.
      6. Generate the per-run session secret (and, on an empty operator store
         only, the bootstrap password), in the child environment only.
      7. Start uvicorn on loopback with one worker.

    Local data (.jobs, .operators, .orgs, rankuno-ui/dist) lands in the checkout
    this script lives in. It is never synced with production.

.PARAMETER Port
    Loopback port to serve on. Default 8000.

.PARAMETER MemoryBudgetMiB
    Explicit CRAWL_MEMORY_BUDGET_MIB, a whole number 256-65536. Overrides the
    RAM-derived value.

.PARAMETER Rebuild
    Rebuild the UI even if dist looks current.

.PARAMETER CheckOnly
    Run every guard, report the configuration in force, and exit without
    building or serving.

.PARAMETER BootstrapOperatorId
    Operator created on the first run, when the operator store is empty.

.PARAMETER PromptPassword
    Type the bootstrap password instead of having one generated.

.PARAMETER Python
    Python interpreter to use when this checkout has no .venv (a git worktree,
    for example). Defaults to <repo>\.venv\Scripts\python.exe.

.EXAMPLE
    .\scripts\run_local.ps1
    .\scripts\run_local.ps1 -Port 8899 -MemoryBudgetMiB 16000
    .\scripts\run_local.ps1 -CheckOnly
#>
[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)][int]$Port = 8000,
    [string]$MemoryBudgetMiB = '',
    [switch]$Rebuild,
    [switch]$CheckOnly,
    [ValidatePattern('^[a-z0-9_-]{1,64}$')][string]$BootstrapOperatorId = 'admin',
    [switch]$PromptPassword,
    [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $RepoRoot
$UiDir = Join-Path $RepoRoot 'rankuno-ui'
$DistDir = Join-Path $UiDir 'dist'
$BuildStamp = Join-Path $DistDir '.rankuno-local-build'
$ApiBase = '/api/v1'
# Names only. The values are generated after the build, so they cannot be in it;
# this checks nothing that names them was inlined either.
$SecretNames = @('AUTH_SESSION_SECRET', 'AUTH_BOOTSTRAP_OPERATOR_PASSWORD', 'DATABASE_URL', 'POSTGRES_PASSWORD')

function Stop-Launch([string]$Message) {
    Write-Host "REFUSED: $Message" -ForegroundColor Red
    exit 1
}

function Quote-Arg([string]$Value) {
    if ($Value -match '[\s"]') { return '"' + ($Value -replace '"', '\"') + '"' }
    return $Value
}

function New-StartInfo([string]$FileName, [string[]]$Arguments, [hashtable]$Environment, [string]$WorkDir) {
    # ProcessStartInfo rather than $env: the child gets its environment without
    # the launcher's own environment ever holding a generated secret.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FileName
    $psi.Arguments = ($Arguments | ForEach-Object { Quote-Arg $_ }) -join ' '
    $psi.UseShellExecute = $false
    $psi.WorkingDirectory = $WorkDir
    foreach ($key in $Environment.Keys) { $psi.EnvironmentVariables[$key] = [string]$Environment[$key] }
    return $psi
}

function Invoke-Child([string]$FileName, [string[]]$Arguments, [hashtable]$Environment, [string]$WorkDir = $RepoRoot, [switch]$Capture) {
    $psi = New-StartInfo $FileName $Arguments $Environment $WorkDir
    $psi.RedirectStandardOutput = [bool]$Capture
    $proc = [System.Diagnostics.Process]::Start($psi)
    $out = if ($Capture) { $proc.StandardOutput.ReadToEnd() } else { '' }
    $proc.WaitForExit()
    return [pscustomobject]@{ Code = $proc.ExitCode; Out = $out.Trim() }
}

function New-RandomText([int]$Length) {
    $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $chars = New-Object System.Text.StringBuilder
    $buffer = New-Object byte[] 1
    # Rejection sampling: a plain modulo would bias the low characters.
    $limit = 256 - (256 % $alphabet.Length)
    while ($chars.Length -lt $Length) {
        $rng.GetBytes($buffer)
        if ($buffer[0] -lt $limit) { [void]$chars.Append($alphabet[$buffer[0] % $alphabet.Length]) }
    }
    $rng.Dispose()
    return $chars.ToString()
}

function New-HexSecret([int]$Bytes) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buffer = New-Object byte[] $Bytes
    $rng.GetBytes($buffer)
    $rng.Dispose()
    return -join ($buffer | ForEach-Object { $_.ToString('x2') })
}

function Test-UiStale {
    $index = Join-Path $DistDir 'index.html'
    if ($Rebuild) { return 'rebuild requested' }
    if (-not (Test-Path $index)) { return 'dist is missing' }
    if (-not (Test-Path $BuildStamp) -or (Get-Content $BuildStamp -Raw).Trim() -ne $ApiBase) {
        return "dist was not built by this launcher with VITE_API_BASE=$ApiBase"
    }
    $builtAt = (Get-Item $index).LastWriteTimeUtc
    $inputs = @(Get-ChildItem (Join-Path $UiDir 'src') -Recurse -File)
    foreach ($name in 'index.html', 'package.json', 'package-lock.json', 'vite.config.ts', 'tsconfig.json') {
        $path = Join-Path $UiDir $name
        if (Test-Path $path) { $inputs += Get-Item $path }
    }
    $newer = $inputs | Where-Object { $_.LastWriteTimeUtc -gt $builtAt } | Select-Object -First 1
    if ($newer) { return "UI source changed since the last build ($($newer.Name))" }
    return ''
}

# -- 0. Interpreter --------------------------------------------------------------
if (-not $Python) {
    $Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $Python)) {
        Stop-Launch ("No virtual environment at $Python. Run .\scripts\bootstrap.ps1, or pass " +
            '-Python <path to python.exe> to use another checkout''s venv.')
    }
} elseif (-not (Test-Path $Python)) {
    Stop-Launch "-Python $Python does not exist."
}
$Preflight = Join-Path $RepoRoot 'scripts\local_preflight.py'

# -- 1. Dotenv guard (names only) ------------------------------------------------
$scan = Invoke-Child $Python @($Preflight, 'scan', '--root', $RepoRoot) @{}
if ($scan.Code -ne 0) { Stop-Launch 'a dotenv file names a production-reaching key (see above).' }

# -- 2. Memory budget ------------------------------------------------------------
$totalBytes = [int64](Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
$budgetArgs = @($Preflight, 'budget', '--total-bytes', [string]$totalBytes)
if ($MemoryBudgetMiB -ne '') { $budgetArgs += @('--override', $MemoryBudgetMiB) }
$budget = Invoke-Child $Python $budgetArgs @{} -Capture
if ($budget.Code -ne 0) { Stop-Launch '-MemoryBudgetMiB must be a whole number from 256 to 65536.' }
$budgetMiB = [int]$budget.Out

# -- 3. Child environment --------------------------------------------------------
$childEnv = @{
    DATABASE_URL            = ''
    POSTGRES_URL            = ''
    DATABASE_PRIVATE_URL    = ''
    POSTGRES_PASSWORD       = ''
    REDIS_URL               = ''
    REDIS_PRIVATE_URL       = ''
    WORKER_STORE_BACKEND    = 'disk'
    ENVIRONMENT             = 'development'
    CRAWL_MEMORY_BUDGET_MIB = [string]$budgetMiB
}

# -- 4. Prove the guard ----------------------------------------------------------
$verify = Invoke-Child $Python @($Preflight, 'verify', '--expect-budget', [string]$budgetMiB) $childEnv -Capture
if ($verify.Code -ne 0) { Stop-Launch 'the guard did not hold in the server environment (see above).' }
$facts = $verify.Out | ConvertFrom-Json
$ramMiB = [math]::Floor($totalBytes / 1MB)
$source = if ($MemoryBudgetMiB -ne '') { 'explicit -MemoryBudgetMiB' } else { "40% of $ramMiB MiB physical RAM" }
Write-Host 'Pre-flight passed:' -ForegroundColor Green
Write-Host "  postgres configured : $($facts.postgres_configured)"
Write-Host "  environment         : $($facts.environment)"
Write-Host "  worker store        : $($facts.worker_store_backend)"
Write-Host "  memory budget       : $($facts.crawl_memory_budget_mib) MiB ($source)"
Write-Host "  concurrent crawls   : $($facts.max_concurrent_crawls) (fair share $($facts.fair_share_mib) MiB each)"
Write-Host "  job store           : $($facts.job_store)"
Write-Host "  operator store empty: $($facts.operator_store_empty)"

$staleReason = Test-UiStale
if ($CheckOnly) {
    $uiState = if ($staleReason) { "would build ($staleReason)" } else { 'up to date' }
    Write-Host "  UI                  : $uiState"
    Write-Host "  would serve         : http://127.0.0.1:$Port/"
    Write-Host 'CheckOnly: nothing built, nothing started.' -ForegroundColor Cyan
    exit 0
}

# -- 5. UI build -----------------------------------------------------------------
if ($staleReason) {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $node -or -not $npm) { Stop-Launch "Node.js 18+ is needed to build the UI ($staleReason). Install it from nodejs.org." }
    $nodeMajor = [int]((& $node.Source --version).TrimStart('v').Split('.')[0])
    if ($nodeMajor -lt 18) { Stop-Launch "Node.js 18+ is needed to build the UI; found $nodeMajor." }
    $lockFile = Join-Path $UiDir 'package-lock.json'
    $installed = Join-Path $UiDir 'node_modules\.package-lock.json'
    if (-not (Test-Path $installed) -or (Get-Item $lockFile).LastWriteTimeUtc -gt (Get-Item $installed).LastWriteTimeUtc) {
        Write-Host 'Installing UI dependencies (npm ci)...' -ForegroundColor Cyan
        $ci = Invoke-Child $npm.Source @('ci') @{} $UiDir
        if ($ci.Code -ne 0) { Stop-Launch 'npm ci failed (see above).' }
    }
    Write-Host "Building the UI ($staleReason)..." -ForegroundColor Cyan
    $build = Invoke-Child $npm.Source @('run', 'build') @{ VITE_API_BASE = $ApiBase } $UiDir
    if ($build.Code -ne 0) { Stop-Launch 'the UI build failed (see above).' }
    Set-Content -Path $BuildStamp -Value $ApiBase -Encoding ASCII
    $leaked = Get-ChildItem $DistDir -Recurse -File |
        Select-String -Pattern $SecretNames -SimpleMatch -List
    if ($leaked) { Stop-Launch "a secret name was inlined into the UI bundle ($($leaked[0].Path))." }
}

# -- 6. Secrets, child environment only ------------------------------------------
# A per-run session key, not the development per-process default: that default
# only applies when AUTH_SESSION_SECRET is unset, and a dotenv carrying the
# production key would make tokens minted here verify in production.
$childEnv['AUTH_SESSION_SECRET'] = New-HexSecret 32
$bootstrapPassword = $null
if ($facts.operator_store_empty) {
    if ($PromptPassword) {
        $secure = Read-Host "Password for the first operator '$BootstrapOperatorId'" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $bootstrapPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        if (-not $bootstrapPassword) { Stop-Launch 'an empty password cannot seed an operator.' }
    } else {
        $bootstrapPassword = New-RandomText 24
        Write-Host ''
        Write-Host 'First run: no operator exists yet. Log in with these; they are shown once' -ForegroundColor Yellow
        Write-Host 'and never written to disk. Add more with scripts\create_operator.py.' -ForegroundColor Yellow
        Write-Host "  operator id: $BootstrapOperatorId"
        Write-Host "  password   : $bootstrapPassword"
        Write-Host ''
    }
    $childEnv['AUTH_BOOTSTRAP_OPERATOR_ID'] = $BootstrapOperatorId
    $childEnv['AUTH_BOOTSTRAP_OPERATOR_PASSWORD'] = $bootstrapPassword
}

# -- 7. Serve --------------------------------------------------------------------
try {
    $probe = New-Object System.Net.Sockets.TcpListener ([System.Net.IPAddress]::Loopback, $Port)
    $probe.Start()
    $probe.Stop()
} catch {
    Stop-Launch "port $Port on 127.0.0.1 is in use. Pass -Port <n> to use another."
}

$serverArgs = @('-m', 'uvicorn', '--factory', 'src.api.server:create_app',
    '--host', '127.0.0.1', '--port', [string]$Port, '--workers', '1')
$psi = New-StartInfo $Python $serverArgs $childEnv $RepoRoot
$server = [System.Diagnostics.Process]::Start($psi)
# The child has its copy; drop ours.
$psi.EnvironmentVariables.Remove('AUTH_SESSION_SECRET')
$psi.EnvironmentVariables.Remove('AUTH_BOOTSTRAP_OPERATOR_PASSWORD')
$childEnv.Remove('AUTH_SESSION_SECRET')
$childEnv.Remove('AUTH_BOOTSTRAP_OPERATOR_PASSWORD')
$bootstrapPassword = $null

Write-Host "Serving http://127.0.0.1:$Port/ (server pid $($server.Id)). Ctrl+C to stop." -ForegroundColor Green
try {
    $server.WaitForExit()
} finally {
    if (-not $server.HasExited) {
        # Ctrl+C reaches the child too; give uvicorn its graceful shutdown first.
        if (-not $server.WaitForExit(10000)) { $server.Kill() }
    }
}
exit $server.ExitCode
