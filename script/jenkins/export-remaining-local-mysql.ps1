#requires -Version 7.0
<#
Prepared one-time read-only retirement export, never a local test/runtime.
Do not execute without new user approval covering both named fixture schemas.
The earlier one-time doorhandledb export permission has already been used.
This script does not elevate itself, change services, restore, upload or delete.
It reuses the reviewed single-schema worker and the already running MySQL83.
IncludeLegacyBusinessSource additionally requires fresh approval for doorhandledb.
Acknowledgements record approval; they cannot provide it.
#>
[CmdletBinding(DefaultParameterSetName = 'AdministratorEnv')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'AdministratorEnv')][string]$PrivateEnvFile,
    [Parameter(Mandatory = $true, ParameterSetName = 'ProjectJson')][switch]$NonAdministratorReadOnlyExport,
    [Parameter(Mandatory = $true)][string]$UserAuthorizationReference,
    [switch]$AcknowledgeRemainingSchemasReadOnlyExport,
    [switch]$IncludeLegacyBusinessSource
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Require-Batch([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw [InvalidOperationException]::new($Message) }
}
function Assert-BatchUnlinked([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        Require-Batch (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Export paths cannot use links or junctions.'
        $item = if ($item -is [IO.FileInfo]) { $item.Directory } else { $item.Parent }
    }
}
function Write-BatchJson([string]$Path, $Value) {
    Require-Batch (-not (Test-Path -LiteralPath $Path)) 'Batch evidence cannot be overwritten.'
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
}
function Get-BatchWorkerFailure([Exception]$Failure, [bool]$NonAdmin) {
    # Only the worker's explicit public envelope is admitted. Never serialize
    # ErrorRecord, Message, StackTrace, Data as a whole, or captured stdout.
    $codes = @(
        'ADDITIONAL_FIXTURE_AUTHORIZATION_REQUIRED', 'ADMINISTRATOR_TOKEN_REQUIRED',
        'EXPORT_FAILED', 'EXPORT_GUARD_REJECTED', 'FIXED_SOURCE_SCHEMA_REQUIRED',
        'INSUFFICIENT_PROCESS_METADATA', 'NO_REVIEWED_TCP_ENDPOINT',
        'USER_AUTHORIZATION_REQUIRED', 'NONADMIN_BATCH_HELPER_BINDING_REQUIRED',
        'NONADMIN_SOURCE_HELPER_CHANGED', 'NONADMIN_SQL_HOST_OR_ACCOUNT_MISMATCH', 'NONADMIN_TOKEN_REQUIRED',
        'NONADMIN_CREDENTIAL_BYTES_REQUIRED', 'NONADMIN_CREDENTIAL_CHANGED',
        'NONADMIN_CREDENTIAL_ENDPOINT_REQUIRED', 'NONADMIN_CREDENTIAL_IDENTITY_REQUIRED',
        'NONADMIN_CREDENTIAL_SHA_REQUIRED', 'NONADMIN_CREDENTIAL_SHAPE_REQUIRED',
        'NONADMIN_ENDPOINT_OWNER_REQUIRED', 'NONADMIN_INTERPRETER_CHANGED', 'NONADMIN_METADATA_BOUND',
        'NONADMIN_METADATA_REFUSED', 'NONADMIN_POLICY_ACTION_REQUIRED', 'NONADMIN_POLICY_CHANGED',
        'NONADMIN_POLICY_START_FAILED', 'NONADMIN_POLICY_TIMEOUT', 'NONADMIN_PROCESS_METADATA_REQUIRED',
        'NONADMIN_SERVICE_REQUIRED', 'NONADMIN_TCP_STATE_REQUIRED'
    )
    $phases = @('AUTHORIZATION_REQUIRED', 'NONADMINISTRATOR_METADATA_GATE', 'ADMINISTRATOR_METADATA_GATE',
        'LOCAL_SOURCE_METADATA_GATE', 'PRIVATE_INPUT_PREPARATION', 'RESTRICTED_SOURCE_OBSERVATION',
        'SINGLE_TRANSACTION_LOGICAL_EXPORT', 'RESTRICTED_AFTER_OBSERVATION', 'BYTE_ONLY_COMPRESSION', 'PRIVATE_CREDENTIAL_CLEANUP')
    $types = @('InvalidOperationException', 'RuntimeException', 'IOException', 'UnauthorizedAccessException',
        'FileNotFoundException', 'DirectoryNotFoundException', 'ArgumentException', 'ArgumentNullException',
        'ArgumentOutOfRangeException', 'InvalidDataException', 'FormatException', 'OverflowException',
        'Win32Exception', 'CimException', 'PSInvalidCastException', 'CommandNotFoundException',
        'ParameterBindingException', 'MethodInvocationException', 'PropertyNotFoundException',
        'PrivateCredentialCleanupFailed', 'CredentialSourceIdentityChanged')
    for ($depth = 0; $null -ne $Failure -and $depth -lt 8; $depth++) {
        $candidate = $Failure; $Failure = $Failure.InnerException
        if (-not $candidate.Data.Contains('ExportFailurePublicJson')) { continue }
        $raw = $candidate.Data['ExportFailurePublicJson']
        if ($raw -isnot [string] -or [Text.Encoding]::UTF8.GetByteCount($raw) -gt 4096) { return $null }
        try { $value = ConvertFrom-Json -InputObject $raw -AsHashtable -Depth 8 } catch { return $null }
        $keys = @('schemaVersion', 'kind', 'status', 'phase', 'errorType', 'reasonCode', 'sourceDeleted',
            'servicesChanged', 'testsExecuted', 'cloudUploaded', 'sourceSeenState', 'actualClientIdentityVerified',
            'backupRestoreVerified', 'retirementAllowed')
        if ($NonAdmin) { $keys += 'sourceMode' }
        if ($value -isnot [Collections.IDictionary] -or
            (($value.Keys | Sort-Object) -join ',') -cne (($keys | Sort-Object) -join ',')) { return $null }
        if (($value.schemaVersion -isnot [int] -and $value.schemaVersion -isnot [long]) -or
            $value.schemaVersion -ne $(if ($NonAdmin) { 2 } else { 1 }) -or
            $value.kind -isnot [string] -or $value.status -isnot [string] -or $value.phase -isnot [string] -or
            $value.kind -cne $(if ($NonAdmin) { 'doorhandle-nonadmin-local-mysql-export' } else { 'doorhandle-local-mysql-export' }) -or
            ($NonAdmin -and ($value.sourceMode -isnot [string] -or $value.sourceMode -cne 'PINNED_HISTORY_FRESH_SERVICE_TCP')) -or
            $value.status -cne 'FAILED' -or $value.phase -cnotin $phases -or
            $value.reasonCode -isnot [string] -or $value.actualClientIdentityVerified -isnot [bool]) { return $null }
        $knownReason = $value.reasonCode -cin $codes
        if (-not $knownReason -and $NonAdmin) {
            $envelope = '{"errorCode": "' + $value.reasonCode + '", "status": "REFUSED"}' + "`n"
            $knownReason = (Get-NonAdminPolicyRefusalCode $envelope) -ceq $value.reasonCode
        }
        if (-not $knownReason) { return $null }
        foreach ($name in @('sourceDeleted','servicesChanged','testsExecuted','cloudUploaded','backupRestoreVerified','retirementAllowed')) {
            if ($value[$name] -isnot [bool] -or $value[$name]) { return $null }
        }
        if ($value.sourceSeenState -isnot [array] -or $value.sourceSeenState.Count -gt 2 -or
            @($value.sourceSeenState | Where-Object { ($_ -isnot [int] -and $_ -isnot [long]) -or $_ -notin @(0,2) }).Count -gt 0 -or
            @($value.sourceSeenState | Select-Object -Unique).Count -ne $value.sourceSeenState.Count) { return $null }
        if ($value.errorType -cnotin $types) { $value.errorType = 'UnclassifiedExportFailure' }
        return $value
    }
    return $null
}

Require-Batch ($IsWindows -and $AcknowledgeRemainingSchemasReadOnlyExport -and
    $UserAuthorizationReference -cmatch '^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,180}$') 'New explicit user approval for this one fixed-schema read-only batch is required.'
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if ($NonAdministratorReadOnlyExport) {
    Require-Batch (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -and
        $IncludeLegacyBusinessSource) 'The explicit ordinary-user mode requires approval and selection of exactly all three reviewed schemas.'
} else {
    Require-Batch ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Use only the separately approved administrator token; this script never requests elevation.'
}
$project = 'D:\AI\lunwen1\DoorHandleCatch'
Require-Batch ((Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path -ceq $project) 'Use the reviewed project checkout.'
$worker = Join-Path $PSScriptRoot 'export-legacy-local-mysql.ps1'
Assert-BatchUnlinked $worker
$workerSha = (Get-FileHash -LiteralPath $worker -Algorithm SHA256).Hash.ToLowerInvariant()
$nonAdminDependencies = @{}
if ($NonAdministratorReadOnlyExport) {
    $nonAdminDependencies = @{
        sourceHelper = Join-Path $PSScriptRoot 'nonadmin-local-mysql-source.ps1';
        policy = Join-Path $PSScriptRoot 'nonadmin-local-mysql-policy.py';
        interpreter = (Get-Command python -CommandType Application -ErrorAction Stop).Source
    }
    $nonAdminDependencySha = @{}
    foreach ($name in $nonAdminDependencies.Keys) {
        Assert-BatchUnlinked $nonAdminDependencies[$name]
        $nonAdminDependencySha[$name] = (Get-FileHash -LiteralPath $nonAdminDependencies[$name] -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    . $nonAdminDependencies.sourceHelper
}
$schemas = @('doorhandle_agent_verify_ef8d5844c1', 'doorhandle_model_verify_22e4bc5566')
if ($IncludeLegacyBusinessSource) { $schemas += 'doorhandledb' }

$parent = Join-Path $project 'work/jenkins'
Assert-BatchUnlinked $parent
$directory = Join-Path $parent ('remaining-local-mysql-export-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $directory -ErrorAction Stop | Out-Null
$owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = [Security.AccessControl.DirectorySecurity]::new()
$acl.SetAccessRuleProtection($true, $false); $acl.SetOwner($owner)
foreach ($sid in @($owner, [Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
}
Set-Acl -LiteralPath $directory -AclObject $acl
Require-Batch (Get-Acl -LiteralPath $directory).AreAccessRulesProtected 'Batch directory permissions were not protected.'
$authorization = [ordered]@{
    kind = 'doorhandle-remaining-local-mysql-export-authorization'; sourceSchemas = $schemas;
    userAuthorizationReference = $UserAuthorizationReference; newOneTimeReadOnlyExceptionAcknowledged = $true;
    includeLegacyBusinessSource = [bool]$IncludeLegacyBusinessSource; workerScriptSha256 = $workerSha;
    batchScriptSha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant();
    serviceName = 'MySQL83'; sourceEndpoint = '127.0.0.1:3306'; ownerSid = $owner.Value
}
if ($NonAdministratorReadOnlyExport) {
    $authorization.kind = 'doorhandle-nonadmin-remaining-local-mysql-export-authorization'
    $authorization['sourceMode'] = 'PINNED_HISTORY_FRESH_SERVICE_TCP'
    $authorization['dependencySha256'] = $nonAdminDependencySha
}
Write-BatchJson (Join-Path $directory 'authorization-private.json') $authorization

$results = [Collections.Generic.List[object]]::new()
$activeSchema = $null; $failureType = $null; $workerFailure = $null
try {
    foreach ($schema in $schemas) {
        $activeSchema = $schema
        Require-Batch ((Get-FileHash -LiteralPath $worker -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $workerSha) 'The reviewed export worker changed before invocation.'
        if ($NonAdministratorReadOnlyExport) {
            foreach ($name in $nonAdminDependencies.Keys) {
                Assert-BatchUnlinked $nonAdminDependencies[$name]
                Require-Batch ((Get-FileHash -LiteralPath $nonAdminDependencies[$name] -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $nonAdminDependencySha[$name]) 'The admitted batch dependencies changed before invocation.'
            }
        }
        $arguments = @{
            UserAuthorizationReference = $UserAuthorizationReference;
            SourceSchema = $schema; AcknowledgeOneTimeLocalReadOnlyExport = $true;
            AcknowledgeAdditionalFixtureReadOnlyExport = $true
        }
        if ($NonAdministratorReadOnlyExport) {
            $arguments['NonAdministratorReadOnlyExport'] = $true
            $arguments['ExpectedSourceHelperSha256'] = $nonAdminDependencySha.sourceHelper
            $arguments['ExpectedPolicySha256'] = $nonAdminDependencySha.policy
            $arguments['ExpectedPolicyInterpreterSha256'] = $nonAdminDependencySha.interpreter
        }
        else { $arguments['PrivateEnvFile'] = $PrivateEnvFile }
        $lines = @(& $worker @arguments)
        Require-Batch ($lines.Count -eq 1) 'The export worker did not return its single bounded public result.'
        $result = $lines[0] | ConvertFrom-Json
        Require-Batch ($result.status -ceq 'LOCAL_EXPORT_COMPLETE_RESTORE_PENDING' -and $result.sourceSchema -ceq $schema -and
            $result.rawSqlSha256 -cmatch '^[a-f0-9]{64}$' -and $result.gzipSha256 -cmatch '^[a-f0-9]{64}$' -and
            $result.backupRestoreVerified -eq $false -and $result.retirementAllowed -eq $false) 'The source result does not match the requested fixed schema or preservation boundary.'
        $exportDirectory = [IO.Path]::GetFullPath($result.exportDirectory)
        Require-Batch ($exportDirectory.StartsWith(($project + '\work\data-migration-20261107\'), [StringComparison]::OrdinalIgnoreCase)) 'The export result is outside the reviewed D-drive output root.'
        Assert-BatchUnlinked $exportDirectory
        $manifestPath = Join-Path $exportDirectory 'public-manifest.json'
        $manifest = [IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
        if ($NonAdministratorReadOnlyExport) {
            Require-Batch ($manifest.kind -ceq 'doorhandle-nonadmin-local-mysql-export' -and $manifest.schemaVersion -eq 2 -and
                $manifest.sourceMode -ceq 'PINNED_HISTORY_FRESH_SERVICE_TCP' -and $manifest.restorePending -eq $true -and
                $manifest.historicalConfigurationPinVerified -eq $true -and $manifest.freshServiceEndpointVerified -eq $true -and
                $manifest.freshDirectPrivilegesVerified -eq $true -and $manifest.actualClientIdentityVerified -eq $true -and
                $manifest.sourceHelperSha256 -ceq $nonAdminDependencySha.sourceHelper -and $manifest.policySha256 -ceq $nonAdminDependencySha.policy -and
                $manifest.policyInterpreterSha256 -ceq $nonAdminDependencySha.interpreter) 'The ordinary-user export did not prove its distinct source/permission contract.'
        }
        Require-Batch ($manifest.sourceSchema -ceq $schema -and $manifest.scriptSha256 -ceq $workerSha -and
            $manifest.rawSqlSha256 -ceq $result.rawSqlSha256 -and $manifest.gzipSha256 -ceq $result.gzipSha256 -and
            $manifest.privateInputFilesRemoved -eq $true -and $manifest.credentialsArchived -eq $false -and
            $manifest.sourceDeleted -eq $false -and $manifest.servicesChanged -eq $false) 'The original per-schema export manifest is missing or inconsistent.'
        Require-Batch ((Get-FileHash -LiteralPath $worker -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $workerSha) 'The reviewed export worker changed during invocation.'
        if ($NonAdministratorReadOnlyExport) {
            foreach ($name in $nonAdminDependencies.Keys) {
                Assert-BatchUnlinked $nonAdminDependencies[$name]
                Require-Batch ((Get-FileHash -LiteralPath $nonAdminDependencies[$name] -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $nonAdminDependencySha[$name]) 'The admitted batch dependencies changed during invocation.'
            }
        }
        $results.Add([ordered]@{
            sourceSchema = $schema; status = $result.status; exportDirectory = $exportDirectory;
            tableCount = $manifest.tableCount; observedRowsBefore = $manifest.observedRowsBefore;
            observedRowsAfter = $manifest.observedRowsAfter; rawSqlSha256 = $result.rawSqlSha256;
            gzipSha256 = $result.gzipSha256; manifestSha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant();
            backupRestoreVerified = $false; retirementAllowed = $false
        })
        Write-BatchJson (Join-Path $directory ($schema + '-result.json')) $results[$results.Count - 1]
    }
} catch {
    $failureType = $_.Exception.GetType().Name
    $workerFailure = Get-BatchWorkerFailure $_.Exception ([bool]$NonAdministratorReadOnlyExport)
}
$receipt = [ordered]@{
    kind = 'doorhandle-remaining-local-mysql-export'; schemaVersion = 1;
    status = if ($failureType) { 'PARTIAL_OR_FAILED' } else { 'LOCAL_EXPORTS_COMPLETE_ECS_RESTORE_PENDING' };
    sourceSchemas = $schemas; completedSchemas = @($results | ForEach-Object { $_.sourceSchema });
    exports = $results.ToArray(); failedSchema = if ($failureType) { $activeSchema } else { $null };
    errorType = $failureType; userAuthorizationReference = $UserAuthorizationReference;
    workerScriptSha256 = $workerSha; sourceMutationsRequested = $false; servicesChanged = $false;
    testsExecuted = $false; cloudUploaded = $false; backupRestoreVerified = $false; retirementAllowed = $false;
    automaticRetryAllowed = $false
}
if ($NonAdministratorReadOnlyExport) {
    $receipt.kind = 'doorhandle-nonadmin-remaining-local-mysql-export'; $receipt.schemaVersion = 2
    $receipt['sourceMode'] = 'PINNED_HISTORY_FRESH_SERVICE_TCP'; $receipt['restorePending'] = $true
    $receipt['dependencySha256'] = $nonAdminDependencySha
}
if ($failureType) {
    $receipt['workerFailureDetailsStatus'] = if ($workerFailure) { 'CONTROLLED_WORKER_FAILURE_CAPTURED' } else { 'NO_ADMISSIBLE_WORKER_FAILURE_DETAILS' }
    $receipt['workerFailure'] = $workerFailure
}
Write-BatchJson (Join-Path $directory 'batch-result-private.json') $receipt
Write-Output ([ordered]@{ status = $receipt.status; completedSchemas = $receipt.completedSchemas;
    receiptDirectory = $directory; backupRestoreVerified = $false; retirementAllowed = $false } | ConvertTo-Json -Compress)
if ($failureType) { throw 'The read-only export batch did not complete; preserve its partial private output and do not retry automatically.' }
