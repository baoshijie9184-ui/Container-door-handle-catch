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
    [ValidateSet('additional-local-artifacts-v1', 'residual-project-originals-v1')][string]$Profile = 'additional-local-artifacts-v1'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$profileSettings = if ($Profile -ceq 'additional-local-artifacts-v1') {
    @{ CatalogSha = 'e1258807aae1df63412e2190268351b1d63e770219ce9aba2d760f2f1bae1383'; Files = 36; Bytes = 465240718; MaximumArchive = 512MB; MaximumManifest = 2MB; Snapshot = 'additional-local-artifacts-snapshot'; Public = 'additional-local-artifacts-public-receipt.json'; Artifact = 'local-artifact-custody'; }
} else {
    @{ CatalogSha = 'a9b6498c0f0e59b8821b0dbd9a8a4c1488bd300a67d92049f673e687fd49a00c'; Files = 1968; Bytes = 8779830; MaximumArchive = 32MB; MaximumManifest = 2MB; Snapshot = 'residual-project-originals-snapshot'; Public = 'residual-project-originals-public-receipt.json'; Artifact = 'residual-artifact-custody'; }
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
    if ($LASTEXITCODE -ne 0) { throw 'Opaque custody failed; originals and all private ECS inputs are retained.' }
    return $output
}

Require-Custody ($env:CI_ECS_VERIFIED -ceq 'true') 'Opaque custody requires this build passing ECS verification.'
$localInput = -not [string]::IsNullOrWhiteSpace($SnapshotDirectory)
$ecsInput = -not [string]::IsNullOrWhiteSpace($EcsSnapshotDirectory)
Require-Custody ($localInput -xor $ecsInput) 'Select exactly one local or existing ECS custody snapshot; no automatic fallback is allowed.'
Require-Custody ($Destination -match '^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}$') 'Invalid custody SSH destination.'
Require-Custody ($PortText -match '^[0-9]{1,5}$' -and [int]$PortText -ge 1 -and [int]$PortText -le 65535) 'Invalid custody SSH port.'
Require-Custody ($RemoteRoot -match '^/(home|srv|opt)/[A-Za-z0-9_./-]+$' -and $RemoteRoot -notmatch '(^|/)\.\.(/|$)' -and -not $RemoteRoot.EndsWith('/')) 'Invalid ECS custody root.'
Require-Custody ($Commit -match '^[a-f0-9]{40}$' -and $Tag -match '^ci-[1-9][0-9]*-[a-f0-9]{12}$' -and $Tag.EndsWith('-' + $Commit.Substring(0, 12)) -and $SourceSha256 -match '^[a-f0-9]{64}$') 'Opaque custody requires the fixed source commit and archive.'
$instance = $env:DOORHANDLE_ECS_INSTANCE_ID
$machine = $env:DOORHANDLE_ECS_MACHINE_ID
Require-Custody ($instance -match '^i-[a-z0-9]+$' -and $machine -match '^[a-f0-9]{32}$') 'Explicit custody ECS identity required.'
$ssh = (Get-Command ssh.exe -ErrorAction Stop | Select-Object -First 1).Source
$scp = (Get-Command scp.exe -ErrorAction Stop | Select-Object -First 1).Source
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$artifact = Join-Path $workspace ('artifacts/' + $profileSettings.Artifact + '.json')
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
    member=archive.getmember('script/jenkins/preserve-local-artifacts.py')
    if not member.isfile() or not 0<member.size<=1048576 or archive.pax_headers.get('comment')!=sys.argv[2]:
        raise SystemExit('Fixed custody helper is unavailable')
    raw=archive.extractfile(member).read(1048577)
print(json.dumps({'sha256':hashlib.sha256(raw).hexdigest()}))
'@
$binding = (Invoke-Custody $python @('-I', '-B', '-c', $reader, $archive, $Commit) | Select-Object -Last 1) | ConvertFrom-Json
Require-Custody ($binding.sha256 -match '^[a-f0-9]{64}$') 'Committed custody helper digest missing.'
$helper = "$RemoteRoot/verification/$Tag/checkout/script/jenkins/preserve-local-artifacts.py"
$helperGuard = "test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$($binding.sha256)' && "
$common = "--root '$RemoteRoot' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --expected-instance-id '$instance' --expected-machine-id '$machine'"
if ($Profile -cne 'additional-local-artifacts-v1') { $common += " --profile '$Profile'" }
function Invoke-EcsCustody([string]$Mode, [string]$Extra) {
    $result = Invoke-Custody $ssh ($SshOptions + @('-p', $PortText, $Destination, "${helperGuard}python3 -I -B '$helper' $Mode $common $Extra"))
    return ($result | Select-Object -Last 1) | ConvertFrom-Json
}
$catalogSha = $profileSettings.CatalogSha
$sourceReceiptSha = $null
if ($localInput) {
    Require-Custody ([IO.Path]::IsPathFullyQualified($SnapshotDirectory)) 'A full local custody snapshot directory is required.'
    $local = [IO.Path]::GetFullPath($SnapshotDirectory).TrimEnd('\', '/')
    $allowed = 'D:\AI\lunwen1\DoorHandleCatch\work\'
    Require-Custody ($local.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase) -and $local.Substring($allowed.Length) -match '^data-migration-[A-Za-z0-9_.-]+\\[^\\]+(?:\\[^\\]+)*$') 'Local custody inputs must remain in the approved project data-migration directory.'
    Assert-CustodyUnlinked $local
    $entries = @(Get-ChildItem -LiteralPath $local -Force)
    Require-Custody ($entries.Count -eq 2 -and @($entries | Where-Object { $_.PSIsContainer -or $_.Name -cnotin @('custody.json', 'originals.tar') }).Count -eq 0) 'Only the two opaque custody input files are accepted.'
    $inputs = @{}
    foreach ($name in @('custody.json', 'originals.tar')) {
        $file = Join-Path $local $name; Assert-CustodyUnlinked $file
        $length = (Get-Item -LiteralPath $file).Length
        Require-Custody ($length -gt 0 -and $length -le $profileSettings.MaximumArchive -and ($name -ne 'custody.json' -or $length -le $profileSettings.MaximumManifest)) 'Custody input exceeds its byte budget.'
        $inputs[$name] = @{ bytes = $length; sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    $manifest = Get-Content -LiteralPath (Join-Path $local 'custody.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    Require-Custody ($manifest.version -eq 1 -and $manifest.kind -ceq 'doorhandle-additional-local-artifact-custody' -and $manifest.profile -ceq $Profile -and $manifest.status -ceq 'COMPLETE' -and $manifest.catalogSha256 -ceq $catalogSha -and $manifest.originalFiles -eq $profileSettings.Files -and @($manifest.files).Count -eq $profileSettings.Files -and $manifest.originalBytes -eq $profileSettings.Bytes -and $manifest.archiveEncoding -ceq 'TAR' -and $manifest.archiveBytes -eq $inputs['originals.tar'].bytes -and $manifest.archiveSha256 -ceq $inputs['originals.tar'].sha256) 'Local opaque input is not the reviewed completed custody package.'
} else {
    $pattern = '^' + [regex]::Escape($RemoteRoot) + '/verification/ci-[1-9][0-9]*-[a-f0-9]{12}/checkout/work/' + [regex]::Escape($profileSettings.Snapshot) + '$'
    Require-Custody ($EcsSnapshotDirectory -cmatch $pattern -and $EcsSnapshotDirectory -cne "$RemoteRoot/verification/$Tag/checkout/work/$($profileSettings.Snapshot)") 'ECS custody reuse must name an earlier same-root fixed snapshot.'
    $description = Invoke-EcsCustody 'describe' "--source-snapshot-directory '$EcsSnapshotDirectory'"
    Require-Custody ($description.status -ceq 'DESCRIBED' -and $description.release -ceq $Tag -and $description.commit -ceq $Commit -and $description.sourceSha256 -ceq $SourceSha256 -and $description.identity.instanceId -ceq $instance -and $description.identity.machineId -ceq $machine -and $description.profile -ceq $Profile -and $description.catalogSha256 -ceq $catalogSha -and $description.files -eq $profileSettings.Files -and $description.bytes -eq $profileSettings.Bytes -and $description.sourceCustodyReceiptSha256 -match '^[a-f0-9]{64}$') 'Existing ECS custody does not provide a matching public description.'
    Require-Custody ($description.archiveSha256 -match '^[a-f0-9]{64}$' -and $description.manifestSha256 -match '^[a-f0-9]{64}$' -and $description.archiveBytes -gt 0 -and $description.archiveBytes -le $profileSettings.MaximumArchive -and $description.manifestBytes -gt 0 -and $description.manifestBytes -le $profileSettings.MaximumManifest) 'ECS custody description exceeds its transport bounds.'
    $inputs = @{ 'custody.json' = @{ bytes = $description.manifestBytes; sha256 = $description.manifestSha256 }; 'originals.tar' = @{ bytes = $description.archiveBytes; sha256 = $description.archiveSha256 } }
    $sourceReceiptSha = $description.sourceCustodyReceiptSha256
}
$inputFlags = "--manifest-sha256 '$($inputs['custody.json'].sha256)' --manifest-bytes $($inputs['custody.json'].bytes) --archive-sha256 '$($inputs['originals.tar'].sha256)' --archive-bytes $($inputs['originals.tar'].bytes)"
if ($localInput) {
    $prepared = Invoke-EcsCustody 'prepare' $inputFlags
    Require-Custody ($prepared.status -ceq 'PREPARED' -and $prepared.release -ceq $Tag -and $prepared.commit -ceq $Commit -and $prepared.sourceSha256 -ceq $SourceSha256 -and $prepared.identity.instanceId -ceq $instance -and $prepared.identity.machineId -ceq $machine) 'ECS did not admit the new private custody destination.'
    $remoteSnapshot = "$RemoteRoot/verification/$Tag/checkout/work/$($profileSettings.Snapshot)"
    foreach ($name in @('custody.json', 'originals.tar')) {
        $file = Join-Path $local $name; Assert-CustodyUnlinked $file
        Invoke-Custody $scp ($SshOptions + @('-P', $PortText, $file, "${Destination}:$remoteSnapshot/$name")) | Out-Null
        Require-Custody ((Get-Item -LiteralPath $file).Length -eq $inputs[$name].bytes -and (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $inputs[$name].sha256) 'Local custody package changed during transfer.'
    }
    $public = Invoke-EcsCustody 'verify-restore' $inputFlags
} else {
    $public = Invoke-EcsCustody 'reuse' "$inputFlags --source-snapshot-directory '$EcsSnapshotDirectory' --source-receipt-sha256 '$sourceReceiptSha'"
}
Require-Custody ($public.status -ceq 'RESTORED_VERIFIED' -and $public.kind -ceq 'doorhandle-additional-local-artifact-custody' -and $public.version -eq 1 -and $public.profile -ceq $Profile -and $public.release -ceq $Tag -and $public.commit -ceq $Commit -and $public.sourceSha256 -ceq $SourceSha256 -and $public.identity.instanceId -ceq $instance -and $public.identity.machineId -ceq $machine -and $public.identity.executionLocation -ceq 'ECS' -and $public.verificationReceiptSha256 -ceq $verificationSha -and $public.catalogSha256 -ceq $catalogSha -and $public.files -eq $profileSettings.Files -and $public.bytes -eq $profileSettings.Bytes -and $public.manifestSha256 -ceq $inputs['custody.json'].sha256 -and $public.archiveSha256 -ceq $inputs['originals.tar'].sha256 -and $public.archiveBytes -eq $inputs['originals.tar'].bytes -and $public.sourceCustodyReceiptSha256 -ceq $sourceReceiptSha -and $public.originalFilesDeleted -eq 0 -and $public.modelsExecuted -eq 0 -and $public.databasesOpened -eq 0 -and $public.restoreReceiptSha256 -match '^[a-f0-9]{64}$' -and $public.publicReceiptSha256 -match '^[a-f0-9]{64}$') 'ECS opaque custody restoration did not prove the admitted bytes and same-build identity.'
# Download only the explicitly projected public count/hash receipt. Business
# originals, filenames, source paths and original permissions stay private on ECS.
$pending = Join-Path $workspace ('artifacts/ecs/' + $profileSettings.Artifact + '-public.pending.json')
Require-Custody (-not (Test-Path -LiteralPath $pending)) 'Use a fresh custody evidence destination.'
Invoke-Custody $scp ($SshOptions + @('-P', $PortText, "${Destination}:$RemoteRoot/verification/$Tag/checkout/work/$($profileSettings.Public)", $pending)) | Out-Null
Assert-CustodyUnlinked $pending
Require-Custody ((Get-Item -LiteralPath $pending).Length -le 16384 -and (Get-FileHash -LiteralPath $pending -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $public.publicReceiptSha256) 'Public custody receipt raw bytes changed in transport.'
$received = Get-Content -LiteralPath $pending -Raw -Encoding UTF8 | ConvertFrom-Json
$allowedFields = @('version','kind','profile','release','commit','sourceSha256','identity','verificationReceiptSha256','catalogSha256','files','bytes','status','manifestSha256','archiveSha256','archiveBytes','sourceCustodyReceiptSha256','originalFilesDeleted','modelsExecuted','databasesOpened','restoreReceiptSha256')
Require-Custody ((@($received.PSObject.Properties.Name | Sort-Object) -join ',') -ceq (@($allowedFields | Sort-Object) -join ',')) 'Public custody receipt includes unexpected data.'
foreach ($name in $allowedFields) {
    Require-Custody (($received.$name | ConvertTo-Json -Depth 5 -Compress) -ceq ($public.$name | ConvertTo-Json -Depth 5 -Compress)) 'Public custody receipt differs from the admitted server result.'
}
$raw = [IO.File]::ReadAllBytes($pending)
$stream = [IO.File]::Open($artifact, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($raw, 0, $raw.Length); $stream.Flush($true) } finally { $stream.Dispose() }
$public | ConvertTo-Json -Depth 5 -Compress
