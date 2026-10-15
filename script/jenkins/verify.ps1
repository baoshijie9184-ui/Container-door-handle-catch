param([Parameter(Mandatory = $true)][string]$PythonExe)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location -LiteralPath $root
New-Item -ItemType Directory -Force -Path artifacts | Out-Null

function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Check failed: $Command (exit $LASTEXITCODE)" }
}

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw 'PYTHON_EXE must point to an existing isolated test environment.' }
Invoke-Checked 'mvn.cmd' @('-B', '-ntp', 'clean', 'verify')
Invoke-Checked $PythonExe @('-m', 'pytest', 'tests_python', '-q', '--junitxml=artifacts/python-tests.xml')
Invoke-Checked 'node.exe' (@('--test') + @(Get-ChildItem -LiteralPath frontend/tests -Filter '*.test.cjs' | ForEach-Object FullName))
Invoke-Checked 'node.exe' (@('--test') + @(Get-ChildItem -LiteralPath frontend-agent/src -Filter '*.test.js' | ForEach-Object FullName))
foreach ($frontend in @('frontend', 'frontend-agent')) {
    Push-Location -LiteralPath (Join-Path $root $frontend)
    try {
        Invoke-Checked 'npm.cmd' @('ci', '--no-audit', '--no-fund')
        Invoke-Checked 'npm.cmd' @('run', 'build')
    } finally { Pop-Location }
}
