param(
    [Parameter(Mandatory = $true)][string[]]$SshOptions,
    [Parameter(Mandatory = $true)][string]$Destination,
    [Parameter(Mandatory = $true)][string]$PortText,
    [Parameter(Mandatory = $true)][string]$RemoteRoot,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$SourceSha256,
    [string]$SnapshotDirectory = '', [string]$ManifestSha256 = '', [string]$ArchiveSha256 = '',
    [string]$FixtureSettings = '',
    [ValidateSet('Preserve','Cleanup')][string]$Mode = 'Preserve'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$workspace=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$script:projectRemoteStarted=$false; $script:projectVerificationAdmitted=$false
trap {
    # Public failure controls contain no exception message, SQL, credentials,
    # source member bytes or private owner file. Unknown cleanup stays unknown.
    $name=if($Mode -ceq 'Cleanup'){'project-mysql-cleanup-failure.json'}else{'project-mysql-ci.json'}
    $target=Join-Path $workspace ('artifacts/'+$name)
    if((Test-Path -LiteralPath (Split-Path -Parent $target) -PathType Container) -and -not (Test-Path -LiteralPath $target)) {
        [ordered]@{kind='doorhandle-project-mysql-ci-failure';release=$Tag;commit=$Commit;sourceSha256=$SourceSha256;
            status='FAILED_OR_UNKNOWN';failureType=$_.Exception.GetType().Name;verificationReceiptCompared=$script:projectVerificationAdmitted;
            remoteCommandStarted=$script:projectRemoteStarted;ownedCleanupVerified=$false;productionMerged=$false;retirementAllowed=$false} |
            ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $target -Encoding utf8
    }
    break
}
function Require-ProjectSql([bool]$Value,[string]$Message) { if (-not $Value) { throw $Message } }
function Assert-ProjectSqlUnlinked([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        Require-ProjectSql (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Project SQL paths cannot contain links or junctions.'
        $item = if ($item -is [IO.FileInfo]) { $item.Directory } else { $item.Parent }
    }
}
function Invoke-ProjectSql([string]$Executable,[string[]]$Arguments) {
    $output = @(& $Executable @Arguments)
    if ($LASTEXITCODE -ne 0) {
        if ($output.Count -eq 1) {
            try {
                $summary = $output[0] | ConvertFrom-Json
                if ($summary.status -ceq 'FAILED_OR_UNKNOWN' -and $summary.errorType -cmatch '^[A-Za-z][A-Za-z0-9_]{0,127}$' -and
                    $summary.productionMerged -eq $false -and $summary.retirementAllowed -eq $false) {
                    $script:projectRemoteFailure = @{status=$summary.status;errorType=$summary.errorType;productionMerged=$false;retirementAllowed=$false}
                }
            } catch { }
        }
        throw 'Fixed-source project SQL preservation or recovery failed; original bytes and private ECS evidence are retained.'
    }
    return $output
}
Require-ProjectSql ($env:CI_ECS_VERIFIED -ceq 'true' -and $env:ACTION -cin @('verify','verify-runtime') -and
    $env:DOORHANDLE_CI_SCOPE -ceq 'mysql' -and $env:PRODUCTION_RELEASE_ENABLED -cne 'true') 'Project SQL custody requires this build full MySQL PASS and an archive-only verification action.'
Require-ProjectSql ($Destination -cmatch '^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}$' -and
    $PortText -cmatch '^[0-9]{1,5}$' -and [int]$PortText -ge 1 -and [int]$PortText -le 65535 -and
    $RemoteRoot -cmatch '^/(home|srv|opt)/[A-Za-z0-9_./-]+$' -and $RemoteRoot -cnotmatch '(^|/)\.\.(/|$)' -and
    -not $RemoteRoot.EndsWith('/')) 'A controlled private ECS endpoint is required.'
Require-ProjectSql ($Tag -cmatch '^ci-[1-9][0-9]*-[a-f0-9]{12}$' -and $Commit -cmatch '^[a-f0-9]{40}$' -and
    $SourceSha256 -cmatch '^[a-f0-9]{64}$' -and $Tag.EndsWith('-'+$Commit.Substring(0,12))) 'Fixed project SQL source required.'
Require-ProjectSql ($FixtureSettings -cmatch '^/(home|srv|opt)/[A-Za-z0-9_./-]+\.json$' -and
    $FixtureSettings -cnotmatch '(^|/)\.\.(/|$)') 'Existing reviewed private ECS image settings are required.'
$instance=$env:DOORHANDLE_ECS_INSTANCE_ID; $machine=$env:DOORHANDLE_ECS_MACHINE_ID
Require-ProjectSql ($instance -cmatch '^i-[a-z0-9]+$' -and $machine -cmatch '^[a-f0-9]{32}$') 'Explicit ECS identity required.'
Require-ProjectSql ($SshOptions -ccontains 'StrictHostKeyChecking=yes' -and $SshOptions -ccontains 'HostKeyAlias=doorhandle-bj') 'Use the authenticated pinned SSH peer.'
$known=@($SshOptions | Where-Object { $_ -clike 'UserKnownHostsFile=*' })
Require-ProjectSql ($known.Count -eq 1) 'One explicit pinned host-key file is required.'
$knownPath=$known[0].Substring('UserKnownHostsFile='.Length); Assert-ProjectSqlUnlinked $knownPath
Require-ProjectSql ([IO.Path]::IsPathFullyQualified($knownPath)) 'The pinned host key requires an absolute path.'
$options=@('-F','NUL','-o','GlobalKnownHostsFile=NUL','-o','IdentitiesOnly=yes','-o','PermitLocalCommand=no','-o','ClearAllForwardings=yes')+$SshOptions
$workspace=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$verification=Join-Path $workspace 'artifacts/ecs/evidence/verification-receipt.json'; Assert-ProjectSqlUnlinked $verification
$verificationSha=(Get-FileHash -LiteralPath $verification -Algorithm SHA256).Hash.ToLowerInvariant()
$accepted=Get-Content -LiteralPath $verification -Raw -Encoding utf8 | ConvertFrom-Json
Require-ProjectSql ($accepted.status -ceq 'PASS' -and $accepted.verificationExitCode -eq 0 -and $accepted.release -ceq $Tag -and
    $accepted.commit -ceq $Commit -and $accepted.sourceSha256 -ceq $SourceSha256 -and $accepted.scope -ceq 'mysql' -and
    $accepted.identity.instanceId -ceq $instance -and $accepted.identity.machineId -ceq $machine -and
    $accepted.identity.executionLocation -ceq 'ECS') 'The actual same-build complete MySQL verification receipt is required.'
$script:projectVerificationAdmitted=$true
$archive=Join-Path $workspace 'artifacts/source.tar.gz'; Assert-ProjectSqlUnlinked $archive
Require-ProjectSql ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256) 'The fixed source archive changed.'
$python=$env:LOCAL_PYTHON_EXE; if ([string]::IsNullOrWhiteSpace($python)) { $python=$env:PYTHON_EXE }
Require-ProjectSql ($python -and [IO.Path]::IsPathFullyQualified($python) -and (Test-Path -LiteralPath $python -PathType Leaf)) 'Use the existing local Python for byte metadata only.'
$projectArchiveReader = @'
import hashlib,json,sys,tarfile
paths=['script/jenkins/'+name for name in ('preserve-project-mysql.ps1','project-mysql-custody.py','restore-project-mysql.py',
 'preserve-local-mysql.py','restore-local-mysql.py','preserve-local-artifacts.py','export-legacy-local-mysql.ps1',
 'export-remaining-local-mysql.ps1','nonadmin-local-mysql-source.ps1','nonadmin-local-mysql-policy.py')]
paths+=['script/schema/'+name for name in ('compact_migration_runtime.py','build_compact_schema.py','compact_clock_policy.py','compact_ddl_policy.py')]
paths+=['script/docker/compact-schema-guard.py','scripts/ecs_execution.py']
result={}
with tarfile.open(sys.argv[1],'r:gz') as archive:
 assert archive.pax_headers.get('comment')==sys.argv[2]
 for path in paths:
  member=archive.getmember(path); assert member.isfile() and 0<member.size<=1048576
  body=archive.extractfile(member).read(1048577); assert len(body)==member.size
  result[path]=hashlib.sha256(body).hexdigest()
print(json.dumps(result))
'@
$hashes=(Invoke-ProjectSql $python @('-I','-B','-c',$projectArchiveReader,$archive,$Commit) | Select-Object -Last 1) | ConvertFrom-Json
Require-ProjectSql ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256 -and
    (Get-FileHash -LiteralPath $verification -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $verificationSha) 'The accepted source or verification changed.'
$guard=''
foreach($property in $hashes.PSObject.Properties) {
    Require-ProjectSql ($property.Name -cmatch '^(script|scripts)/[A-Za-z0-9_./-]+\.(py|ps1)$' -and
        $property.Name -cnotmatch '(^|/)\.\.(/|$)' -and $property.Value -cmatch '^[a-f0-9]{64}$') 'Fixed source dependency binding differs.'
    $remote="$RemoteRoot/verification/$Tag/checkout/$($property.Name)"
    $guard+="test `"`$(sha256sum '$remote' | cut -d ' ' -f 1)`" = '$($property.Value)' && "
}
Require-ProjectSql (@($hashes.PSObject.Properties).Count -eq 16) 'The complete project SQL dependency closure is required.'
$ssh=(Get-Command ssh.exe -ErrorAction Stop | Select-Object -First 1).Source
$scp=(Get-Command scp.exe -ErrorAction Stop | Select-Object -First 1).Source
$helper="$RemoteRoot/verification/$Tag/checkout/script/jenkins/project-mysql-custody.py"
$recovery="$RemoteRoot/verification/$Tag/checkout/script/jenkins/restore-project-mysql.py"
$context="--root '$RemoteRoot' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --instance-id '$instance' --machine-id '$machine'"
$inputArtifact=Join-Path $workspace 'artifacts/project-mysql-inputs.json'
$projectRunRequest=Join-Path $workspace 'artifacts/project-mysql-run-request.json'
$script:projectRemoteFailure=$null
function Assert-ProjectSqlContext($Value) {
    Require-ProjectSql ($Value.release -ceq $Tag -and $Value.commit -ceq $Commit -and $Value.sourceSha256 -ceq $SourceSha256 -and
        $Value.identity.instanceId -ceq $instance -and $Value.identity.machineId -ceq $machine -and
        $Value.identity.executionLocation -ceq 'ECS' -and $Value.verificationReceiptSha256 -ceq $verificationSha -and
        $Value.batchReceiptSha256 -ceq $binding.batchReceiptSha256 -and $Value.profile -ceq 'project-mysql-three-schema-v2') 'The original project SQL receipt belongs to another source or ECS.'
}
function Invoke-ProjectSqlRemote([string]$Program,[string]$Operation,[string]$Extra='') {
    $script:projectRemoteStarted=$true
    if($Operation -ceq 'run') {
        Require-ProjectSql (-not (Test-Path -LiteralPath $projectRunRequest)) 'Use a fresh project SQL run request; observe the original issued run.'
        @{kind='doorhandle-project-mysql-run-request';release=$Tag;commit=$Commit;sourceSha256=$SourceSha256;
            verificationReceiptSha256=$verificationSha;identity=$accepted.identity;batchReceiptSha256=$binding.batchReceiptSha256;
            manifestSha256=$ManifestSha256;archiveSha256=$ArchiveSha256;runAttempted=$true} |
            ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $projectRunRequest -Encoding utf8
    }
    try {
        $lines=@(Invoke-ProjectSql $ssh ($options+@('-p',$PortText,$Destination,"umask 077; ${guard}python3 -I -B '$Program' $Operation $context $inputFlags $Extra")))
    } catch {
        if($Operation -cne 'run' -or $LASTEXITCODE -ne 255) { throw }
        $observed=Observe-ProjectSqlRecovery
        Require-ProjectSql ($observed.status -ceq 'PASS') 'The original three-schema recovery did not pass; retain its failure and original bytes.'
        return $observed.result
    }
    Require-ProjectSql ($lines.Count -eq 1) 'A single bounded project SQL summary is required.'
    return $lines[0] | ConvertFrom-Json
}
function Observe-ProjectSqlRecovery {
    $requested=Test-ProjectSqlRunRequested
    $requestFlag=if($requested){'--run-requested'}else{''}
    for($readback=1;$readback -le 3;$readback++) {
        $observerArguments=$options+@('-p',$PortText,$Destination,"umask 077; ${guard}python3 -I -B '$recovery' observe $context $inputFlags --fixture-settings '$FixtureSettings' $requestFlag")
        $lines=@(& $ssh @observerArguments)
        $exit=$LASTEXITCODE
        $lines | Add-Content -LiteralPath (Join-Path $workspace 'artifacts/project-mysql-observe.stdout.log') -Encoding utf8
        if($exit -eq 255) { if($readback -lt 3){Start-Sleep -Seconds 2}; continue }
        Require-ProjectSql ($exit -eq 0 -and $lines.Count -gt 0) 'The original three-schema recovery has no readable terminal state; retain its resources.'
        $value=$lines[-1] | ConvertFrom-Json; Assert-ProjectSqlContext $value
        if($requested -and $value.status -ceq 'PENDING' -and $value.terminal -is [bool] -and -not $value.terminal -and $null -eq $value.executionId) {
            if($readback -lt 3){Start-Sleep -Seconds 2}; continue
        }
        Require-ProjectSql ($value.terminal -eq $true -and $value.status -cin @('PASS','FAILED','NOT_STARTED') -and
            (-not $requested -or $value.status -cne 'NOT_STARTED') -and
            (($value.status -ceq 'NOT_STARTED' -and $null -eq $value.executionId) -or
             ($value.status -cin @('PASS','FAILED') -and $value.executionId -cmatch '^[a-f0-9]{32}$'))) 'The observed three-schema terminal belongs to another operation.'
        $value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $workspace 'artifacts/project-mysql-observation.json') -Encoding utf8
        return $value
    }
    throw 'Cannot reconnect to the original three-schema recovery; do not restart it or cancel unknown work.'
}
function Test-ProjectSqlRunRequested {
    if(-not (Test-Path -LiteralPath $projectRunRequest)){return $false}
    Assert-ProjectSqlUnlinked $projectRunRequest
    Require-ProjectSql ((Get-Item -LiteralPath $projectRunRequest).Length -le 4096) 'Project SQL run request exceeds its metadata bound.'
    $request=Get-Content -LiteralPath $projectRunRequest -Raw -Encoding utf8 | ConvertFrom-Json
    Require-ProjectSql ($request.kind -ceq 'doorhandle-project-mysql-run-request' -and $request.release -ceq $Tag -and
        $request.commit -ceq $Commit -and $request.sourceSha256 -ceq $SourceSha256 -and
        $request.verificationReceiptSha256 -ceq $verificationSha -and $request.identity.instanceId -ceq $instance -and
        $request.identity.machineId -ceq $machine -and $request.batchReceiptSha256 -ceq $binding.batchReceiptSha256 -and
        $request.manifestSha256 -ceq $ManifestSha256 -and $request.archiveSha256 -ceq $ArchiveSha256 -and
        $request.runAttempted -is [bool] -and $request.runAttempted) 'Project SQL run request belongs to another fixed build.'
    return $true
}
function Collect-ProjectSqlReceipt([string]$RemoteRelative,[string]$ArtifactName,[string]$ExpectedSha) {
    Require-ProjectSql ($RemoteRelative -cmatch '^project-mysql[-a-z/]+\.json$' -and $ExpectedSha -cmatch '^[a-f0-9]{64}$') 'A fixed public metadata receipt is required.'
    $target=Join-Path $workspace ('artifacts/'+$ArtifactName)
    if (-not (Test-Path -LiteralPath $target)) { Invoke-ProjectSql $scp ($options+@('-P',$PortText,"${Destination}:$RemoteRoot/verification/$Tag/checkout/work/$RemoteRelative",$target)) | Out-Null }
    Assert-ProjectSqlUnlinked $target
    Require-ProjectSql ((Get-Item -LiteralPath $target).Length -gt 0 -and (Get-Item -LiteralPath $target).Length -le 128KB -and
        (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $ExpectedSha) 'The original public project SQL receipt changed in collection.'
}
function Collect-ProjectSqlCleanup {
    $null=Observe-ProjectSqlRecovery
    $value=Invoke-ProjectSqlRemote $recovery 'cleanup' "--fixture-settings '$FixtureSettings'"
    Assert-ProjectSqlContext $value
    Require-ProjectSql ($value.status -cin @('NOT_CREATED','STOPPED') -and $value.originalsChanged -eq $false -and
        $value.cleanupReceiptSha256 -cmatch '^[a-f0-9]{64}$') 'Owned project SQL resources were not proved stopped.'
    $relative=if($value.status -ceq 'NOT_CREATED') {'project-mysql-recovery-not-created.json'} else {'project-mysql-recovery/public-cleanup.json'}
    Collect-ProjectSqlReceipt $relative 'project-mysql-cleanup.json' $value.cleanupReceiptSha256
    return $value
}
if($Mode -ceq 'Preserve') {
    Require-ProjectSql ([IO.Path]::IsPathFullyQualified($SnapshotDirectory) -and $ManifestSha256 -cmatch '^[a-f0-9]{64}$' -and
        $ArchiveSha256 -cmatch '^[a-f0-9]{64}$') 'All three explicit sealed project inputs are required.'
    $local=[IO.Path]::GetFullPath($SnapshotDirectory).TrimEnd('\','/')
    Require-ProjectSql ($local -cmatch '^D:\\AI\\lunwen1\\DoorHandleCatch\\work\\data-migration-20261107\\project-mysql-custody-[A-Za-z0-9_.-]+$') 'Use the approved project-private three-schema packet.'
    Assert-ProjectSqlUnlinked $local
    $projectInputReader = @'
import hashlib,json,os,re,stat,sys
from pathlib import Path
directory=Path(sys.argv[1]); expected={'custody.json':sys.argv[2],'originals.tar.gz':sys.argv[3]}
assert {p.name for p in directory.iterdir()}==set(expected)
inputs={}
for name,checksum in expected.items():
 assert re.fullmatch('[a-f0-9]{64}',checksum)
 path=directory/name; original=path.lstat(); h=hashlib.sha256()
 with path.open('rb') as stream:
  before=os.fstat(stream.fileno()); assert stat.S_ISREG(before.st_mode) and before.st_nlink==1
  assert 0<before.st_size<=(1048576 if name=='custody.json' else 4*1024**3)
  for block in iter(lambda:stream.read(1048576),b''): h.update(block)
  after=os.fstat(stream.fileno())
 signature=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode,s.st_nlink)
 assert signature(original)==signature(before)==signature(after)==signature(path.lstat()) and h.hexdigest()==checksum
 inputs[name]={'bytes':before.st_size,'sha256':checksum}
value=json.loads((directory/'custody.json').read_bytes())
assert value['schemaVersion']==2 and value['kind']=='doorhandle-project-mysql-custody' and value['profile']=='project-mysql-three-schema-v2'
assert value['status']=='PACKED_RESTORE_PENDING' and re.fullmatch('[a-f0-9]{64}',value['batchReceiptSha256'])
assert value['archiveBytes']==inputs['originals.tar.gz']['bytes'] and value['archiveSha256']==expected['originals.tar.gz']
assert len(value['files'])==60 and set(value['schemas'])=={'doorhandledb','doorhandle_agent_verify_ef8d5844c1','doorhandle_model_verify_22e4bc5566'}
assert all(value[key] is False for key in ('liveSourceRowHashesVerified','productionMerged','retirementAllowed'))
print(json.dumps({'inputs':inputs,'batchReceiptSha256':value['batchReceiptSha256']}))
'@
    $binding=(Invoke-ProjectSql $python @('-I','-B','-c',$projectInputReader,$local,$ManifestSha256,$ArchiveSha256) | Select-Object -Last 1) | ConvertFrom-Json
    Require-ProjectSql (-not (Test-Path -LiteralPath $inputArtifact)) 'A fresh project SQL transport descriptor is required.'
    $descriptor=[ordered]@{kind='doorhandle-project-mysql-ci-inputs';release=$Tag;commit=$Commit;sourceSha256=$SourceSha256;
        verificationReceiptSha256=$verificationSha;identity=$accepted.identity;inputs=$binding.inputs;batchReceiptSha256=$binding.batchReceiptSha256;
        productionMerged=$false;retirementAllowed=$false}
    [IO.File]::WriteAllText($inputArtifact,($descriptor|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
} else {
    Assert-ProjectSqlUnlinked $inputArtifact
    Require-ProjectSql ((Get-Item -LiteralPath $inputArtifact).Length -le 32KB) 'Bounded public transport inputs required for cleanup.'
    $descriptor=Get-Content -LiteralPath $inputArtifact -Raw -Encoding utf8 | ConvertFrom-Json
    Require-ProjectSql ($descriptor.kind -ceq 'doorhandle-project-mysql-ci-inputs' -and $descriptor.release -ceq $Tag -and
        $descriptor.commit -ceq $Commit -and $descriptor.sourceSha256 -ceq $SourceSha256 -and
        $descriptor.verificationReceiptSha256 -ceq $verificationSha -and $descriptor.identity.instanceId -ceq $instance -and
        $descriptor.identity.machineId -ceq $machine -and $descriptor.identity.executionLocation -ceq 'ECS' -and
        $descriptor.inputs.'custody.json'.sha256 -ceq $ManifestSha256 -and $descriptor.inputs.'originals.tar.gz'.sha256 -ceq $ArchiveSha256 -and
        $descriptor.productionMerged -eq $false -and $descriptor.retirementAllowed -eq $false) 'Cleanup transport inputs differ from this fixed verified build.'
    $binding=$descriptor
}
Require-ProjectSql ($binding.batchReceiptSha256 -cmatch '^[a-f0-9]{64}$' -and
    (@($binding.inputs.PSObject.Properties.Name | Sort-Object)-join ',') -ceq 'custody.json,originals.tar.gz') 'Complete sealed project input bindings required.'
foreach($name in @('custody.json','originals.tar.gz')) {
    $row=$binding.inputs.$name; $maximum=if($name -ceq 'custody.json'){1MB}else{4GB}
    Require-ProjectSql (($row.bytes -is [int] -or $row.bytes -is [long]) -and $row.bytes -gt 0 -and $row.bytes -le $maximum -and
        $row.sha256 -cmatch '^[a-f0-9]{64}$') 'The project input SHA or byte bound differs.'
}
$inputFlags="--batch-receipt-sha256 '$($binding.batchReceiptSha256)' --manifest-sha256 '$($binding.inputs.'custody.json'.sha256)' --manifest-bytes $($binding.inputs.'custody.json'.bytes) --archive-sha256 '$($binding.inputs.'originals.tar.gz'.sha256)' --archive-bytes $($binding.inputs.'originals.tar.gz'.bytes)"
if($Mode -ceq 'Cleanup') { Collect-ProjectSqlCleanup | ConvertTo-Json -Depth 8 -Compress; return }
$failure=$null; $cleanupFailure=$null; $cleanup=$null; $result=$null; $phase='PREPARE'
try {
    $prepared=Invoke-ProjectSqlRemote $helper 'prepare'; Assert-ProjectSqlContext $prepared
    Require-ProjectSql ($prepared.status -ceq 'TRANSFER_DIRECTORY_PREPARED' -and
        $prepared.directory -ceq "$RemoteRoot/verification/$Tag/checkout/work/project-mysql-snapshot") 'The fresh private ECS transfer directory was not prepared.'
    Collect-ProjectSqlReceipt 'project-mysql-transfer.json' 'project-mysql-transfer.json' $prepared.transferReceiptSha256
    $phase='TRANSFER'
    foreach($name in @('custody.json','originals.tar.gz')) {
        $file=Join-Path $local $name; Assert-ProjectSqlUnlinked $file
        Require-ProjectSql ((Get-Item -LiteralPath $file).Length -eq $binding.inputs.$name.bytes -and
            (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $binding.inputs.$name.sha256) 'The local original changed before transfer.'
        Invoke-ProjectSql $scp ($options+@('-P',$PortText,$file,"${Destination}:$RemoteRoot/verification/$Tag/checkout/work/project-mysql-snapshot/$name")) | Out-Null
        Require-ProjectSql ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $binding.inputs.$name.sha256) 'The original changed during transfer.'
    }
    $phase='BYTE_RESTORE'; $bytes=Invoke-ProjectSqlRemote $helper 'restore'; Assert-ProjectSqlContext $bytes
    Require-ProjectSql ($bytes.status -ceq 'BYTES_RESTORED_VERIFIED' -and $bytes.manifestSha256 -ceq $ManifestSha256 -and
        $bytes.archiveSha256 -ceq $ArchiveSha256 -and $bytes.sqlDoubleRestoreVerified -eq $false -and
        $bytes.productionMerged -eq $false -and $bytes.retirementAllowed -eq $false) 'Actual original byte recovery failed.'
    Collect-ProjectSqlReceipt 'project-mysql-originals/restore-receipt.json' 'project-mysql-custody.json' $bytes.restoreReceiptSha256
    $phase='SQL_DOUBLE_RESTORE'; $result=Invoke-ProjectSqlRemote $recovery 'run' "--fixture-settings '$FixtureSettings'"
    Assert-ProjectSqlContext $result
    Require-ProjectSql ($result.status -ceq 'PROJECT_SQL_DOUBLE_RESTORED_VERIFIED' -and $result.allAcceptedDumpRowsPreserved -eq $true -and
        $result.liveSourceRowHashesVerified -eq $false -and $result.productionMerged -eq $false -and $result.retirementAllowed -eq $false -and
        $result.eventsExecuted -eq $false -and $result.paidModelCalls -eq 0 -and
        (@($result.schemas.PSObject.Properties.Name | Sort-Object)-join ',') -ceq 'doorhandle_agent_verify_ef8d5844c1,doorhandle_model_verify_22e4bc5566,doorhandledb') 'The complete three-schema recovery did not pass.'
    foreach($entry in $result.schemas.PSObject.Properties) {
        $expectedPurpose=if($entry.Name -ceq 'doorhandledb'){'BUSINESS_SOURCE'}else{'FIXTURE_ARCHIVE_ONLY'}
        Require-ProjectSql ($entry.Value.purpose -ceq $expectedPurpose -and $entry.Value.tableCount -gt 0 -and
            $entry.Value.snapshotSha256 -cmatch '^[a-f0-9]{64}$' -and $entry.Value.metadataSha256 -cmatch '^[a-f0-9]{64}$') 'Schema recovery metadata or archival purpose differs.'
    }
    Collect-ProjectSqlReceipt 'project-mysql-recovery/public-recovery.json' 'project-mysql-recovery.json' $result.recoveryReceiptSha256
} catch { $failure=$_ }
finally {
    try {
        $cleanup=Collect-ProjectSqlCleanup
        if(-not $failure) {
            Require-ProjectSql ($cleanup.derivedContainersRemoved -eq 2 -and $cleanup.derivedVolumesRemoved -eq 2 -and
                $cleanup.recoveryVolumesRetained -eq $false) 'Successful three-schema recovery requires exact owned derived cleanup.'
        }
    } catch { $cleanupFailure=$_ }
    $transport=[ordered]@{kind='doorhandle-project-mysql-ci';release=$Tag;commit=$Commit;sourceSha256=$SourceSha256;
        phase=$phase;status=$(if($failure -or $cleanupFailure){'FAILED_OR_UNKNOWN'}else{'COMPLETE'});
        manifestSha256=$ManifestSha256;archiveSha256=$ArchiveSha256;batchReceiptSha256=$binding.batchReceiptSha256;
        failureType=$(if($failure){$failure.Exception.GetType().Name}else{$null});remoteFailure=$script:projectRemoteFailure;
        cleanupStatus=$(if($cleanup){$cleanup.status}else{'UNKNOWN'});productionMerged=$false;retirementAllowed=$false}
    $transport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $workspace 'artifacts/project-mysql-ci.json') -Encoding utf8
}
if($failure){throw $failure}; if($cleanupFailure){throw $cleanupFailure}
Write-Output ([ordered]@{status='PROJECT_SQL_DOUBLE_RESTORED_VERIFIED';schemas=3;productionMerged=$false;retirementAllowed=$false}|ConvertTo-Json -Compress)
