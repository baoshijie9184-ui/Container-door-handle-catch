#requires -Version 7.0
param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Retirement discovery only: no SQL/Redis connection, service changes, database
# startup, test execution, copying business files or deletion is implemented.
$projectRoot = 'D:\AI\lunwen1\DoorHandleCatch'
$allowedRoot = Join-Path $projectRoot 'work\jenkins'
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (-not $output.StartsWith($allowedRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
    (Test-Path -LiteralPath $output)) {
    throw 'Use a fresh output directory inside the project Jenkins control directory.'
}
if ($output.Substring($allowedRoot.Length + 1) -notmatch '^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}$') {
    throw 'The private report must use one new direct child of the Jenkins control directory.'
}
$ancestor = Get-Item -LiteralPath $allowedRoot -Force
while ($null -ne $ancestor) {
    if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked control directories are not accepted.' }
    $ancestor = $ancestor.Parent
}
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Windows administrator access is required to inventory the protected MySQL data directory.'
}

function Get-ClosedFileInventory([string]$Root) {
    $rootItem = Get-Item -LiteralPath $Root -Force
    if (-not $rootItem.PSIsContainer -or ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'A regular data directory is required.'
    }
    $stack = [Collections.Generic.Stack[string]]::new()
    $stack.Push($rootItem.FullName)
    $members = [Collections.Generic.List[object]]::new()
    while ($stack.Count -gt 0) {
        foreach ($entry in Get-ChildItem -LiteralPath $stack.Pop() -Force -ErrorAction Stop) {
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'A linked data entry requires separate review.' }
            if ($entry.PSIsContainer) { $stack.Push($entry.FullName); continue }
            if ($members.Count -ge 100000) { throw 'Local data inventory exceeded its file bound.' }
            $members.Add([ordered]@{
                path = [IO.Path]::GetRelativePath($rootItem.FullName, $entry.FullName).Replace('\', '/')
                bytes = [long]$entry.Length
                modifiedAtUtc = $entry.LastWriteTimeUtc.ToString('o')
            })
        }
    }
    return @($members.ToArray())
}

$services = @()
foreach ($name in @('MySQL83', 'Redis')) {
    $service = Get-CimInstance Win32_Service -Filter ("Name='" + $name + "'")
    if ($null -eq $service) { continue }
    $executable = if ($service.PathName -match '^"([^"]+)"') { $Matches[1] } else { ($service.PathName -split '\s+')[0] }
    $services += [ordered]@{ name = $service.Name; state = $service.State; startMode = $service.StartMode;
        processId = $service.ProcessId; executable = $executable }
}
$mysqlIni = 'C:\ProgramData\MySQL\MySQL Server 8.3\my.ini'
$mysqlRoot = $null
foreach ($line in Get-Content -LiteralPath $mysqlIni) {
    if ($line -match '^\s*datadir\s*=\s*(.+?)\s*$') { $mysqlRoot = $Matches[1].Trim('"') }
}
if (-not $mysqlRoot -or [IO.Path]::GetFullPath($mysqlRoot) -ne 'C:\ProgramData\MySQL\MySQL Server 8.3\Data') {
    throw 'The configured local MySQL directory differs from the reviewed installation.'
}
$mysqlFiles = @(Get-ClosedFileInventory $mysqlRoot)
$mysqlSchemas = @(Get-ChildItem -LiteralPath $mysqlRoot -Directory -Force | Select-Object -ExpandProperty Name)
$redisCandidates = @()
foreach ($base in @('D:\ruanjian\Redis', 'C:\Windows\System32')) {
    foreach ($name in @('dump.rdb', 'appendonly.aof')) {
        $path = Join-Path $base $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        $item = Get-Item -LiteralPath $path -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked Redis candidates require separate review.' }
        $redisCandidates += [ordered]@{ path = $item.FullName; bytes = [long]$item.Length;
            modifiedAtUtc = $item.LastWriteTimeUtc.ToString('o') }
    }
}
$report = [ordered]@{
    schema = 1; kind = 'doorhandle-local-runtime-discovery'; status = 'INVENTORIED_ONLY'
    observedAtUtc = [DateTimeOffset]::UtcNow.ToString('o'); elevated = $true
    scriptSha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    services = $services; mysqlDataDirectory = $mysqlRoot; mysqlSchemas = $mysqlSchemas
    mysqlFiles = $mysqlFiles; mysqlBytes = ($mysqlFiles | ForEach-Object { $_.bytes } | Measure-Object -Sum).Sum
    redisPersistenceCandidates = $redisCandidates
    databasesOpened = $false; testsExecuted = $false; servicesChanged = $false; sourceFilesChanged = $false
    note = 'Metadata captured while legacy services may be running; this is not a consistent database backup or deletion admission.'
}
New-Item -ItemType Directory -Path $output | Out-Null
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $output /inheritance:r /grant:r ('*' + $sid + ':(OI)(CI)F') '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Private control report permissions could not be established.' }
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $output 'inventory-private.json') -Encoding utf8
Write-Output ([pscustomobject]@{ status = $report.status; mysqlFiles = $mysqlFiles.Count;
    mysqlBytes = $report.mysqlBytes; projectSchemaPresent = ($mysqlSchemas -contains 'doorhandledb');
    servicesChanged = $false; sourceFilesChanged = $false } | ConvertTo-Json)
