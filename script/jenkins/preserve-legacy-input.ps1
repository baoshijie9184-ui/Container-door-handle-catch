param(
    [Parameter(Mandatory = $true)][string[]]$SshOptions,
    [Parameter(Mandatory = $true)][string]$Destination,
    [Parameter(Mandatory = $true)][string]$PortText,
    [Parameter(Mandatory = $true)][string]$RemoteRoot,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$SourceSha256,
    [string]$SnapshotDirectory = '',
    [string]$EcsSnapshotDirectory = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Require-Preservation([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Invoke-PreservationCommand([string]$Executable, [string[]]$Arguments) {
    $result = & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Legacy byte preservation stopped; original inputs and private ECS evidence are retained.' }
    return $result
}
function Assert-UnlinkedPath([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        Require-Preservation (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Preservation paths cannot use links or junctions.'
        if ($item -is [IO.FileInfo]) { $item = $item.Directory } else { $item = $item.Parent }
    }
}

Require-Preservation ($env:CI_ECS_VERIFIED -eq 'true') 'Legacy preservation requires this build passing ECS verification.'
Require-Preservation ($Destination -match '^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}$') 'Invalid admitted SSH destination.'
Require-Preservation ($PortText -match '^[0-9]{1,5}$' -and [int]$PortText -ge 1 -and [int]$PortText -le 65535) 'Invalid SSH port.'
Require-Preservation ($RemoteRoot -match '^/(home|srv|opt)/[A-Za-z0-9_./-]+$' -and $RemoteRoot -notmatch '(^|/)\.\.(/|$)' -and -not $RemoteRoot.EndsWith('/')) 'Invalid admitted ECS root.'
Require-Preservation ($Commit -match '^[a-f0-9]{40}$' -and $Tag -match '^ci-[0-9]+-[a-f0-9]{12}$' -and $Tag.EndsWith('-' + $Commit.Substring(0, 12))) 'Preservation requires this exact source commit and build.'
Require-Preservation ($SourceSha256 -match '^[a-f0-9]{64}$') 'Invalid source archive digest.'
$instance = $env:DOORHANDLE_ECS_INSTANCE_ID
$machine = $env:DOORHANDLE_ECS_MACHINE_ID
Require-Preservation ($instance -match '^i-[a-z0-9]+$' -and $machine -match '^[a-f0-9]{32}$') 'Explicit admitted ECS identity required.'
$ssh = (Get-Command ssh.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$scp = (Get-Command scp.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
Require-Preservation ((-not [string]::IsNullOrWhiteSpace($SnapshotDirectory)) -xor (-not [string]::IsNullOrWhiteSpace($EcsSnapshotDirectory))) 'Choose exactly one local byte snapshot or existing verified ECS snapshot.'

if (-not [string]::IsNullOrWhiteSpace($EcsSnapshotDirectory)) {
    $escapedRoot = [regex]::Escape($RemoteRoot)
    Require-Preservation ($EcsSnapshotDirectory -cmatch "^$escapedRoot/verification/ci-[0-9]+-[a-f0-9]{12}/checkout/work/legacy-source-snapshot$") 'ECS reuse accepts only a verified old snapshot in this same CI root.'
    $workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
    $artifact = Join-Path $workspace 'artifacts/legacy-source-preservation.json'
    Require-Preservation (-not (Test-Path -LiteralPath $artifact)) 'Use a fresh build; existing preservation evidence is never overwritten.'
    $verifiedFile = Join-Path $workspace 'artifacts/ecs/evidence/verification-receipt.json'
    $archive = Join-Path $workspace 'artifacts/source.tar.gz'
    foreach ($file in @($verifiedFile, $archive)) { Assert-UnlinkedPath $file }
    $verified = Get-Content -LiteralPath $verifiedFile -Raw -Encoding UTF8 | ConvertFrom-Json
    Require-Preservation ($verified.status -ceq 'PASS' -and $verified.verificationExitCode -eq 0 -and $verified.release -ceq $Tag -and $verified.commit -ceq $Commit -and $verified.sourceSha256 -ceq $SourceSha256 -and $verified.identity.instanceId -ceq $instance -and $verified.identity.machineId -ceq $machine -and $verified.identity.executionLocation -ceq 'ECS') 'Cloud snapshot reuse requires this fixed build passing ECS verification.'
    Require-Preservation ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256) 'The fixed source archive changed.'
    $python = $env:LOCAL_PYTHON_EXE
    if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
    Require-Preservation ($python -and [IO.Path]::IsPathFullyQualified($python) -and (Test-Path -LiteralPath $python -PathType Leaf)) 'Configure the existing local packaging Python.'
    $reader = @'
import hashlib,json,sys,tarfile
with tarfile.open(sys.argv[1],'r:gz') as archive:
    entries=[entry for entry in archive if entry.name=='script/jenkins/reuse-legacy-source.py']
    if len(entries)!=1 or not entries[0].isfile() or not 0<entries[0].size<=1048576 or archive.pax_headers.get('comment')!=sys.argv[2]:raise ValueError('Fixed cloud reuse recipe missing')
    raw=archive.extractfile(entries[0]).read(1048577)
    if len(raw)!=entries[0].size:raise ValueError('Truncated cloud reuse recipe')
print(json.dumps({'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}))
'@
    $binding = (Invoke-PreservationCommand $python @('-I', '-B', '-c', $reader, $archive, $Commit) | Select-Object -Last 1) | ConvertFrom-Json
    Require-Preservation ($binding.sha256 -cmatch '^[a-f0-9]{64}$' -and $binding.bytes -gt 0 -and $binding.bytes -le 1MB) 'Fixed reuse helper is unavailable.'
    $context = @{ root = $RemoteRoot; tag = $Tag; commit = $Commit; sourceSha256 = $SourceSha256;
        helperSha256 = $binding.sha256; helperBytes = $binding.bytes; sourceSnapshot = $EcsSnapshotDirectory;
        verificationReceiptSha256 = (Get-FileHash -LiteralPath $verifiedFile -Algorithm SHA256).Hash.ToLowerInvariant() }
    $bootstrap = @'
import base64,hashlib,json,os,stat,sys,tarfile
from pathlib import Path
def need(value):
    if not value:raise ValueError('Cloud snapshot reuse bootstrap refused')
def owned(path,maximum):
    need(path.resolve(strict=True)==path and path.is_file());info=path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and not info.st_mode&0o022 and info.st_size<=maximum)
def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for raw in iter(lambda:stream.read(1048576),b''):value.update(raw)
    return value.hexdigest()
data=json.loads(base64.b64decode(sys.argv[1]));root=Path(data['root']);inbox=root/'inbox'/data['tag']
for path in (root,root/'inbox',inbox):
    need(path.resolve(strict=True)==path and path.is_dir() and path.stat().st_uid==os.getuid() and not path.stat().st_mode&0o022)
source=inbox/'source.tar.gz';owned(source,134217728);need(digest(source)==data['sourceSha256'])
receipt=root/'verification'/data['tag']/'verification-receipt.json';owned(receipt,262144);need(digest(receipt)==data['verificationReceiptSha256'])
with tarfile.open(source,'r:gz') as archive:
    matches=[entry for entry in archive if entry.name=='script/jenkins/reuse-legacy-source.py']
    need(len(matches)==1 and matches[0].isfile() and matches[0].size==data['helperBytes'] and archive.pax_headers.get('comment')==data['commit'])
    raw=archive.extractfile(matches[0]).read(1048577);need(len(raw)==data['helperBytes'] and hashlib.sha256(raw).hexdigest()==data['helperSha256'])
target=inbox/'reuse-legacy-source.py'
if target.exists() or target.is_symlink():owned(target,1048576);need(digest(target)==data['helperSha256'])
else:
    with os.fdopen(os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
print(json.dumps({'status':'PREPARED','sha256':digest(target)}))
'@
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($bootstrap))
    $data = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($context | ConvertTo-Json -Depth 5 -Compress)))
    $launcher = 'import base64;exec(compile(base64.b64decode("' + $encoded + '"),"fixed-legacy-reuse-bootstrap","exec"))'
    $prepared = (Invoke-PreservationCommand $ssh ($SshOptions + @('-p', $PortText, $Destination, "python3 -I -B -c '$launcher' '$data'")) | Select-Object -Last 1) | ConvertFrom-Json
    Require-Preservation ($prepared.status -ceq 'PREPARED' -and $prepared.sha256 -ceq $binding.sha256) 'Cloud reuse recipe was not admitted.'
    $helper = "$RemoteRoot/inbox/$Tag/reuse-legacy-source.py"
    $arguments = "--root '$RemoteRoot' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --instance-id '$instance' --machine-id '$machine' --source-snapshot '$EcsSnapshotDirectory'"
    $public = (Invoke-PreservationCommand $ssh ($SshOptions + @('-p', $PortText, $Destination, "python3 -I -B '$helper' $arguments")) | Select-Object -Last 1) | ConvertFrom-Json
    Require-Preservation ($public.status -ceq 'RESTORED_VERIFIED' -and $public.kind -ceq 'doorhandle-legacy-source-preservation' -and $public.release -ceq $Tag -and $public.commit -ceq $Commit -and $public.sourceSha256 -ceq $SourceSha256 -and $public.identity.instanceId -ceq $instance -and $public.identity.machineId -ceq $machine -and $public.identity.executionLocation -ceq 'ECS' -and $public.verificationReceiptSha256 -ceq $context.verificationReceiptSha256 -and $public.restoreReceiptSha256 -cmatch '^[a-f0-9]{64}$' -and $public.memberInventorySha256 -cmatch '^[a-f0-9]{64}$' -and $public.sourceSnapshotReuse.oldOriginalsPreserved -eq $true -and $public.legacyKafkaReplay -ceq 'NOT_PERFORMED') 'Cloud archive reuse did not prove this exact independent byte restore.'
    Require-Preservation ($public.archiveSha256 -cmatch '^[a-f0-9]{64}$' -and $public.snapshotManifestSha256 -cmatch '^[a-f0-9]{64}$' -and $public.files -gt 0 -and $public.files -le 8192 -and $public.bytes -ge 0 -and $public.bytes -le 2GB -and $public.profile -cin @('legacy-stores-v1', 'legacy-stores-with-windows-mcp-v1', 'legacy-stores-with-windows-mcp-and-kafka-v1')) 'Cloud restore lacks its frozen inventory profile.'
    # Only bounded public counts/hashes are returned. No SCP of private source
    # bytes, source member paths, original permissions or manifest is performed.
    $stream = [IO.File]::Open($artifact, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($public | ConvertTo-Json -Depth 7)); $stream.Write($bytes, 0, $bytes.Length) }
    finally { $stream.Dispose() }
    Write-Host ("The {0} retained legacy files were copied and independently recovered within ECS." -f $public.files)
    return
}

# Local work is byte inventory, hashing and transfer only. No database, application
# process or project test is opened, imported or started by this stage.
Require-Preservation ([IO.Path]::IsPathFullyQualified($SnapshotDirectory)) 'A full local preservation directory is required.'
$local = [IO.Path]::GetFullPath($SnapshotDirectory).TrimEnd('\', '/')
$allowed = 'D:\AI\lunwen1\DoorHandleCatch\work\'
Require-Preservation ($local.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase) -and $local.Substring($allowed.Length) -match '^data-migration-[A-Za-z0-9_.-]+(?:\\[^\\]+)*$') 'Preservation input must stay under the approved project work/data-migration directory.'
Assert-UnlinkedPath $local
$entries = @(Get-ChildItem -LiteralPath $local -Force)
Require-Preservation ($entries.Count -eq 2 -and @($entries | Where-Object { $_.PSIsContainer -or $_.Name -cnotin @('snapshot.json', 'originals.tar') }).Count -eq 0) 'Only the two byte-preservation input files are accepted.'
$files = @{}
foreach ($name in @('snapshot.json', 'originals.tar')) {
    $path = Join-Path $local $name
    Assert-UnlinkedPath $path
    $info = Get-Item -LiteralPath $path -Force
    Require-Preservation (-not $info.PSIsContainer -and $info.Length -gt 0 -and $info.Length -le 512MB) 'Preservation input exceeds its byte budget.'
    $files[$name] = @{ bytes = $info.Length; sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
}
Require-Preservation ($files['snapshot.json'].bytes -le 16MB) 'Preservation manifest exceeds its metadata budget.'
$snapshot = Get-Content -LiteralPath (Join-Path $local 'snapshot.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Require-Preservation ($snapshot.format -eq 1 -and $snapshot.kind -eq 'legacy-stores-byte-preservation' -and $snapshot.status -eq 'COMPLETE' -and $snapshot.archiveSha256 -eq $files['originals.tar'].sha256 -and $snapshot.inventorySha256 -match '^[a-f0-9]{64}$') 'Inputs are not a completed byte-only source preservation snapshot.'
$kafkaProfile = 'legacy-stores-with-windows-mcp-and-kafka-v1'
$hasKafka = $snapshot.PSObject.Properties['profile'] -and $snapshot.profile -ceq $kafkaProfile
$logicalLimit = if ($hasKafka) { 2GB } else { 512MB }
$expectedFiles = @($snapshot.files).Count
Require-Preservation ($expectedFiles -gt 0 -and $expectedFiles -le 8192) 'Preservation member count exceeds its closed profile budget.'
$total = [long]0
$seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($file in $snapshot.files) {
    Require-Preservation (($file.bytes -is [long] -or $file.bytes -is [int]) -and $file.bytes -ge 0 -and $file.bytes -le 512MB -and $file.sha256 -match '^[a-f0-9]{64}$' -and $file.path -is [string] -and $file.path -notmatch '(^/|\\|:|(^|/)\.\.?(/|$)|//)' -and $seen.Add($file.path)) 'Invalid or repeated source byte inventory member.'
    $total += [long]$file.bytes
}
Require-Preservation ($total -eq $snapshot.originalBytes -and $total -le $logicalLimit) 'Source byte inventory total differs or exceeds its profile logical budget.'

$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$artifact = Join-Path $workspace 'artifacts/legacy-source-preservation.json'
Require-Preservation (-not (Test-Path -LiteralPath $artifact)) 'Use a fresh build; existing preservation evidence is never overwritten.'
$verifiedFile = Join-Path $workspace 'artifacts/ecs/evidence/verification-receipt.json'
Assert-UnlinkedPath $verifiedFile
$verified = Get-Content -LiteralPath $verifiedFile -Raw -Encoding UTF8 | ConvertFrom-Json
Require-Preservation ($verified.status -eq 'PASS' -and $verified.verificationExitCode -eq 0 -and $verified.release -eq $Tag -and $verified.commit -eq $Commit -and $verified.sourceSha256 -eq $SourceSha256 -and $verified.identity.instanceId -eq $instance -and $verified.identity.machineId -eq $machine) 'The collected ECS result does not admit this source and host.'
$archive = Join-Path $workspace 'artifacts/source.tar.gz'
Assert-UnlinkedPath $archive
Require-Preservation ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -eq $SourceSha256) 'This build source archive changed.'
$python = $env:LOCAL_PYTHON_EXE
if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
Require-Preservation ($python -and [IO.Path]::IsPathFullyQualified($python) -and (Test-Path -LiteralPath $python -PathType Leaf)) 'Configure the existing local packaging Python.'
$archiveReader = @'
import hashlib,json,sys,tarfile
from pathlib import Path
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    source=archive.getmember('script/memory/migrate_legacy_stores.py')
    assert source.isfile() and 0 < source.size <= 1048576
    assert archive.pax_headers.get('comment') == sys.argv[2]
    raw=archive.extractfile(source).read(1048577)
scope={'__name__':'fixed_byte_preservation_plan','__file__':str(Path(sys.argv[1]).resolve())}
exec(compile(raw,'fixed-source-byte-preservation','exec'),scope)
snapshot=Path(sys.argv[3]); manifest=scope['read_json'](snapshot/'snapshot.json')
plan=scope['validate_preservation_plan'](manifest)
verified=scope['verify_preservation'](snapshot)
assert verified['files']==plan['files'] and verified['bytes']==plan['bytes']
print(json.dumps({'sha256':hashlib.sha256(raw).hexdigest(),'plan':plan}))
'@
$scriptBinding = (Invoke-PreservationCommand $python @('-I', '-B', '-c', $archiveReader, $archive, $Commit, $local) | Select-Object -Last 1) | ConvertFrom-Json
Require-Preservation ($scriptBinding.sha256 -match '^[a-f0-9]{64}$') 'Fixed archive migration helper is unavailable.'
Require-Preservation ($scriptBinding.plan.profile -cin @('legacy-stores-v1', 'legacy-stores-with-windows-mcp-v1', $kafkaProfile) -and $scriptBinding.plan.files -eq $expectedFiles -and $scriptBinding.plan.bytes -eq $total -and $scriptBinding.plan.memberInventorySha256 -match '^[a-f0-9]{64}$' -and $scriptBinding.plan.logicalByteLimit -eq $logicalLimit -and $scriptBinding.plan.transportByteLimit -eq 512MB) 'Source member paths, roots and actual byte hashes do not match a reviewed preservation profile.'
Require-Preservation (($hasKafka -and $scriptBinding.plan.archiveEncoding -ceq 'TAR_GZIP' -and $scriptBinding.plan.kafkaFiles -eq 309 -and $scriptBinding.plan.kafkaBytes -eq 1184990233) -or (-not $hasKafka -and $scriptBinding.plan.archiveEncoding -ceq 'TAR' -and $scriptBinding.plan.kafkaFiles -eq 0 -and $scriptBinding.plan.kafkaBytes -eq 0)) 'Kafka preservation requires its complete frozen inventory and explicit compressed encoding.'
$context = @{ root = $RemoteRoot; tag = $Tag; commit = $Commit; sourceSha256 = $SourceSha256;
    scriptSha256 = $scriptBinding.sha256; instanceId = $instance; machineId = $machine;
    files = $files; expectedFiles = $expectedFiles; expectedBytes = $total;
    verificationReceiptSha256 = (Get-FileHash -LiteralPath $verifiedFile -Algorithm SHA256).Hash.ToLowerInvariant() }

# Send only this bounded controller as base64 code. Neither local paths nor
# private manifest content enter a shell string or a public build report.
$remoteProgram = @'
import base64,hashlib,json,os,runpy,stat,subprocess,sys,tarfile
from pathlib import Path
from urllib.request import ProxyHandler,Request,build_opener
def need(value):
    if not value: raise ValueError('Preservation admission failed')
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()
def canonical(path):
    need(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True)==path)
    return path
def private(path,value):
    with os.fdopen(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as stream:
        json.dump(value,stream,sort_keys=True)
def regular(path):
    canonical(path); info=path.stat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1)
    return info
data=json.loads(base64.b64decode(sys.argv[1])); mode=sys.argv[2]
snapshot=None; may_write=False
try:
    need(sys.platform=='linux' and Path('/etc/machine-id').read_text().strip()==data['machineId'])
    opener=build_opener(ProxyHandler({})); base='http://100.100.100.200/latest/'
    with opener.open(Request(base+'api/token',data=b'',method='PUT',headers={'X-aliyun-ecs-metadata-token-ttl-seconds':'60'}),timeout=4) as response:token=response.read(4096).decode()
    with opener.open(Request(base+'meta-data/instance-id',headers={'X-aliyun-ecs-metadata-token':token}),timeout=4) as response:need(response.read(256).decode().strip()==data['instanceId'])
    root=canonical(Path(data['root'])); attempt=canonical(root/'verification'/data['tag']); checkout=canonical(attempt/'checkout')
    receipt=attempt/'verification-receipt.json'; regular(receipt); need(digest(receipt)==data['verificationReceiptSha256']); accepted=json.loads(receipt.read_text())
    identity={'instanceId':data['instanceId'],'machineId':data['machineId'],'executionLocation':'ECS'}
    need(accepted.get('status')=='PASS' and accepted.get('verificationExitCode')==0 and accepted.get('release')==data['tag'] and accepted.get('commit')==data['commit'] and accepted.get('sourceSha256')==data['sourceSha256'] and accepted.get('identity')==identity)
    source=canonical(root/'inbox'/data['tag']/'source.tar.gz'); regular(source); need(digest(source)==data['sourceSha256'])
    with tarfile.open(source,'r:gz') as archive:
        entry=archive.getmember('script/memory/migrate_legacy_stores.py')
        need(entry.isfile() and 0<entry.size<=1048576 and archive.pax_headers.get('comment')==data['commit'])
        need(hashlib.sha256(archive.extractfile(entry).read(1048577)).hexdigest()==data['scriptSha256'])
    helper=checkout/'script/memory/migrate_legacy_stores.py'; regular(helper); need(digest(helper)==data['scriptSha256'])
    work=canonical(checkout/'work'); need(work.stat().st_uid==os.getuid() and not work.stat().st_mode&0o022)
    snapshot=work/'legacy-source-snapshot'; restore=work/'legacy-source-restore'
    if mode=='prepare':
        need(not snapshot.exists() and not snapshot.is_symlink() and not restore.exists() and not restore.is_symlink())
        usage=os.statvfs(work); need(usage.f_bavail*usage.f_frsize >= (2*1024+256)*1024**2+data['expectedBytes']+sum(v['bytes'] for v in data['files'].values()))
        snapshot.mkdir(mode=0o700)
        may_write=True
        for name in ('snapshot.json','originals.tar'):
            os.close(os.open(snapshot/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600))
        print(json.dumps({'status':'PREPARED'}))
    else:
        need(mode=='restore'); canonical(snapshot); need(snapshot.stat().st_uid==os.getuid() and stat.S_IMODE(snapshot.stat().st_mode)==0o700)
        may_write=True
        need({file.name for file in snapshot.iterdir()}=={'snapshot.json','originals.tar'})
        for name,expected in data['files'].items():
            file=snapshot/name; info=regular(file); os.chmod(file,0o600); need(info.st_size==expected['bytes'] and digest(file)==expected['sha256'])
        stdout=snapshot/'verification.stdout.json'; stderr=snapshot/'verification.stderr'
        with os.fdopen(os.open(stdout,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as output,os.fdopen(os.open(stderr,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as error:
            result=subprocess.run([sys.executable,'-I','-B',str(helper),'snapshot-verify','--snapshot',str(snapshot),'--restore',str(restore),'--expected-instance-id',data['instanceId'],'--expected-machine-id',data['machineId']],cwd=checkout,stdout=output,stderr=error,timeout=600,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','PYTHON_DOTENV_DISABLED':'1'})
        need(result.returncode==0 and stdout.stat().st_size<=16384)
        report=json.loads(stdout.read_text()); expected={'status':'RESTORED_VERIFIED','archiveSha256':data['files']['originals.tar']['sha256'],'snapshotManifestSha256':data['files']['snapshot.json']['sha256'],'files':data['expectedFiles'],'bytes':data['expectedBytes']}
        need(report==expected)
        restored=restore/'restore-receipt.json'; regular(restored); need(json.loads(restored.read_text())==expected)
        need(json.loads((restore/'original-manifest.json').read_text())==json.loads((snapshot/'snapshot.json').read_text()))
        scope=runpy.run_path(str(helper),run_name='fixed_byte_preservation_public_plan')
        plan=scope['validate_preservation_plan'](json.loads((restore/'original-manifest.json').read_text()))
        public={**expected,'kind':'doorhandle-legacy-source-preservation','schemaVersion':1,'release':data['tag'],'commit':data['commit'],'sourceSha256':data['sourceSha256'],'scriptSha256':data['scriptSha256'],'identity':identity,'restoreReceiptSha256':digest(restored),'verificationReceiptSha256':digest(receipt),'archiveBytes':data['files']['originals.tar']['bytes'],'manifestBytes':data['files']['snapshot.json']['bytes'],'profile':plan['profile'],'archiveEncoding':plan['archiveEncoding'],'kafkaFiles':plan['kafkaFiles'],'kafkaBytes':plan['kafkaBytes'],'legacyKafkaReplay':'NOT_PERFORMED'}
        private(snapshot/'preservation-public.json',public)
        print(json.dumps(public,sort_keys=True))
except BaseException as error:
    if may_write and snapshot is not None and snapshot.is_dir() and not snapshot.is_symlink():
        try:private(snapshot/'preservation-failed.json',{'status':'FAILED','errorType':type(error).__name__})
        except BaseException:pass
    print(json.dumps({'status':'FAILED','errorType':type(error).__name__}),file=sys.stderr)
    raise SystemExit(1)
'@
$encodedProgram = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteProgram))
$encodedContext = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($context | ConvertTo-Json -Depth 8 -Compress)))
$launcher = 'import base64;exec(compile(base64.b64decode("' + $encodedProgram + '"),"legacy-preservation-controller","exec"))'
$baseCommand = "python3 -I -B -c '$launcher' '$encodedContext'"
$prepared = (Invoke-PreservationCommand $ssh ($SshOptions + @('-p', $PortText, $Destination, "$baseCommand prepare")) | Select-Object -Last 1) | ConvertFrom-Json
Require-Preservation ($prepared.status -eq 'PREPARED') 'Remote private snapshot destination was not admitted.'
$remoteSnapshot = "$RemoteRoot/verification/$Tag/checkout/work/legacy-source-snapshot"
foreach ($name in @('snapshot.json', 'originals.tar')) {
    $path = Join-Path $local $name
    Assert-UnlinkedPath $path
    Require-Preservation ((Get-Item -LiteralPath $path).Length -eq $files[$name].bytes -and (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -eq $files[$name].sha256) 'Local preservation input changed before transfer.'
    $null = Invoke-PreservationCommand $scp ($SshOptions + @('-P', $PortText, $path, "${Destination}:$remoteSnapshot/$name"))
    Require-Preservation ((Get-Item -LiteralPath $path).Length -eq $files[$name].bytes -and (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -eq $files[$name].sha256) 'Local preservation input changed during transfer.'
}
$public = (Invoke-PreservationCommand $ssh ($SshOptions + @('-p', $PortText, $Destination, "$baseCommand restore")) | Select-Object -Last 1) | ConvertFrom-Json
Require-Preservation ($public.profile -ceq $scriptBinding.plan.profile -and $public.archiveEncoding -ceq $scriptBinding.plan.archiveEncoding -and $public.kafkaFiles -eq $scriptBinding.plan.kafkaFiles -and $public.kafkaBytes -eq $scriptBinding.plan.kafkaBytes -and $public.legacyKafkaReplay -ceq 'NOT_PERFORMED') 'ECS restoration did not attest the actual preserved Kafka inventory and encoding.'
Require-Preservation ($public.status -eq 'RESTORED_VERIFIED' -and $public.files -eq $expectedFiles -and $public.bytes -eq $total -and $public.archiveSha256 -eq $files['originals.tar'].sha256 -and $public.snapshotManifestSha256 -eq $files['snapshot.json'].sha256 -and $public.commit -eq $Commit -and $public.sourceSha256 -eq $SourceSha256 -and $public.scriptSha256 -eq $scriptBinding.sha256 -and $public.identity.instanceId -eq $instance -and $public.identity.machineId -eq $machine -and $public.restoreReceiptSha256 -match '^[a-f0-9]{64}$' -and $public.verificationReceiptSha256 -eq $context.verificationReceiptSha256) 'ECS byte-preservation recovery evidence is incomplete or belongs to another build.'
# Select public fields explicitly; never archive the private manifest or paths.
$summary = @{ schemaVersion = 1; kind = 'doorhandle-legacy-source-preservation'; status = $public.status;
    release = $Tag; commit = $Commit; sourceSha256 = $SourceSha256; scriptSha256 = $scriptBinding.sha256;
    identity = @{ instanceId = $instance; machineId = $machine; executionLocation = 'ECS' };
    files = $expectedFiles; bytes = $total; archiveBytes = $files['originals.tar'].bytes; manifestBytes = $files['snapshot.json'].bytes;
    profile = $scriptBinding.plan.profile; memberInventorySha256 = $scriptBinding.plan.memberInventorySha256;
    archiveEncoding = $public.archiveEncoding; kafkaFiles = $public.kafkaFiles; kafkaBytes = $public.kafkaBytes; legacyKafkaReplay = $public.legacyKafkaReplay;
    archiveSha256 = $files['originals.tar'].sha256; snapshotManifestSha256 = $files['snapshot.json'].sha256;
    restoreReceiptSha256 = $public.restoreReceiptSha256; verificationReceiptSha256 = $public.verificationReceiptSha256 }
$stream = [IO.File]::Open($artifact, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($summary | ConvertTo-Json -Depth 6))
    $stream.Write($bytes, 0, $bytes.Length)
} finally { $stream.Dispose() }
Write-Host ("The {0} inventoried legacy source files were retained and recovered byte for byte on the admitted ECS." -f $expectedFiles)
