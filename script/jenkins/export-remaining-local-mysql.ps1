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
$activeSchema = $null; $failureType = $null
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
} catch { $failureType = $_.Exception.GetType().Name }
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
Write-BatchJson (Join-Path $directory 'batch-result-private.json') $receipt
Write-Output ([ordered]@{ status = $receipt.status; completedSchemas = $receipt.completedSchemas;
    receiptDirectory = $directory; backupRestoreVerified = $false; retirementAllowed = $false } | ConvertTo-Json -Compress)
if ($failureType) { throw 'The read-only export batch did not complete; preserve its partial private output and do not retry automatically.' }
