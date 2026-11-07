#requires -Version 7.0
<#
One retirement export, not a development/test runtime or a migration result.
Do not run until the user explicitly approves this one local read-only SQL
exception. The acknowledgement flag records that decision; it cannot grant it.
Only the already running MySQL83 / 127.0.0.1:3306 / doorhandledb is accepted.
No service change, source deletion, local restore, cloud call or retry exists.

The private env uses the existing DB_USERNAME / DB_PASSWORD dotenv format.
The output remains private and local until fixed-source Jenkins uploads it and
independently restores/verifies it on ECS. Nothing here authorizes retirement.

References: https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html
https://dev.mysql.com/doc/refman/8.0/en/option-file-options.html
#>
param(
    [Parameter(Mandatory = $true)][string]$PrivateEnvFile,
    [Parameter(Mandatory = $true)][string]$UserAuthorizationReference,
    [switch]$AcknowledgeOneTimeLocalReadOnlyExport
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Require-Export([bool]$Condition, [string]$Message, [string]$Reason = 'EXPORT_GUARD_REJECTED') {
    if (-not $Condition) { $guardFailure = [InvalidOperationException]::new($Message); $guardFailure.Data['ExportReason'] = $Reason; throw $guardFailure }
}
function Assert-Unlinked([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        Require-Export (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Export paths cannot contain links or junctions.'
        $item = if ($item -is [IO.FileInfo]) { $item.Directory } else { $item.Parent }
    }
}
function Set-PrivateDirectory([string]$Path) {
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($script:owner)
    foreach ($sid in @($script:owner, [Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
    Require-Export (Get-Acl -LiteralPath $Path).AreAccessRulesProtected 'Export directory permissions were not protected.'
}
function Write-PrivateJson([string]$Path, $Value) {
    Require-Export (-not (Test-Path -LiteralPath $Path)) 'Export evidence is immutable; choose a fresh attempt.'
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 15), [Text.UTF8Encoding]::new($false))
}
function File-Sha([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Option-Value([string]$Value) {
    Require-Export (-not $Value.Contains([char]0)) 'Credential contains an unsupported character.'
    return '"' + $Value.Replace('\', '\\').Replace('"', '\"').Replace("`r", '\r').Replace("`n", '\n').Replace("`t", '\t') + '"'
}
function Assert-GlobalClientOptions {
    # --defaults-extra-file also reads global files. Refuse includes and any
    # client instruction outside this small closed list before starting a CLI.
    # MYSQL_TEST_LOGIN_FILE separately prevents reading a user's real login file.
    $safeKeys = @('host','port','user','password','protocol','socket','default-character-set',
        'max-allowed-packet','quick','no-auto-rehash','connect-timeout')
    foreach ($file in @("$env:WINDIR\my.ini", "$env:WINDIR\my.cnf", 'C:\my.ini', 'C:\my.cnf',
        (Join-Path $script:binaryRoot 'my.ini'), (Join-Path $script:binaryRoot 'my.cnf'))) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { continue }
        Assert-Unlinked $file
        Require-Export ((Get-Item -LiteralPath $file).Length -le 1048576) 'A global client option file exceeds its review bound.'
        $group = ''
        foreach ($line in [IO.File]::ReadAllLines($file)) {
            $text = $line.Trim()
            if (-not $text -or $text.StartsWith('#') -or $text.StartsWith(';')) { continue }
            Require-Export (-not $text.StartsWith('!')) 'Included global client options require separate review.'
            if ($text -match '^\[([^\]]+)\]$') { $group = $Matches[1].ToLowerInvariant(); continue }
            if ($group -notin @('client','mysql','mysqldump')) { continue }
            $key = (($text -split '=', 2)[0]).Trim().Replace('_', '-').ToLowerInvariant()
            Require-Export ($key -in $safeKeys) 'A global client option is outside the reviewed read-only export contract.'
        }
    }
}
function Get-ReviewedSource {
    $service = Get-CimInstance Win32_Service -Filter "Name='MySQL83'"
    $executable = 'C:\Program Files\MySQL\MySQL Server 8.3\bin\mysqld.exe'
    Require-Export ($null -ne $service -and $service.State -ceq 'Running' -and
        $service.PathName -match '^"?C:\\Program Files\\MySQL\\MySQL Server 8\.3\\bin\\mysqld\.exe(?:"|\s|$)') 'The reviewed MySQL83 service must already be running.'
    $parent = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $service.ProcessId)
    Require-Export ($null -ne $parent -and -not [string]::IsNullOrWhiteSpace($parent.ExecutablePath)) 'INSUFFICIENT_PROCESS_METADATA: service executable cannot be proven.' 'INSUFFICIENT_PROCESS_METADATA'
    Require-Export ($parent.ExecutablePath -ieq $executable) 'The actual service executable differs from the reviewed installation.'
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 3306 -ErrorAction SilentlyContinue)
    Require-Export ($listeners.Count -gt 0) 'NO_REVIEWED_TCP_LISTENER: the fixed source endpoint is not listening.' 'NO_REVIEWED_TCP_LISTENER'
    $workers = @()
    foreach ($pidValue in @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $worker = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $pidValue)
        Require-Export ($null -ne $worker -and -not [string]::IsNullOrWhiteSpace($worker.ExecutablePath)) 'INSUFFICIENT_PROCESS_METADATA: listener executable cannot be proven.' 'INSUFFICIENT_PROCESS_METADATA'
        Require-Export ($worker.ExecutablePath -ieq $executable -and
            ($worker.ProcessId -eq $service.ProcessId -or $worker.ParentProcessId -eq $service.ProcessId)) 'A listener is neither the reviewed service nor its proven direct mysqld child.'
        $workers += [ordered]@{ processId = [int]$worker.ProcessId; parentProcessId = [int]$worker.ParentProcessId;
            createdAtUtc = $worker.CreationDate.ToUniversalTime().ToString('o') }
    }
    Require-Export ($workers.Count -eq 1) 'The local source has multiple listener process identities.'
    return [pscustomobject]@{ serviceProcessId = [int]$service.ProcessId; worker = $workers[0] }
}
function Invoke-PrivateClient([string]$Executable, [string[]]$Arguments, [string]$OutputFile,
                              [string]$Sql = '', [long]$MaximumBytes = 1048576, [int]$TimeoutSeconds = 120) {
    Require-Export (-not (Test-Path -LiteralPath $OutputFile)) 'A client result already exists.'
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Executable
    $start.WorkingDirectory = $script:output
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardInputEncoding = [Text.UTF8Encoding]::new($false)
    foreach ($key in @($start.Environment.Keys)) {
        if ($key.StartsWith('MYSQL_', [StringComparison]::OrdinalIgnoreCase)) { $start.Environment.Remove($key) | Out-Null }
    }
    $start.Environment['MYSQL_TEST_LOGIN_FILE'] = $script:loginFile
    foreach ($argument in $Arguments) { $start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new(); $process.StartInfo = $start
    $stream = $null; $started = $false
    try {
        $stream = [IO.File]::Open($OutputFile, 'CreateNew', 'Write', 'None')
        Require-Export ($process.Start()) 'The existing export client could not start.'
        $started = $true
        if ($Sql) { $process.StandardInput.Write($Sql) }
        $process.StandardInput.Close()
        $clock = [Diagnostics.Stopwatch]::StartNew(); $buffer = [byte[]]::new(65536); $diagnosticBuffer = [byte[]]::new(8192)
        $bytes = 0L; $diagnosticBytes = 0L; $stdoutEnd = $false; $stderrEnd = $false
        $stdoutRead = $process.StandardOutput.BaseStream.ReadAsync($buffer, 0, $buffer.Length)
        $stderrRead = $process.StandardError.BaseStream.ReadAsync($diagnosticBuffer, 0, $diagnosticBuffer.Length)
        while (-not ($stdoutEnd -and $stderrEnd)) {
            Require-Export ($clock.Elapsed.TotalSeconds -le $TimeoutSeconds) 'The one-time export exceeded its time bound.'
            Require-Export ([IO.DriveInfo]::new('D:\').AvailableFreeSpace -ge $script:diskFloor) 'The one-time export reached its disk reserve.'
            $progressMade = $false
            if (-not $stdoutEnd -and $stdoutRead.IsCompleted) {
                $count = $stdoutRead.GetAwaiter().GetResult(); $progressMade = $true
                if ($count -eq 0) { $stdoutEnd = $true }
                else {
                    $bytes += $count
                    Require-Export ($bytes -le $MaximumBytes) 'The one-time export exceeded its byte bound.'
                    $stream.Write($buffer, 0, $count)
                    $stdoutRead = $process.StandardOutput.BaseStream.ReadAsync($buffer, 0, $buffer.Length)
                }
            }
            if (-not $stderrEnd -and $stderrRead.IsCompleted) {
                $count = $stderrRead.GetAwaiter().GetResult(); $progressMade = $true
                if ($count -eq 0) { $stderrEnd = $true }
                else {
                    $diagnosticBytes += $count
                    Require-Export ($diagnosticBytes -le 1048576) 'The client diagnostics exceeded the private bound.'
                    [Array]::Clear($diagnosticBuffer, 0, $diagnosticBuffer.Length) # Never print/archive raw diagnostics.
                    $stderrRead = $process.StandardError.BaseStream.ReadAsync($diagnosticBuffer, 0, $diagnosticBuffer.Length)
                }
            }
            if (-not $progressMade) { Start-Sleep -Milliseconds 25 }
        }
        Require-Export ($process.WaitForExit(10000)) 'The export client did not terminate.'
        Require-Export ($process.ExitCode -eq 0) 'The database client failed; no complete export is asserted.'
        $stream.Flush($true)
        return $bytes
    } finally {
        try {
            if ($started -and -not $process.HasExited) {
                # Only the process created above; never the shared mysqld service.
                $process.Kill($true); Require-Export ($process.WaitForExit(10000)) 'An owned export client did not stop.'
            }
        } finally { try { if ($null -ne $stream) { $stream.Dispose() } } finally { $process.Dispose() } }
    }
}
function Observe-Project([string]$Prefix) {
    $identityFile = Join-Path $script:output "$Prefix-identity-private.json"
    Invoke-PrivateClient $script:mysql ($script:clientArgs + @('--batch','--raw','--silent','--skip-column-names', '--skip-auto-rehash',
        '--init-command=SET SESSION TRANSACTION READ ONLY', '--database=doorhandledb')) $identityFile `
        "SELECT JSON_OBJECT('schema',DATABASE(),'serverUuid',@@server_uuid,'version',@@version,'port',@@port);" | Out-Null
    $identity = [IO.File]::ReadAllText($identityFile) | ConvertFrom-Json
    Require-Export ($identity.schema -ceq 'doorhandledb' -and $identity.version -match '^8\.3\.' -and $identity.port -eq 3306 -and
        $identity.serverUuid -match '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$') 'The actual connection is not the reviewed local MySQL83 project source.'
    $catalogFile = Join-Path $script:output "$Prefix-catalog-private.jsonl"
    Invoke-PrivateClient $script:mysql ($script:clientArgs + @('--batch','--raw','--silent','--skip-column-names','--skip-auto-rehash',
        '--init-command=SET SESSION TRANSACTION READ ONLY', '--database=doorhandledb')) $catalogFile `
        "SELECT JSON_OBJECT('table',TABLE_NAME,'kind',TABLE_TYPE,'engine',ENGINE,'collation',TABLE_COLLATION) FROM information_schema.TABLES WHERE TABLE_SCHEMA='doorhandledb' ORDER BY TABLE_NAME;" | Out-Null
    $catalog = @([IO.File]::ReadAllLines($catalogFile) | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
    Require-Export ($catalog.Count -gt 0 -and $catalog.Count -le 128) 'The source table catalogue exceeds the reviewed project bound.'
    foreach ($table in $catalog) {
        Require-Export ($table.table -match '^[A-Za-z_][A-Za-z0-9_]{0,63}$' -and $table.kind -ceq 'BASE TABLE' -and
            $table.engine -ceq 'InnoDB') 'Views, nontransactional tables or unusual identifiers need separate export review.'
    }
    $countSql = ($catalog | ForEach-Object {
        "SELECT JSON_OBJECT('table','" + $_.table + "','rows',COUNT(*)) FROM ``doorhandledb``.``" + $_.table + '`;'
    }) -join "`n"
    $countFile = Join-Path $script:output "$Prefix-row-counts-private.jsonl"
    Invoke-PrivateClient $script:mysql ($script:clientArgs + @('--batch','--raw','--silent','--skip-column-names','--skip-auto-rehash',
        '--init-command=SET SESSION TRANSACTION READ ONLY','--database=doorhandledb')) $countFile $countSql | Out-Null
    $counts = @([IO.File]::ReadAllLines($countFile) | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
    Require-Export ($counts.Count -eq $catalog.Count) 'The restricted row observation is incomplete.'
    for ($i = 0; $i -lt $counts.Count; $i++) {
        Require-Export ($counts[$i].table -ceq $catalog[$i].table -and $counts[$i].rows -is [ValueType] -and
            [long]$counts[$i].rows -ge 0) 'A restricted table row count is invalid.'
    }
    return [pscustomobject]@{ identity = $identity; catalog = $catalog; counts = $counts;
        identityFile = $identityFile; catalogFile = $catalogFile; countFile = $countFile }
}

$output = $null; $optionFile = $null; $loginFile = $null; $stage = 'AUTHORIZATION_REQUIRED'; $failure = $null; $reason = 'EXPORT_FAILED'
$diskFloor = [long](2GB + 256MB)
try {
    Require-Export ($IsWindows -and $AcknowledgeOneTimeLocalReadOnlyExport -and
        $UserAuthorizationReference -match '^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,180}$') 'Explicit user approval for this one local read-only export is required.' 'USER_AUTHORIZATION_REQUIRED'
    $stage = 'ADMINISTRATOR_METADATA_GATE'
    $principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    Require-Export ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Run only inside the separately approved administrator token; this script never elevates itself.' 'ADMINISTRATOR_TOKEN_REQUIRED'
    $project = 'D:\AI\lunwen1\DoorHandleCatch'
    Require-Export ((Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path -ceq $project) 'Use the reviewed project checkout.'
    $owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $private = [IO.Path]::GetFullPath($PrivateEnvFile)
    Require-Export ($private.StartsWith($project + '\', [StringComparison]::OrdinalIgnoreCase)) 'Use an existing private credential file inside the project.'
    Assert-Unlinked $private
    Require-Export ((Get-Item -LiteralPath $private).Length -le 1048576) 'Private credential input is too large.'
    $acl = Get-Acl -LiteralPath $private
    foreach ($rule in $acl.Access) {
        Require-Export ($rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -in
            @($owner.Value, 'S-1-5-18', 'S-1-5-32-544')) 'The existing credential file is readable by an unreviewed principal.'
    }
    & git -C $project check-ignore --quiet -- $private
    Require-Export ($LASTEXITCODE -eq 0) 'The private credential file must be Git ignored.'
    $binaryRoot = 'C:\Program Files\MySQL\MySQL Server 8.3'
    $mysql = Join-Path $binaryRoot 'bin/mysql.exe'; $dump = Join-Path $binaryRoot 'bin/mysqldump.exe'
    foreach ($file in @($mysql, $dump)) {
        Assert-Unlinked $file
        Require-Export ((Get-Item -LiteralPath $file).VersionInfo.ProductVersion -match '^8\.3\.') 'Use only the installed MySQL 8.3 clients.'
    }
    Assert-GlobalClientOptions
    $stage = 'LOCAL_SOURCE_METADATA_GATE'; $sourceProcess = Get-ReviewedSource
    $parent = Join-Path $project 'work/data-migration-20261107'; Assert-Unlinked $parent
    $output = Join-Path $parent ('local-mysql-export-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Path $output -ErrorAction Stop | Out-Null
    Set-PrivateDirectory $output
    Write-PrivateJson (Join-Path $output 'authorization-private.json') ([ordered]@{ userAuthorizationReference = $UserAuthorizationReference;
        oneTimeReadOnlyExceptionAcknowledged = $true; ownerSid = $owner.Value; serviceName = 'MySQL83'; sourceProcess = $sourceProcess })
    $stage = 'PRIVATE_INPUT_PREPARATION'
    $credentials = @{}
    foreach ($line in [IO.File]::ReadAllLines($private, [Text.UTF8Encoding]::new($false, $true))) {
        if ($line -notmatch '^\s*(?:export\s+)?(DB_USERNAME|DB_PASSWORD)\s*=(.*)$') { continue }
        $name = $Matches[1]; $value = $Matches[2].Trim()
        Require-Export (-not $credentials.ContainsKey($name)) 'Credential input has duplicate fields.'
        if ($value.Length -ge 2 -and $value[0] -eq $value[-1] -and $value[0] -in @('"', "'")) { $value = $value.Substring(1, $value.Length - 2) }
        $credentials[$name] = $value
    }
    Require-Export ($credentials.Count -eq 2 -and $credentials.DB_USERNAME -match '^[A-Za-z0-9_]{1,32}$' -and
        $credentials.DB_PASSWORD.Length -gt 0 -and $credentials.DB_PASSWORD.Length -le 4096) 'The existing DB_USERNAME / DB_PASSWORD credentials are incomplete.'
    $optionFile = Join-Path $output 'temporary-client-private.ini'; $loginFile = Join-Path $output 'temporary-empty-login-private.cnf'
    [IO.File]::WriteAllText($optionFile, ("[client]`nhost=127.0.0.1`nport=3306`nprotocol=TCP`nuser=" +
        (Option-Value $credentials.DB_USERNAME) + "`npassword=" + (Option-Value $credentials.DB_PASSWORD) + "`n"), [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllBytes($loginFile, [byte[]]::new(0)); $credentials.Clear(); $value = $null
    $clientArgs = @(('--defaults-extra-file=' + $optionFile), '--host=127.0.0.1','--port=3306','--protocol=TCP','--connect-timeout=10','--default-character-set=utf8mb4')
    $dumpArgs = $clientArgs + @('--single-transaction','--skip-lock-tables','--no-tablespaces','--set-gtid-purged=OFF',
        '--column-statistics=0','--hex-blob','--routines','--events','--triggers','--quick','--skip-comments','--skip-dump-date',
        '--skip-add-locks','--skip-add-drop-table','--skip-disable-keys')
    $stage = 'RESTRICTED_SOURCE_OBSERVATION'; $before = Observe-Project 'before'
    $ddlBefore = Join-Path $output 'schema-before.sql'
    Invoke-PrivateClient $dump ($dumpArgs + @('--no-data','doorhandledb')) $ddlBefore -MaximumBytes 16777216 | Out-Null
    $stage = 'SINGLE_TRANSACTION_LOGICAL_EXPORT'; $raw = Join-Path $output 'database.sql.partial'
    $rawBytes = Invoke-PrivateClient $dump ($dumpArgs + @('doorhandledb')) $raw -MaximumBytes 536870912 -TimeoutSeconds 1800
    Require-Export ($rawBytes -gt 0) 'The logical export is empty.'
    $stage = 'RESTRICTED_AFTER_OBSERVATION'; $after = Observe-Project 'after'
    $ddlAfter = Join-Path $output 'schema-after.sql'
    Invoke-PrivateClient $dump ($dumpArgs + @('--no-data','doorhandledb')) $ddlAfter -MaximumBytes 16777216 | Out-Null
    Require-Export ($before.identity.serverUuid -ceq $after.identity.serverUuid -and
        (File-Sha $before.catalogFile) -ceq (File-Sha $after.catalogFile) -and (File-Sha $before.countFile) -ceq (File-Sha $after.countFile) -and
        (File-Sha $ddlBefore) -ceq (File-Sha $ddlAfter)) 'Source identity, DDL or observed row counts changed; the outcome requires review.'
    $currentSource = Get-ReviewedSource
    Require-Export (($currentSource | ConvertTo-Json -Compress -Depth 5) -ceq ($sourceProcess | ConvertTo-Json -Compress -Depth 5)) 'The source service or direct listener process changed during export.'
    $stage = 'BYTE_ONLY_COMPRESSION'; $compressed = Join-Path $output 'database.sql.gz'
    $inputStream = $null; $outputStream = $null; $gzip = $null
    try {
        $inputStream = [IO.File]::OpenRead($raw); $outputStream = [IO.File]::Open($compressed, 'CreateNew', 'Write', 'None')
        $gzip = [IO.Compression.GZipStream]::new($outputStream, [IO.Compression.CompressionLevel]::Optimal, $true)
        $inputStream.CopyTo($gzip); $gzip.Dispose(); $gzip = $null; $outputStream.Flush($true)
    } finally {
        try { if ($null -ne $gzip) { $gzip.Dispose() } }
        finally { try { if ($null -ne $outputStream) { $outputStream.Dispose() } } finally { if ($null -ne $inputStream) { $inputStream.Dispose() } } }
    }
    $rawSha = File-Sha $raw; $inputStream = $null; $gzip = $null; $hasher = $null
    try {
        $inputStream = [IO.File]::OpenRead($compressed); $hasher = [Security.Cryptography.SHA256]::Create()
        $gzip = [IO.Compression.GZipStream]::new($inputStream, [IO.Compression.CompressionMode]::Decompress)
        $expandedSha = ([BitConverter]::ToString($hasher.ComputeHash($gzip))).Replace('-', '').ToLowerInvariant()
        Require-Export ($expandedSha -ceq $rawSha) 'Compressed export byte readback differs from the original SQL.'
    } finally {
        try { if ($null -ne $gzip) { $gzip.Dispose() } }
        finally { try { if ($null -ne $inputStream) { $inputStream.Dispose() } } finally { if ($null -ne $hasher) { $hasher.Dispose() } } }
    }
    $rawComplete = Join-Path $output 'database.sql'; Move-Item -LiteralPath $raw -Destination $rawComplete
    $stage = 'PRIVATE_CREDENTIAL_CLEANUP'
} catch { $failure = $_.Exception.GetType().Name; $reason = $_.Exception.Data['ExportReason'] }
finally {
    foreach ($file in @($optionFile, $loginFile)) {
        if ($file -and (Test-Path -LiteralPath $file)) {
            try { Assert-Unlinked $file; Remove-Item -LiteralPath $file -Force -ErrorAction Stop }
            catch { $failure = 'PrivateCredentialCleanupFailed' }
        }
    }
}
if ($failure) {
    $report = [ordered]@{ schemaVersion = 1; kind = 'doorhandle-local-mysql-export'; status = 'FAILED'; phase = $stage;
        errorType = $failure; reasonCode = $reason; sourceDeleted = $false; servicesChanged = $false; testsExecuted = $false; cloudUploaded = $false;
        backupRestoreVerified = $false; retirementAllowed = $false }
    if ($output -and (Test-Path -LiteralPath $output -PathType Container)) { Write-PrivateJson (Join-Path $output 'public-failure.json') $report }
    Write-Output ($report | ConvertTo-Json -Compress); throw 'Local export did not complete. Preserve partial business artifacts; no source deletion is authorized.'
}
$files = @{}
foreach ($file in Get-ChildItem -LiteralPath $output -File) { $files[$file.Name] = [ordered]@{ bytes = $file.Length; sha256 = File-Sha $file.FullName } }
$public = [ordered]@{ schemaVersion = 1; kind = 'doorhandle-local-mysql-export'; status = 'LOCAL_EXPORT_COMPLETE_RESTORE_PENDING';
    exportedAtUtc = [DateTimeOffset]::UtcNow.ToString('o'); sourceSchema = 'doorhandledb'; sourceEndpoint = '127.0.0.1:3306';
    scriptSha256 = File-Sha $PSCommandPath; tableCount = $before.catalog.Count;
    observedRowsBefore = [long](($before.counts | Measure-Object -Property rows -Sum).Sum);
    observedRowsAfter = [long](($after.counts | Measure-Object -Property rows -Sum).Sum);
    rowEvidence = 'BEFORE_AFTER_OBSERVATIONS_NOT_THE_DUMP_TRANSACTION'; ddlEvidence = 'MATCHING_RESTRICTED_BEFORE_AFTER_DDL';
    dumpConsistency = 'MYSQLDUMP_SINGLE_TRANSACTION_INNODB'; rawSqlSha256 = $rawSha; rawSqlBytes = $rawBytes;
    gzipSha256 = File-Sha $compressed; gzipBytes = (Get-Item -LiteralPath $compressed).Length; gzipByteReadbackVerified = $true;
    privateInputFilesRemoved = $true; credentialsArchived = $false; files = $files;
    sourceDeleted = $false; servicesChanged = $false; testsExecuted = $false; cloudUploaded = $false;
    backupRestoreVerified = $false; retirementAllowed = $false }
Write-PrivateJson (Join-Path $output 'public-manifest.json') $public
Write-Output ([ordered]@{ status = $public.status; exportDirectory = $output; rawSqlSha256 = $rawSha;
    gzipSha256 = $public.gzipSha256; tableCount = $public.tableCount; backupRestoreVerified = $false; retirementAllowed = $false } | ConvertTo-Json -Compress)
