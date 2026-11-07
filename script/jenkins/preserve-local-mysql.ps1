param(
    [Parameter(Mandatory = $true)][string[]]$SshOptions,
    [Parameter(Mandatory = $true)][string]$Destination,
    [Parameter(Mandatory = $true)][string]$PortText,
    [Parameter(Mandatory = $true)][string]$RemoteRoot,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$SourceSha256,
    [string]$SnapshotDirectory,
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
$accepted = Get-Content -LiteralPath $verification -Raw -Encoding UTF8 | ConvertFrom-Json
Require-SqlCustody ($accepted.status -ceq 'PASS' -and $accepted.verificationExitCode -eq 0 -and $accepted.release -ceq $Tag -and
    $accepted.commit -ceq $Commit -and $accepted.sourceSha256 -ceq $SourceSha256 -and $accepted.identity.instanceId -ceq $instance -and
    $accepted.identity.machineId -ceq $machine) 'SQL custody lacks a same-build passing verification receipt.'
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
    for name in ('preserve-local-mysql.py','restore-local-mysql.py'):
        entry=archive.getmember('script/jenkins/'+name)
        assert entry.isfile() and 0<entry.size<=1048576
        data=archive.extractfile(entry).read(1048577)
        assert len(data)==entry.size
        result[name]=hashlib.sha256(data).hexdigest()
print(json.dumps(result))
'@
$sourceHashes = (Invoke-SqlCustody $python @('-I','-B','-c',$archiveReader,$sourceArchive,$Commit) | Select-Object -Last 1) | ConvertFrom-Json
$ssh = (Get-Command ssh.exe -ErrorAction Stop | Select-Object -First 1).Source
$scp = (Get-Command scp.exe -ErrorAction Stop | Select-Object -First 1).Source
$helper = "$RemoteRoot/verification/$Tag/checkout/script/jenkins/preserve-local-mysql.py"
$recovery = "$RemoteRoot/verification/$Tag/checkout/script/jenkins/restore-local-mysql.py"
$helperGuard = "test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$($sourceHashes.'preserve-local-mysql.py')' && "
$recoveryGuard = "test `"`$(sha256sum '$recovery' | cut -d ' ' -f 1)`" = '$($sourceHashes.'restore-local-mysql.py')' && "
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
$inputFlags = "--manifest-sha256 '$($bindings['custody.json'].sha256)' --manifest-bytes $($bindings['custody.json'].bytes) --archive-sha256 '$($bindings['originals.tar.gz'].sha256)' --archive-bytes $($bindings['originals.tar.gz'].bytes)"
function Ecs-SqlCustody([string]$Mode) {
    $result = Invoke-SqlCustody $ssh ($SshOptions + @('-p',$PortText,$Destination,"${helperGuard}python3 -I -B '$helper' $Mode $context $inputFlags"))
    return ($result | Select-Object -Last 1) | ConvertFrom-Json
}
$prepared = Ecs-SqlCustody 'prepare'
Require-SqlCustody ($prepared.status -ceq 'PREPARED' -and $prepared.release -ceq $Tag -and $prepared.commit -ceq $Commit) 'ECS did not admit the SQL custody destination.'
foreach ($name in @('custody.json','originals.tar.gz')) {
    $file = Join-Path $local $name
    Invoke-SqlCustody $scp ($SshOptions + @('-P',$PortText,$file,"${Destination}:$RemoteRoot/verification/$Tag/checkout/work/local-mysql-export-snapshot/$name")) | Out-Null
    Require-SqlCustody ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $bindings[$name].sha256) 'Local packet changed while transferring.'
}
$bytes = Ecs-SqlCustody 'verify-restore'
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
Write-Output ([ordered]@{status=$result.status;tableCount=45;rawSqlSha256=$result.rawSqlSha256;
    recoveryReceiptSha256=$result.recoveryReceiptSha256;retirementAllowed=$false;productionMerged=$false} | ConvertTo-Json -Compress)
