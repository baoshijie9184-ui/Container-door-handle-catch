param(
    [Parameter(Mandatory = $true)][string[]]$SshOptions,
    [Parameter(Mandatory = $true)][string]$Destination,
    [Parameter(Mandatory = $true)][string]$PortText,
    [Parameter(Mandatory = $true)][string]$RemoteRoot,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$SourceSha256,
    [string]$SnapshotDirectory = '',
    [string]$EcsSnapshotDirectory = '',
    [string]$FixtureSettings,
    [ValidateSet('Preserve','Cleanup')][string]$Mode = 'Preserve'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Require-SqlCustody([bool]$Value, [string]$Message) { if (-not $Value) { throw $Message } }
function Assert-UnlinkedSqlInput([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        Require-SqlCustody (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'SQL custody inputs cannot contain links or junctions.'
        $item = if ($item -is [IO.FileInfo]) { $item.Directory } else { $item.Parent }
    }
}
function Invoke-SqlCustody([string]$Executable, [string[]]$Arguments) {
    $result = & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Fixed-source SQL custody/recovery failed; retain the original packet and private ECS evidence.' }
    return $result
}
Require-SqlCustody ($env:CI_ECS_VERIFIED -ceq 'true') 'SQL custody requires this build actual passing ECS verification.'
Require-SqlCustody ($Destination -match '^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}$' -and
    $PortText -match '^[0-9]{1,5}$' -and [int]$PortText -ge 1 -and [int]$PortText -le 65535) 'Invalid controlled SSH endpoint.'
Require-SqlCustody ($RemoteRoot -match '^/(home|srv|opt)/[A-Za-z0-9_./-]+$' -and $RemoteRoot -notmatch '(^|/)\.\.(/|$)' -and
    -not $RemoteRoot.EndsWith('/')) 'Explicit private ECS root is required.'
if ($Mode -eq 'Preserve') {
    Require-SqlCustody ($FixtureSettings -match '^/(home|srv|opt)/[A-Za-z0-9_./-]+\.json$' -and
        $FixtureSettings -notmatch '(^|/)\.\.(/|$)') 'Explicit private fixture settings are required for recovery.'
}
Require-SqlCustody ($Commit -match '^[a-f0-9]{40}$' -and $SourceSha256 -match '^[a-f0-9]{64}$' -and
    $Tag -match '^ci-[1-9][0-9]*-[a-f0-9]{12}$' -and $Tag.EndsWith('-' + $Commit.Substring(0,12))) 'Fixed SQL custody source identity required.'
$instance = $env:DOORHANDLE_ECS_INSTANCE_ID; $machine = $env:DOORHANDLE_ECS_MACHINE_ID
Require-SqlCustody ($instance -match '^i-[a-z0-9]+$' -and $machine -match '^[a-f0-9]{32}$') 'Explicit ECS identity required.'
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$verification = Join-Path $workspace 'artifacts/ecs/evidence/verification-receipt.json'; Assert-UnlinkedSqlInput $verification
$verificationSha = (Get-FileHash -LiteralPath $verification -Algorithm SHA256).Hash.ToLowerInvariant()
$accepted = Get-Content -LiteralPath $verification -Raw -Encoding UTF8 | ConvertFrom-Json
Require-SqlCustody ($accepted.status -ceq 'PASS' -and $accepted.verificationExitCode -eq 0 -and $accepted.release -ceq $Tag -and
    $accepted.commit -ceq $Commit -and $accepted.sourceSha256 -ceq $SourceSha256 -and $accepted.identity.instanceId -ceq $instance -and
    $accepted.identity.machineId -ceq $machine) 'SQL custody lacks a same-build passing verification receipt.'
Require-SqlCustody ((Get-FileHash -LiteralPath $verification -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $verificationSha) 'The accepted verification receipt changed during reading.'
$sourceArchive = Join-Path $workspace 'artifacts/source.tar.gz'; Assert-UnlinkedSqlInput $sourceArchive
Require-SqlCustody ((Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256) 'Source archive changed.'
$python = $env:LOCAL_PYTHON_EXE
if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
Require-SqlCustody ($python -and [IO.Path]::IsPathFullyQualified($python) -and (Test-Path -LiteralPath $python -PathType Leaf)) 'Use the existing local Python only for source archive bytes.'
$archiveReader = @'
import hashlib,json,sys,tarfile
result={}
with tarfile.open(sys.argv[1],'r:gz') as archive:
    assert archive.pax_headers.get('comment')==sys.argv[2]
    members={name:'script/jenkins/'+name for name in ('preserve-local-mysql.py','restore-local-mysql.py','classify-local-mysql-source.py','collect-local-mysql-legacy-projection.py')}
    members['compact-schema-contract.json']='docs/database/compact-schema-contract.json'
    members['compact_ddl_policy.py']='script/schema/compact_ddl_policy.py'
    for name in ('compact_migration_runtime.py','compact_clock_policy.py','build_compact_schema.py'):
        members[name]='script/schema/'+name
    members['ecs_execution.py']='scripts/ecs_execution.py'
    for name,path in members.items():
        entry=archive.getmember(path)
        assert entry.isfile() and 0<entry.size<=1048576
        data=archive.extractfile(entry).read(1048577)
        assert len(data)==entry.size
        result[name]=hashlib.sha256(data).hexdigest()
print(json.dumps(result))
'@
$sourceHashes = (Invoke-SqlCustody $python @('-I','-B','-c',$archiveReader,$sourceArchive,$Commit) | Select-Object -Last 1) | ConvertFrom-Json
Require-SqlCustody ((Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256) 'Source archive changed while binding custody and classification helpers.'
$ssh = (Get-Command ssh.exe -ErrorAction Stop | Select-Object -First 1).Source
$scp = (Get-Command scp.exe -ErrorAction Stop | Select-Object -First 1).Source
$helper = "$RemoteRoot/verification/$Tag/checkout/script/jenkins/preserve-local-mysql.py"
$recovery = "$RemoteRoot/verification/$Tag/checkout/script/jenkins/restore-local-mysql.py"
$ddlPolicy = "$RemoteRoot/verification/$Tag/checkout/script/schema/compact_ddl_policy.py"
$ddlPolicyGuard = "test `"`$(sha256sum '$ddlPolicy' | cut -d ' ' -f 1)`" = '$($sourceHashes.'compact_ddl_policy.py')' && "
$helperGuard = "test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$($sourceHashes.'preserve-local-mysql.py')' && "
$recoveryGuard = $ddlPolicyGuard + "test `"`$(sha256sum '$recovery' | cut -d ' ' -f 1)`" = '$($sourceHashes.'restore-local-mysql.py')' && "
$context = "--root '$RemoteRoot' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --instance-id '$instance' --machine-id '$machine'"
function Collect-SqlCleanup {
    $text = Invoke-SqlCustody $ssh ($SshOptions + @('-p',$PortText,$Destination,"${recoveryGuard}python3 -I -B '$recovery' cleanup $context"))
    $receipt = ($text | Select-Object -Last 1) | ConvertFrom-Json
    Require-SqlCustody ($receipt.status -cin @('NOT_CREATED','STOPPED') -and $receipt.originalsChanged -eq $false -and
        $receipt.release -ceq $Tag -and $receipt.commit -ceq $Commit -and $receipt.sourceSha256 -ceq $SourceSha256 -and
        $receipt.identity.instanceId -ceq $instance -and $receipt.identity.machineId -ceq $machine -and
        $receipt.cleanupReceiptSha256 -match '^[a-f0-9]{64}$') 'Owned SQL recovery cleanup was not confirmed for this source and ECS.'
    $remoteReceipt = if ($receipt.status -ceq 'NOT_CREATED') { 'local-mysql-recovery-not-created.json' } else { 'local-mysql-recovery/public-cleanup.json' }
    $cleanupArtifact = Join-Path $workspace 'artifacts/local-mysql-recovery-cleanup.json'
    if (-not (Test-Path -LiteralPath $cleanupArtifact)) {
        Invoke-SqlCustody $scp ($SshOptions + @('-P',$PortText,"${Destination}:$RemoteRoot/verification/$Tag/checkout/work/$remoteReceipt",$cleanupArtifact)) | Out-Null
    } else { Assert-UnlinkedSqlInput $cleanupArtifact }
    Require-SqlCustody ((Get-Item -LiteralPath $cleanupArtifact).Length -le 32768 -and
        (Get-FileHash -LiteralPath $cleanupArtifact -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $receipt.cleanupReceiptSha256) 'The actual derived cleanup receipt changed during collection.'
    return $receipt
}
if ($Mode -eq 'Cleanup') {
    Collect-SqlCleanup | ConvertTo-Json -Compress
    return
}
function Ecs-SqlCustody([string]$Operation, [string]$Flags = '') {
    $result = Invoke-SqlCustody $ssh ($SshOptions + @('-p',$PortText,$Destination,"${helperGuard}python3 -I -B '$helper' $Operation $context $Flags"))
    return ($result | Select-Object -Last 1) | ConvertFrom-Json
}
$localInput = -not [string]::IsNullOrWhiteSpace($SnapshotDirectory)
$ecsInput = -not [string]::IsNullOrWhiteSpace($EcsSnapshotDirectory)
Require-SqlCustody ($localInput -xor $ecsInput) 'Choose exactly one local SQL packet or verified older ECS snapshot.'
$sourceReceiptSha = ''
if ($localInput) {
Require-SqlCustody ([IO.Path]::IsPathFullyQualified($SnapshotDirectory)) 'A full local byte-only packet path is required.'
$local = [IO.Path]::GetFullPath($SnapshotDirectory).TrimEnd('\','/')
Require-SqlCustody ($local -match '^D:\\AI\\lunwen1\\DoorHandleCatch\\work\\data-migration-20261107\\local-mysql-custody-[A-Za-z0-9_.-]+$') 'Use only the approved new local SQL packet.'
Assert-UnlinkedSqlInput $local
$entries = @(Get-ChildItem -LiteralPath $local -Force)
Require-SqlCustody ($entries.Count -eq 2 -and @($entries | Where-Object { $_.PSIsContainer -or $_.Name -cnotin @('custody.json','originals.tar.gz') }).Count -eq 0) 'Only the closed two-file SQL custody packet can be transferred.'
$bindings = @{}
foreach ($name in @('custody.json','originals.tar.gz')) {
    $file = Join-Path $local $name; Assert-UnlinkedSqlInput $file; $size = (Get-Item -LiteralPath $file).Length
    Require-SqlCustody ($size -gt 0 -and $size -le 32MB -and ($name -cne 'custody.json' -or $size -le 1MB)) 'SQL packet exceeds its reviewed byte bound.'
    $bindings[$name] = @{bytes=$size; sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$manifest = Get-Content -LiteralPath (Join-Path $local 'custody.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Require-SqlCustody ($manifest.kind -ceq 'doorhandle-local-mysql-custody' -and $manifest.profile -ceq 'local-mysql-export45-v1' -and
    $manifest.status -ceq 'PACKED' -and @($manifest.files).Count -eq 13 -and $manifest.archiveEncoding -ceq 'TAR_GZIP' -and
    $manifest.archiveSha256 -ceq $bindings['originals.tar.gz'].sha256 -and $manifest.archiveBytes -eq $bindings['originals.tar.gz'].bytes -and
    $manifest.exportManifestSha256 -ceq '0b58012469e0babb2031b54d34ed906910b75f9385d8950776776153dde3495d') 'The local packet is not the fixed successful export.'
} else {
    $pattern = '^' + [regex]::Escape($RemoteRoot) + '/verification/ci-[1-9][0-9]*-[a-f0-9]{12}/checkout/work/local-mysql-export-snapshot$'
    Require-SqlCustody ($EcsSnapshotDirectory -cmatch $pattern -and $EcsSnapshotDirectory -cne "$RemoteRoot/verification/$Tag/checkout/work/local-mysql-export-snapshot") 'SQL reuse requires an earlier same-root fixed snapshot.'
    $description = Ecs-SqlCustody 'describe' "--source-snapshot-directory '$EcsSnapshotDirectory'"
    Require-SqlCustody ($description.status -ceq 'DESCRIBED' -and $description.kind -ceq 'doorhandle-local-mysql-custody' -and
        $description.profile -ceq 'local-mysql-export45-v1' -and $description.release -ceq $Tag -and $description.commit -ceq $Commit -and
        $description.sourceSha256 -ceq $SourceSha256 -and $description.verificationReceiptSha256 -ceq $verificationSha -and
        $description.identity.instanceId -ceq $instance -and $description.identity.machineId -ceq $machine -and
        $description.identity.executionLocation -ceq 'ECS' -and $description.files -eq 13 -and
        $description.rawSqlSha256 -ceq '6b8bce0cc4da19384d9fc4ce894946c34b9b285dd2e9a150f1211967999e2464' -and
        $description.gzipSha256 -ceq '8f0a2e9014233dc20f4e26321eb855846bda0ddb689c39d85db33133e447b627' -and
        $description.productionMerged -is [bool] -and -not $description.productionMerged -and
        $description.retirementAllowed -is [bool] -and -not $description.retirementAllowed -and
        $description.sourceCustodyReceiptSha256 -cmatch '^[a-f0-9]{64}$') 'Old ECS SQL custody did not prove its exact source and complete independent recovery.'
    $bindings = @{'custody.json'=@{bytes=$description.manifestBytes;sha256=$description.manifestSha256};
                  'originals.tar.gz'=@{bytes=$description.archiveBytes;sha256=$description.archiveSha256}}
    foreach ($name in @('custody.json','originals.tar.gz')) {
        $binding = $bindings[$name]; $maximum = if ($name -ceq 'custody.json') { 1MB } else { 32MB }
        Require-SqlCustody (($binding.bytes -is [int] -or $binding.bytes -is [long]) -and $binding.bytes -gt 0 -and
            $binding.bytes -le $maximum -and $binding.sha256 -cmatch '^[a-f0-9]{64}$') 'Old ECS SQL input byte bindings are missing or exceed the fixed limits.'
    }
    $sourceReceiptSha = $description.sourceCustodyReceiptSha256
}
$inputFlags = "--manifest-sha256 '$($bindings['custody.json'].sha256)' --manifest-bytes $($bindings['custody.json'].bytes) --archive-sha256 '$($bindings['originals.tar.gz'].sha256)' --archive-bytes $($bindings['originals.tar.gz'].bytes)"
if ($localInput) {
$prepared = Ecs-SqlCustody 'prepare' $inputFlags
Require-SqlCustody ($prepared.status -ceq 'PREPARED' -and $prepared.release -ceq $Tag -and $prepared.commit -ceq $Commit) 'ECS did not admit the SQL custody destination.'
foreach ($name in @('custody.json','originals.tar.gz')) {
    $file = Join-Path $local $name
    Invoke-SqlCustody $scp ($SshOptions + @('-P',$PortText,$file,"${Destination}:$RemoteRoot/verification/$Tag/checkout/work/local-mysql-export-snapshot/$name")) | Out-Null
    Require-SqlCustody ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $bindings[$name].sha256) 'Local packet changed while transferring.'
}
$bytes = Ecs-SqlCustody 'verify-restore' $inputFlags
} else {
    $bytes = Ecs-SqlCustody 'reuse' "$inputFlags --source-snapshot-directory '$EcsSnapshotDirectory' --source-receipt-sha256 '$sourceReceiptSha'"
}
Require-SqlCustody ($bytes.status -ceq 'BYTES_RESTORED_VERIFIED' -and $bytes.rawSqlSha256 -ceq '6b8bce0cc4da19384d9fc4ce894946c34b9b285dd2e9a150f1211967999e2464' -and
    $bytes.manifestSha256 -ceq $bindings['custody.json'].sha256 -and $bytes.archiveSha256 -ceq $bindings['originals.tar.gz'].sha256) 'Exact SQL byte preservation failed.'
$byteArtifact = Join-Path $workspace 'artifacts/local-mysql-custody.json'
Require-SqlCustody (-not (Test-Path -LiteralPath $byteArtifact) -and $bytes.publicReceiptSha256 -match '^[a-f0-9]{64}$') 'Use a fresh SQL byte receipt destination.'
Invoke-SqlCustody $scp ($SshOptions + @('-P',$PortText,"${Destination}:$RemoteRoot/verification/$Tag/checkout/work/local-mysql-export-public.json",$byteArtifact)) | Out-Null
Require-SqlCustody ((Get-Item -LiteralPath $byteArtifact).Length -le 32768 -and (Get-FileHash -LiteralPath $byteArtifact -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $bytes.publicReceiptSha256) 'The actual SQL byte custody receipt changed in collection.'
$failed = $null; $result = $null
try {
    $text = Invoke-SqlCustody $ssh ($SshOptions + @('-p',$PortText,$Destination,"${recoveryGuard}python3 -I -B '$recovery' run $context --fixture-settings '$FixtureSettings'"))
    $result = ($text | Select-Object -Last 1) | ConvertFrom-Json
} catch { $failed = $_ }
$cleanup = $null; $cleanupFailure = $null
try { $cleanup = Collect-SqlCleanup } catch { $cleanupFailure = $_ }
if ($failed) { throw $failed }
if ($cleanupFailure) { throw $cleanupFailure }
Require-SqlCustody ($cleanup.derivedContainersRemoved -eq 2 -and $cleanup.derivedVolumesRemoved -eq 2 -and
    $cleanup.recoveryVolumesRetained -eq $false -and $cleanup.cleanupReceiptSha256 -match '^[a-f0-9]{64}$') 'Successful recovery must clean only its two independently verified derived containers and volumes.'
Require-SqlCustody ($result.status -ceq 'SQL_DOUBLE_RESTORED_VERIFIED' -and $result.release -ceq $Tag -and $result.commit -ceq $Commit -and
    $result.sourceSha256 -ceq $SourceSha256 -and $result.identity.instanceId -ceq $instance -and $result.identity.machineId -ceq $machine -and
    $result.tableCount -eq 45 -and $result.allOriginalRowsPreserved -eq $true -and $result.liveSourceRowHashesVerified -eq $false -and
    $result.productionMerged -eq $false -and $result.retirementAllowed -eq $false -and $result.eventsExecuted -eq $false -and
    $result.recoveryReceiptSha256 -match '^[a-f0-9]{64}$') 'The exact two independent SQL recoveries were not verified.'
$artifact = Join-Path $workspace 'artifacts/local-mysql-recovery.json'
Require-SqlCustody (-not (Test-Path -LiteralPath $artifact)) 'SQL public recovery evidence already exists.'
Invoke-SqlCustody $scp ($SshOptions + @('-P',$PortText,"${Destination}:$RemoteRoot/verification/$Tag/checkout/work/local-mysql-recovery/public-recovery.json",$artifact)) | Out-Null
Require-SqlCustody ((Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $result.recoveryReceiptSha256) 'The original ECS recovery receipt changed during collection.'
if ($accepted.scope -ceq 'mysql') {
    # Only this same-build scope has the complete 131-table fixture-origin copy.
    # Dynamic owner digests come from authenticated SSH file reads, not from a
    # classification response that could merely repeat its own invented hashes.
    Require-SqlCustody ($SshOptions -ccontains 'StrictHostKeyChecking=yes' -and
        $SshOptions -ccontains 'HostKeyAlias=doorhandle-bj') 'Classification requires the fixed authenticated SSH peer.'
    $knownOptions = @($SshOptions | Where-Object { $_ -clike 'UserKnownHostsFile=*' })
    Require-SqlCustody ($knownOptions.Count -eq 1) 'Classification requires one explicit pinned host-key file.'
    $knownFile = $knownOptions[0].Substring('UserKnownHostsFile='.Length); Assert-UnlinkedSqlInput $knownFile
    Require-SqlCustody ([IO.Path]::IsPathFullyQualified($knownFile) -and (Test-Path -LiteralPath $knownFile -PathType Leaf)) 'The pinned host-key file is unavailable.'
    $classificationSshOptions = @('-F','NUL','-o','GlobalKnownHostsFile=NUL','-o','IdentitiesOnly=yes',
        '-o','PermitLocalCommand=no','-o','ClearAllForwardings=yes') + $SshOptions
    $digestReader = @'
import hashlib,json,os,re,stat,sys
from pathlib import Path
def need(value):
    if not value: raise ValueError('Classification control digest admission failed')
root=Path(sys.argv[1]); tag=sys.argv[2]; mode=sys.argv[3]
need(root.is_absolute() and '..' not in root.parts and root.resolve(strict=True)==root)
need(re.fullmatch(r'ci-[1-9][0-9]*-[a-f0-9]{12}',tag) and mode in ('anchors','report','projection'))
work=root/'verification'/tag/'checkout/work'
paths=({'localOwner':work/'local-mysql-recovery-owner.json','fixtureOwner':work/'compact-fixtures-owner.json'}
       if mode=='anchors' else {'projection':work/'compact-fixtures/source-legacy-projection/receipt.json'}
       if mode=='projection' else {'report':work/'local-mysql-source-classification.json'})
maximum=16*1024**2 if mode=='anchors' else 1024**2
result={}
for name,path in paths.items():
    need(path.resolve(strict=True)==path)
    for parent in (path,*path.parents): need(not parent.is_symlink())
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
        before=os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and before.st_nlink==1
             and not before.st_mode&0o077 and 0<before.st_size<=maximum)
        raw=stream.read(maximum+1); after=os.fstat(stream.fileno()); linked=path.lstat()
    signature=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_nlink,value.st_mode)
    need(signature(before)==signature(after)==signature(linked) and len(raw)==before.st_size)
    result[name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
print(json.dumps(result))
'@
    function Read-ClassificationDigests([ValidateSet('anchors','report','projection')][string]$ReadMode) {
        $sshArguments = $classificationSshOptions + @('-p',$PortText,$Destination,"python3 -I -B - '$RemoteRoot' '$Tag' '$ReadMode'")
        $lines = @($digestReader | & $ssh @sshArguments)
        Require-SqlCustody ($LASTEXITCODE -eq 0 -and $lines.Count -eq 1) 'Authenticated stable classification-control digests were not obtained.'
        return $lines[0] | ConvertFrom-Json
    }
    $anchors = Read-ClassificationDigests 'anchors'
    foreach ($role in @('localOwner','fixtureOwner')) {
        $binding = $anchors.$role
        Require-SqlCustody ($binding.bytes -gt 0 -and $binding.bytes -le 16MB -and $binding.sha256 -cmatch '^[a-f0-9]{64}$') 'A classification owner digest is missing or unbounded.'
    }
    Require-SqlCustody ((Get-FileHash -LiteralPath $verification -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $verificationSha) 'The current verification anchor drifted before classification.'
    $classifier = "$RemoteRoot/verification/$Tag/checkout/script/jenkins/classify-local-mysql-source.py"
    $remoteReport = "$RemoteRoot/verification/$Tag/checkout/work/local-mysql-source-classification.json"
    $classifierSha = $sourceHashes.'classify-local-mysql-source.py'; $contractSha = $sourceHashes.'compact-schema-contract.json'
    Require-SqlCustody ($classifierSha -cmatch '^[a-f0-9]{64}$' -and $contractSha -cmatch '^[a-f0-9]{64}$') 'Classification code and contract must be bound to the immutable source archive.'
    $classifierGuard = $ddlPolicyGuard + "test `"`$(sha256sum '$classifier' | cut -d ' ' -f 1)`" = '$classifierSha' && "
    $anchorFlags = "--verification-receipt-sha256 '$verificationSha' --local-owner-sha256 '$($anchors.localOwner.sha256)' --fixture-owner-sha256 '$($anchors.fixtureOwner.sha256)' --contract-sha256 '$contractSha'"
    $collector = "$RemoteRoot/verification/$Tag/checkout/script/jenkins/collect-local-mysql-legacy-projection.py"
    $collectorSha = $sourceHashes.'collect-local-mysql-legacy-projection.py'
    $collectorGuard = $classifierGuard + "test `"`$(sha256sum '$collector' | cut -d ' ' -f 1)`" = '$collectorSha' && "
    foreach ($entry in @(@('compact_migration_runtime.py','script/schema'),@('compact_clock_policy.py','script/schema'),
        @('build_compact_schema.py','script/schema'),@('ecs_execution.py','scripts'))) {
        $boundHelper = "$RemoteRoot/verification/$Tag/checkout/$($entry[1])/$($entry[0])"
        $boundSha = $sourceHashes.($entry[0])
        Require-SqlCustody ($boundSha -cmatch '^[a-f0-9]{64}$') 'Projection dependencies must come from the immutable source archive.'
        $collectorGuard += "test `"`$(sha256sum '$boundHelper' | cut -d ' ' -f 1)`" = '$boundSha' && "
    }
    $projectionLines = @(Invoke-SqlCustody $ssh ($classificationSshOptions + @('-p',$PortText,$Destination,"${collectorGuard}python3 -I -B '$collector' $context $anchorFlags")))
    Require-SqlCustody ($projectionLines.Count -eq 1) 'Legacy projection must return one bounded summary.'
    $projected = $projectionLines[0] | ConvertFrom-Json
    $projectionBinding = (Read-ClassificationDigests 'projection').projection
    Require-SqlCustody ($projected.status -ceq 'LEGACY_PROJECTION_VERIFIED' -and
        $projected.receiptSha256 -cmatch '^[a-f0-9]{64}$' -and $projectionBinding.sha256 -ceq $projected.receiptSha256 -and
        $projectionBinding.bytes -gt 0 -and $projectionBinding.bytes -le 1MB -and
        (@($projected.tables | Sort-Object) -join ',') -ceq 'detection_task,model_management' -and
        $projected.productionMerged -eq $false -and $projected.retirementAllowed -eq $false) 'The authenticated complete legacy-column projection was not captured.'
    $projectionArtifact = Join-Path $workspace 'artifacts/local-mysql-legacy-projection.json'
    Require-SqlCustody (-not (Test-Path -LiteralPath $projectionArtifact)) 'Use a fresh legacy-projection receipt destination.'
    $remoteProjection = "$RemoteRoot/verification/$Tag/checkout/work/compact-fixtures/source-legacy-projection/receipt.json"
    Invoke-SqlCustody $scp ($classificationSshOptions + @('-P',$PortText,"${Destination}:$remoteProjection",$projectionArtifact)) | Out-Null
    Assert-UnlinkedSqlInput $projectionArtifact
    Require-SqlCustody ((Get-Item -LiteralPath $projectionArtifact).Length -eq $projectionBinding.bytes -and
        (Get-FileHash -LiteralPath $projectionArtifact -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $projectionBinding.sha256) 'The original projection receipt changed during collection.'
    $flags = "$anchorFlags --legacy-projection-sha256 '$($projectionBinding.sha256)' --output '$remoteReport'"
    $classificationLines = @(Invoke-SqlCustody $ssh ($classificationSshOptions + @('-p',$PortText,$Destination,"${classifierGuard}python3 -I -B '$classifier' $context $flags")))
    Require-SqlCustody ($classificationLines.Count -eq 1) 'Classification must return one bounded summary.'
    $classified = $classificationLines[0] | ConvertFrom-Json
    Require-SqlCustody ($classified.status -ceq 'CLASSIFIED' -and $classified.reportSha256 -cmatch '^[a-f0-9]{64}$' -and
        $classified.perKeyStatus -cin @('NOT_COLLECTED','NEEDS_REVIEW','RECONCILED') -and
        $classified.cutoverBlocked -is [bool] -and
        $classified.coverageVerified -is [bool] -and -not $classified.coverageVerified -and
        $classified.productionMerged -is [bool] -and -not $classified.productionMerged -and
        $classified.retirementAllowed -is [bool] -and -not $classified.retirementAllowed) 'Classification did not return the expected non-authorizing result.'
    $remoteBinding = (Read-ClassificationDigests 'report').report
    Require-SqlCustody ($remoteBinding.bytes -gt 0 -and $remoteBinding.bytes -le 1MB -and
        $remoteBinding.sha256 -ceq $classified.reportSha256) 'The remote original classification report is unbounded or changed.'
    $reportArtifact = Join-Path $workspace 'artifacts/local-mysql-source-classification.json'
    $wiringArtifact = Join-Path $workspace 'artifacts/local-mysql-source-classification-ci.json'
    Require-SqlCustody (-not (Test-Path -LiteralPath $reportArtifact) -and -not (Test-Path -LiteralPath $wiringArtifact)) 'Use fresh classification artifact destinations.'
    Invoke-SqlCustody $scp ($classificationSshOptions + @('-P',$PortText,"${Destination}:$remoteReport",$reportArtifact)) | Out-Null
    Assert-UnlinkedSqlInput $reportArtifact
    Require-SqlCustody ((Get-Item -LiteralPath $reportArtifact).Length -eq $remoteBinding.bytes -and
        (Get-FileHash -LiteralPath $reportArtifact -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $classified.reportSha256) 'The original classification report changed during SCP.'
    $report = Get-Content -LiteralPath $reportArtifact -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 32
    Require-SqlCustody ($report.schemaVersion -eq 1 -and $report.kind -ceq 'doorhandle-local-mysql-source-classification' -and $report.status -ceq 'CLASSIFIED' -and
        $report.context.release -ceq $Tag -and $report.context.commit -ceq $Commit -and $report.context.sourceSha256 -ceq $SourceSha256 -and
        $report.context.identity.instanceId -ceq $instance -and $report.context.identity.machineId -ceq $machine -and
        $report.context.identity.executionLocation -ceq 'ECS' -and $report.localTableCount -eq 45 -and $report.sourceTableCount -eq 131 -and
        $report.comparisonScope -ceq 'COMPLETE_TABLE_SNAPSHOT_V1' -and $report.trustAnchorAuthentication -ceq 'REQUIRED_FROM_CALLER' -and
        $report.inputRawSha256.verification -ceq $verificationSha -and $report.inputRawSha256.localOwner -ceq $anchors.localOwner.sha256 -and
        $report.inputRawSha256.fixtureOwner -ceq $anchors.fixtureOwner.sha256 -and $report.inputRawSha256.contract -ceq $contractSha -and
        $report.inputRawSha256.localPublic -ceq $result.recoveryReceiptSha256 -and $report.localSnapshotSha256 -ceq $result.snapshotSha256) 'Collected classification context, table scope or trust anchors differ.'
    foreach ($field in @('coverageVerified','targetDataCompared','productionMerged','retirementAllowed','sourceDataBytesRehashed')) {
        Require-SqlCustody ($report.$field -is [bool] -and -not $report.$field) 'A classification report attempted an unproved coverage, data or retirement claim.'
    }
    $perKey = $report.perKeyReconciliation
    $projection = $perKey.legacyColumnProjection
    Require-SqlCustody ($projection.status -ceq 'VERIFIED' -and $projection.receiptSha256 -ceq $projectionBinding.sha256 -and
        $projection.ruleEvidenceSha256 -ceq '5fedf7fd1e1d95a0533d5ee201aad2e2a7489f5950d56519137e4494ffb94e0f' -and
        $projection.scope -ceq 'AUDITED_19_APPENDED_COLUMNS_ONLY' -and $projection.fullSourceColumnsAndRowsRetained -eq $true -and
        $projection.sourceScope -ceq 'SAME_BUILD_FULL_131_FROZEN_SOURCE_CLONE' -and
        (@($projection.tables | Sort-Object) -join ',') -ceq 'detection_task,model_management') 'The audit did not bind both approved projections while retaining full source vectors.'
    Require-SqlCustody ($perKey.scope -ceq 'EXACT_TYPED_PRIMARY_KEYS_V1' -and
        $perKey.gateScope -ceq 'PER_KEY_SOURCE_INCLUSION_ONLY' -and
        $perKey.wholeMigrationAndRuntimeAcceptanceStillRequired -eq $true -and
        $perKey.requiredBeforeCutover -eq $true -and $perKey.cutoverBlocked -is [bool] -and
        $perKey.legacyRowsPresentInSource -is [bool] -and $perKey.targetDataCompared -eq $false -and
        $perKey.status -ceq $classified.perKeyStatus -and $perKey.cutoverBlocked -eq $classified.cutoverBlocked -and
        (($perKey.status -ceq 'RECONCILED' -and -not $perKey.cutoverBlocked -and $perKey.legacyRowsPresentInSource) -or
         ($perKey.status -cin @('NOT_COLLECTED','NEEDS_REVIEW') -and $perKey.cutoverBlocked -and -not $perKey.legacyRowsPresentInSource))) 'Per-key audit does not establish its exact limited source-inclusion boundary.'
    $wiring = [ordered]@{schemaVersion=1;kind='doorhandle-local-mysql-source-classification-ci';status='CLASSIFIED';
        release=$Tag;commit=$Commit;sourceSha256=$SourceSha256;identity=$report.context.identity;
        classifierSha256=$classifierSha;contractSha256=$contractSha;projectionCollectorSha256=$collectorSha;
        projectionReceiptSha256=$projectionBinding.sha256;projectionReceiptBytes=$projectionBinding.bytes;
        anchors=[ordered]@{verification=$verificationSha;localOwner=$anchors.localOwner.sha256;fixtureOwner=$anchors.fixtureOwner.sha256;contract=$contractSha};
        recoveryReceiptSha256=$result.recoveryReceiptSha256;cleanupReceiptSha256=$cleanup.cleanupReceiptSha256;
        reportSha256=$classified.reportSha256;reportBytes=$remoteBinding.bytes;counts=$report.counts;
        perKeyReconciliation=$perKey;
        coverageVerified=$false;targetDataCompared=$false;productionMerged=$false;retirementAllowed=$false}
    $wiring | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $wiringArtifact -Encoding utf8
    # Verification may retain unresolved differences for review. A requested
    # first production cutover must not advance past this unverified subgate.
    if ($env:ACTION -ceq 'compact-cutover') {
        Require-SqlCustody ($perKey.status -ceq 'RECONCILED' -and -not $perKey.cutoverBlocked -and
            $perKey.legacyRowsPresentInSource) 'Legacy 45-table rows are not yet verified in the 131-table source; production cutover remains blocked.'
    }
} else {
    Require-SqlCustody ($accepted.scope -ceq 'source') 'Classification supports only the established source or mysql verification scopes.'
    Write-Host '45-to-131 classification is not run in source scope; this build has no complete 131-table fixture-origin copy.'
}
Write-Output ([ordered]@{status=$result.status;tableCount=45;rawSqlSha256=$result.rawSqlSha256;
    recoveryReceiptSha256=$result.recoveryReceiptSha256;retirementAllowed=$false;productionMerged=$false} | ConvertTo-Json -Compress)
