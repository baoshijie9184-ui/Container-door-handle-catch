param(
    [Parameter(Mandatory = $true)][string[]]$SshOptions,
    [Parameter(Mandatory = $true)][string]$Destination,
    [Parameter(Mandatory = $true)][string]$PortText,
    [Parameter(Mandatory = $true)][string]$RemoteRoot,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$SourceSha256,
    [string]$SnapshotDirectory,
    [string]$EcsSnapshotDirectory,
    [ValidateSet('cold-store-originals-v1','cold-store-history-v2')][string]$Profile = 'cold-store-originals-v1'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$profileInfo = if ($Profile -ceq 'cold-store-history-v2') {
    @{inventorySha='61a9dddc73bbcd15be4dd6ad0cb11aed3ad805862eb99c4940ecf321df25f33a';files=16417;bytes=486493287;roots=4041;groups=4041;
      snapshot='cold-history-snapshot';public='cold-history-public-receipt.json';artifact='cold-history-custody-public';maxArchive=576MB}
} else {
    @{inventorySha='d31a1359676053b4182a0e4a9d15d8647cf17f93b2bc26bd7e84ce01116e2f6d';files=15750;bytes=12547814103;roots=70;groups=71;
      snapshot='cold-stores-snapshot';public='cold-stores-public-receipt.json';artifact='cold-store-custody-public';maxArchive=14GB}
}

function Require-Custody([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Assert-CustodyUnlinked([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        Require-Custody (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Custody paths cannot use links or junctions.'
        $item = if ($item -is [IO.FileInfo]) { $item.Directory } else { $item.Parent }
    }
}
function Invoke-Custody([string]$Executable, [string[]]$Arguments) {
    $output = & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Cold-store custody failed; originals and all private ECS inputs are retained.' }
    return $output
}

Require-Custody ($env:CI_ECS_VERIFIED -ceq 'true') 'Cold-store custody requires this build passing ECS verification.'
Require-Custody ($Profile -cin @('cold-store-originals-v1','cold-store-history-v2')) 'Select an exact fixed custody profile name.'
$localInput = -not [string]::IsNullOrWhiteSpace($SnapshotDirectory)
$ecsInput = -not [string]::IsNullOrWhiteSpace($EcsSnapshotDirectory)
Require-Custody ($localInput -xor $ecsInput) 'Select exactly one local or existing ECS custody snapshot; no automatic fallback is allowed.'
Require-Custody ($Destination -match '^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}$') 'Invalid custody SSH destination.'
Require-Custody ($PortText -match '^[0-9]{1,5}$' -and [int]$PortText -ge 1 -and [int]$PortText -le 65535) 'Invalid custody SSH port.'
Require-Custody ($RemoteRoot -match '^/(home|srv|opt)/[A-Za-z0-9_./-]+$' -and $RemoteRoot -notmatch '(^|/)\.\.(/|$)' -and -not $RemoteRoot.EndsWith('/')) 'Invalid ECS custody root.'
Require-Custody ($Commit -match '^[a-f0-9]{40}$' -and $Tag -match '^ci-[1-9][0-9]*-[a-f0-9]{12}$' -and $Tag.EndsWith('-' + $Commit.Substring(0, 12)) -and $SourceSha256 -match '^[a-f0-9]{64}$') 'Cold-store custody requires the fixed source commit and archive.'
$instance = $env:DOORHANDLE_ECS_INSTANCE_ID
$machine = $env:DOORHANDLE_ECS_MACHINE_ID
Require-Custody ($instance -match '^i-[a-z0-9]+$' -and $machine -match '^[a-f0-9]{32}$') 'Explicit custody ECS identity required.'
$ssh = (Get-Command ssh.exe -ErrorAction Stop | Select-Object -First 1).Source
$scp = (Get-Command scp.exe -ErrorAction Stop | Select-Object -First 1).Source
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$artifact = Join-Path $workspace "artifacts/ecs/$($profileInfo.artifact).json"
Require-Custody (-not (Test-Path -LiteralPath $artifact)) 'Use a fresh custody build; completed evidence is immutable.'
$verification = Join-Path $workspace 'artifacts/ecs/evidence/verification-receipt.json'
Assert-CustodyUnlinked $verification
$verified = Get-Content -LiteralPath $verification -Raw -Encoding UTF8 | ConvertFrom-Json
Require-Custody ($verified.status -ceq 'PASS' -and $verified.verificationExitCode -eq 0 -and $verified.release -ceq $Tag -and $verified.commit -ceq $Commit -and $verified.sourceSha256 -ceq $SourceSha256 -and $verified.identity.instanceId -ceq $instance -and $verified.identity.machineId -ceq $machine) 'This build has no matching actual passing ECS verification.'
$verificationSha = (Get-FileHash -LiteralPath $verification -Algorithm SHA256).Hash.ToLowerInvariant()
$archive = Join-Path $workspace 'artifacts/source.tar.gz'
Assert-CustodyUnlinked $archive
Require-Custody ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256) 'Fixed custody source archive changed.'
$python = $env:LOCAL_PYTHON_EXE
if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
Require-Custody ($python -and [IO.Path]::IsPathFullyQualified($python) -and (Test-Path -LiteralPath $python -PathType Leaf)) 'Configure the existing local byte-packaging Python.'
# This reader hashes committed source bytes only. It never imports the helper,
# opens an original database, or verifies/unpacks a local business archive.
$reader = @'
import hashlib,json,sys,tarfile
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    member=archive.getmember('script/jenkins/preserve-cold-stores.py')
    if not member.isfile() or not 0<member.size<=1048576 or archive.pax_headers.get('comment')!=sys.argv[2]:
        raise SystemExit('Fixed custody helper is unavailable')
    raw=archive.extractfile(member).read(1048577)
print(json.dumps({'sha256':hashlib.sha256(raw).hexdigest()}))
'@
$binding = (Invoke-Custody $python @('-I', '-B', '-c', $reader, $archive, $Commit) | Select-Object -Last 1) | ConvertFrom-Json
Require-Custody ($binding.sha256 -match '^[a-f0-9]{64}$') 'Committed custody helper digest missing.'
$helper = "$RemoteRoot/verification/$Tag/checkout/script/jenkins/preserve-cold-stores.py"
$helperGuard = "test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$($binding.sha256)' && "
$common = "--root '$RemoteRoot' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --expected-instance-id '$instance' --expected-machine-id '$machine'"
# Omit the default flag so the original profile remains callable against its
# fixed first-release helper. The second profile is always explicit.
if ($Profile -ceq 'cold-store-history-v2') { $common += " --profile '$Profile'" }
function Invoke-EcsCustody([string]$Mode, [string]$Extra) {
    $result = Invoke-Custody $ssh ($SshOptions + @('-p', $PortText, $Destination, "${helperGuard}python3 -I -B '$helper' $Mode $common $Extra"))
    return ($result | Select-Object -Last 1) | ConvertFrom-Json
}
$inventorySha = $profileInfo.inventorySha
$sourceReceiptSha = $null
if ($localInput) {
    Require-Custody ([IO.Path]::IsPathFullyQualified($SnapshotDirectory)) 'A full local custody snapshot directory is required.'
    $local = [IO.Path]::GetFullPath($SnapshotDirectory).TrimEnd('\', '/')
    $allowed = 'D:\AI\lunwen1\DoorHandleCatch\work\'
    Require-Custody ($local.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase) -and $local.Substring($allowed.Length) -match '^data-migration-[A-Za-z0-9_.-]+\\[^\\]+(?:\\[^\\]+)*$') 'Local custody inputs must remain in the approved project data-migration directory.'
    Assert-CustodyUnlinked $local
    $entries = @(Get-ChildItem -LiteralPath $local -Force)
    Require-Custody ($entries.Count -eq 3 -and @($entries | Where-Object { $_.PSIsContainer -or $_.Name -cnotin @('inventory.json', 'custody.json', 'originals.tar.gz') }).Count -eq 0) 'Only the three cold-store custody input files are accepted.'
    $inputs = @{}
    foreach ($name in @('inventory.json', 'custody.json', 'originals.tar.gz')) {
        $file = Join-Path $local $name; Assert-CustodyUnlinked $file
        $length = (Get-Item -LiteralPath $file).Length
        Require-Custody ($length -gt 0 -and $length -le $profileInfo.maxArchive -and ($name -eq 'originals.tar.gz' -or $length -le 64MB)) 'Custody input exceeds its byte budget.'
        $inputs[$name] = @{ bytes = $length; sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    $manifest = Get-Content -LiteralPath (Join-Path $local 'custody.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    Require-Custody ($manifest.version -eq 1 -and $manifest.kind -ceq 'doorhandle-cold-store-byte-custody' -and $manifest.profile -ceq $Profile -and $manifest.status -ceq 'COMPLETE' -and $manifest.inventorySha256 -ceq $inventorySha -and $inputs['inventory.json'].sha256 -ceq $inventorySha -and $manifest.files -eq $profileInfo.files -and $manifest.bytes -eq $profileInfo.bytes -and $manifest.roots -eq $profileInfo.roots -and $manifest.groups -eq $profileInfo.groups -and $manifest.heldAllSourcesExclusive -eq $true -and $manifest.archiveEncoding -ceq 'TAR_GZIP' -and $manifest.archiveBytes -eq $inputs['originals.tar.gz'].bytes -and $manifest.archiveSha256 -ceq $inputs['originals.tar.gz'].sha256) 'Local cold archive differs from the complete reviewed inventory.'
} else {
    $pattern = '^' + [regex]::Escape($RemoteRoot) + '/verification/ci-[1-9][0-9]*-[a-f0-9]{12}/checkout/work/' + [regex]::Escape($profileInfo.snapshot) + '$'
    Require-Custody ($EcsSnapshotDirectory -cmatch $pattern -and $EcsSnapshotDirectory -cne "$RemoteRoot/verification/$Tag/checkout/work/$($profileInfo.snapshot)") 'ECS custody reuse must name an earlier same-root fixed snapshot.'
    $description = Invoke-EcsCustody 'describe' "--source-snapshot-directory '$EcsSnapshotDirectory'"
    Require-Custody ($description.status -ceq 'DESCRIBED' -and $description.release -ceq $Tag -and $description.commit -ceq $Commit -and $description.sourceSha256 -ceq $SourceSha256 -and $description.identity.instanceId -ceq $instance -and $description.identity.machineId -ceq $machine -and $description.profile -ceq $Profile -and $description.inventorySha256 -ceq $inventorySha -and $description.files -eq $profileInfo.files -and $description.bytes -eq $profileInfo.bytes -and $description.roots -eq $profileInfo.roots -and $description.sourceCustodyReceiptSha256 -match '^[a-f0-9]{64}$') 'Existing ECS custody does not provide a matching public description.'
    Require-Custody ($description.archiveSha256 -match '^[a-f0-9]{64}$' -and $description.manifestSha256 -match '^[a-f0-9]{64}$' -and $description.archiveBytes -gt 0 -and $description.archiveBytes -le $profileInfo.maxArchive -and $description.manifestBytes -gt 0 -and $description.manifestBytes -le 64MB -and $description.inventoryBytes -gt 0 -and $description.inventoryBytes -le 64MB) 'ECS custody description exceeds its transport bounds.'
    $inputs = @{ 'inventory.json' = @{ bytes = $description.inventoryBytes; sha256 = $inventorySha }; 'custody.json' = @{ bytes = $description.manifestBytes; sha256 = $description.manifestSha256 }; 'originals.tar.gz' = @{ bytes = $description.archiveBytes; sha256 = $description.archiveSha256 } }
    $sourceReceiptSha = $description.sourceCustodyReceiptSha256
}
$inputFlags = "--inventory-sha256 '$($inputs['inventory.json'].sha256)' --inventory-bytes $($inputs['inventory.json'].bytes) --manifest-sha256 '$($inputs['custody.json'].sha256)' --manifest-bytes $($inputs['custody.json'].bytes) --archive-sha256 '$($inputs['originals.tar.gz'].sha256)' --archive-bytes $($inputs['originals.tar.gz'].bytes)"
if ($localInput) {
    $prepared = Invoke-EcsCustody 'prepare' $inputFlags
    Require-Custody ($prepared.status -ceq 'PREPARED' -and $prepared.release -ceq $Tag -and $prepared.commit -ceq $Commit -and $prepared.sourceSha256 -ceq $SourceSha256 -and $prepared.identity.instanceId -ceq $instance -and $prepared.identity.machineId -ceq $machine) 'ECS did not admit the new private custody destination.'
    $remoteSnapshot = "$RemoteRoot/verification/$Tag/checkout/work/$($profileInfo.snapshot)"
    foreach ($name in @('inventory.json', 'custody.json', 'originals.tar.gz')) {
        $file = Join-Path $local $name; Assert-CustodyUnlinked $file
        Invoke-Custody $scp ($SshOptions + @('-P', $PortText, $file, "${Destination}:$remoteSnapshot/$name")) | Out-Null
        Require-Custody ((Get-Item -LiteralPath $file).Length -eq $inputs[$name].bytes -and (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $inputs[$name].sha256) 'Local custody package changed during transfer.'
    }
    $public = Invoke-EcsCustody 'verify-restore' $inputFlags
} else {
    $public = Invoke-EcsCustody 'reuse' "$inputFlags --source-snapshot-directory '$EcsSnapshotDirectory' --source-receipt-sha256 '$sourceReceiptSha'"
}
Require-Custody ($public.status -ceq 'RESTORED_VERIFIED' -and $public.kind -ceq 'doorhandle-cold-store-byte-custody' -and $public.version -eq 1 -and $public.profile -ceq $Profile -and $public.release -ceq $Tag -and $public.commit -ceq $Commit -and $public.sourceSha256 -ceq $SourceSha256 -and $public.identity.instanceId -ceq $instance -and $public.identity.machineId -ceq $machine -and $public.identity.executionLocation -ceq 'ECS' -and $public.verificationReceiptSha256 -ceq $verificationSha -and $public.inventorySha256 -ceq $inventorySha -and $public.files -eq $profileInfo.files -and $public.bytes -eq $profileInfo.bytes -and $public.roots -eq $profileInfo.roots -and $public.restoredRoots -eq $profileInfo.groups -and $public.temporaryRestoresRemoved -eq $profileInfo.groups -and $public.manifestSha256 -ceq $inputs['custody.json'].sha256 -and $public.archiveSha256 -ceq $inputs['originals.tar.gz'].sha256 -and $public.archiveBytes -eq $inputs['originals.tar.gz'].bytes -and $public.sourceCustodyReceiptSha256 -ceq $sourceReceiptSha -and $public.originalFilesDeleted -eq 0 -and $public.databasesOpened -eq 0 -and $public.restoreReceiptSha256 -match '^[a-f0-9]{64}$' -and $public.publicReceiptSha256 -match '^[a-f0-9]{64}$') 'ECS cold-store custody restoration did not prove the admitted bytes and same-build identity.'
# Download only the explicitly projected public count/hash receipt. Business
# originals, filenames, source paths and original permissions stay private on ECS.
$pending = Join-Path $workspace "artifacts/ecs/$($profileInfo.artifact).pending.json"
Require-Custody (-not (Test-Path -LiteralPath $pending)) 'Use a fresh custody evidence destination.'
Invoke-Custody $scp ($SshOptions + @('-P', $PortText, "${Destination}:$RemoteRoot/verification/$Tag/checkout/work/$($profileInfo.public)", $pending)) | Out-Null
Assert-CustodyUnlinked $pending
Require-Custody ((Get-Item -LiteralPath $pending).Length -le 16384 -and (Get-FileHash -LiteralPath $pending -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $public.publicReceiptSha256) 'Public custody receipt raw bytes changed in transport.'
$received = Get-Content -LiteralPath $pending -Raw -Encoding UTF8 | ConvertFrom-Json
$allowedFields = @('version','kind','profile','release','commit','sourceSha256','identity','verificationReceiptSha256','inventorySha256','files','bytes','roots','status','manifestSha256','archiveSha256','archiveBytes','sourceCustodyReceiptSha256','restoredRoots','restoreReceiptSha256','originalFilesDeleted','databasesOpened','temporaryRestoresRemoved')
Require-Custody ((@($received.PSObject.Properties.Name | Sort-Object) -join ',') -ceq (@($allowedFields | Sort-Object) -join ',')) 'Public custody receipt includes unexpected data.'
foreach ($name in $allowedFields) {
    Require-Custody (($received.$name | ConvertTo-Json -Depth 5 -Compress) -ceq ($public.$name | ConvertTo-Json -Depth 5 -Compress)) 'Public custody receipt differs from the admitted server result.'
}
$raw = [IO.File]::ReadAllBytes($pending)
$stream = [IO.File]::Open($artifact, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($raw, 0, $raw.Length); $stream.Flush($true) } finally { $stream.Dispose() }
$public | ConvertTo-Json -Depth 5 -Compress
