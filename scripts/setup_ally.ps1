# Windows PowerShell 5.1 bootstrap. No permanent execution-policy or PATH change.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolsRoot = Join-Path $projectRoot '.ally-tools'
$stage = $null
try {
    $architecture = [Environment]::GetEnvironmentVariable('PROCESSOR_ARCHITEW6432')
    if ([string]::IsNullOrWhiteSpace($architecture)) { $architecture = $env:PROCESSOR_ARCHITECTURE }
    if ($architecture -ne 'AMD64') { throw 'This setup supports Windows Intel/AMD 64-bit.' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime-downloads.json') -Raw | ConvertFrom-Json
    New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
    $uvRoot = Join-Path $toolsRoot 'uv'
    $uv = Join-Path $uvRoot 'uv.exe'
    $ready = $false
    if (Test-Path -LiteralPath $uv -PathType Leaf) {
        $version = & $uv --version
        $ready = ($LASTEXITCODE -eq 0 -and ($version -split '\s+')[1] -eq $manifest.uv_version)
    }
    if (!$ready) {
        Write-Host 'Preparing installation tool (Internet access required)...'
        $stage = Join-Path $toolsRoot ('.uv-stage-' + [guid]::NewGuid().ToString())
        New-Item -ItemType Directory -Path $stage | Out-Null
        $archive = Join-Path $stage 'uv.zip'
        $spec = $manifest.platforms.'windows-x64'.uv
        Invoke-WebRequest -UseBasicParsing -Uri $spec.url -OutFile $archive
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $spec.sha256) {
            throw 'SHA256 verification failed. Run Setup again.'
        }
        $expanded = Join-Path $stage 'expanded'
        Expand-Archive -LiteralPath $archive -DestinationPath $expanded
        $binaries = @(Get-ChildItem -LiteralPath $expanded -Recurse -Filter uv.exe -File)
        if ($binaries.Count -ne 1) { throw 'Installation tool archive is incomplete.' }
        $previous = Join-Path $stage 'previous'
        if (Test-Path -LiteralPath $uvRoot) { Move-Item -LiteralPath $uvRoot -Destination $previous }
        try {
            Move-Item -LiteralPath $binaries[0].Directory.FullName -Destination $uvRoot
        } catch {
            if (Test-Path -LiteralPath $previous) { Move-Item -LiteralPath $previous -Destination $uvRoot }
            throw
        }
    }
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $toolsRoot 'python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $toolsRoot 'python-bin'
    $env:UV_CACHE_DIR = Join-Path $toolsRoot 'cache'
    $env:UV_NO_MODIFY_PATH = '1'
    $env:UV_PYTHON_INSTALL_BIN = '0'
    $env:UV_PYTHON_INSTALL_REGISTRY = '0'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONUNBUFFERED = '1'
    foreach ($name in @('VIRTUAL_ENV', 'PYTHONHOME', 'PYTHONPATH', 'UV_PROJECT_ENVIRONMENT')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    Set-Location -LiteralPath $projectRoot
    & $uv run --no-project --no-config --managed-python --python $manifest.python_version (Join-Path $PSScriptRoot 'setup_ally.py') @args
    if ($LASTEXITCODE -ne 0) { throw 'Setup did not complete. Check the message above, then run Setup again.' }
    exit 0
} catch {
    Write-Host ('Setup failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($stage -and (Test-Path -LiteralPath $stage)) { Remove-Item -LiteralPath $stage -Force -Recurse }
}
