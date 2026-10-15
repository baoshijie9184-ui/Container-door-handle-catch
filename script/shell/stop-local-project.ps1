[CmdletBinding()]
param([switch]$ApplicationsOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$logRoot = Join-Path $projectRoot 'work/middlewares'
$names = @('agent-ui','frontend','backend')
if (-not $ApplicationsOnly) { $names += @('mem0','chroma','kafka') }
foreach ($name in $names) {
    $recordFile = Join-Path $logRoot "$name.process.json"
    if (-not (Test-Path -LiteralPath $recordFile)) { Write-Output "$name has no project process record; skipped"; continue }
    $record = Get-Content -LiteralPath $recordFile -Raw | ConvertFrom-Json
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.pid)" -ErrorAction SilentlyContinue
    if (-not $process) { Write-Output "$name already stopped"; continue }
    # PowerShell 7.5+ auto-converts JSON ISO dates, while Windows PowerShell keeps strings.
    $recordTime = if ($record.createdAt -is [DateTime]) { $record.createdAt.ToUniversalTime() } else {
        [DateTime]::Parse($record.createdAt, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
    }
    if ($process.CreationDate.ToUniversalTime().Ticks -ne $recordTime.Ticks -or $process.ExecutablePath -ne $record.executable) {
        Write-Warning "$name process identity changed; skipped"
        continue
    }
    Stop-Process -Id $record.pid
    Write-Output "$name stopped"
}
Write-Output 'Shared MySQL and Redis Windows services are left running. Project data is retained.'
