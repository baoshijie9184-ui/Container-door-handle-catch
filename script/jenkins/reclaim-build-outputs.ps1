param(
    [Parameter(Mandatory = $true)][string[]]$SshOptions,
    [Parameter(Mandatory = $true)][string]$Destination,
    [Parameter(Mandatory = $true)][string]$PortText,
    [Parameter(Mandatory = $true)][string]$RemoteRoot,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$SourceSha256
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Require-Reclaim([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Assert-ReclaimPath([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        Require-Reclaim (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Cleanup evidence cannot use links or junctions.'
        if ($item -is [IO.FileInfo]) { $item = $item.Directory } else { $item = $item.Parent }
    }
}
function Invoke-Reclaim([string]$Executable, [string[]]$Arguments) {
    $result = & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Build output cleanup refused or failed; original data and evidence are retained.' }
    return $result
}

Require-Reclaim ($env:CI_ECS_VERIFIED -ceq 'true') 'Cleanup requires this build passing ECS verification.'
Require-Reclaim ($Destination -cmatch '^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}$') 'Invalid admitted SSH destination.'
Require-Reclaim ($PortText -match '^[0-9]{1,5}$' -and [int]$PortText -ge 1 -and [int]$PortText -le 65535) 'Invalid SSH port.'
Require-Reclaim ($RemoteRoot -cmatch '^/(home|srv|opt)/[A-Za-z0-9_./-]+$' -and $RemoteRoot -notmatch '(^|/)\.\.?(/|$)|//' -and -not $RemoteRoot.EndsWith('/')) 'Invalid admitted ECS root.'
Require-Reclaim ($Commit -cmatch '^[a-f0-9]{40}$' -and $Tag -cmatch '^ci-[0-9]+-[a-f0-9]{12}$' -and $Tag.EndsWith('-' + $Commit.Substring(0, 12))) 'Cleanup requires this exact fixed commit and build.'
Require-Reclaim ($SourceSha256 -cmatch '^[a-f0-9]{64}$') 'Invalid fixed source archive SHA.'
$instance = $env:DOORHANDLE_ECS_INSTANCE_ID
$machine = $env:DOORHANDLE_ECS_MACHINE_ID
Require-Reclaim ($instance -cmatch '^i-[a-z0-9]+$' -and $machine -cmatch '^[a-f0-9]{32}$') 'Explicit admitted ECS identity required.'
$ssh = (Get-Command ssh.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$scp = (Get-Command scp.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$python = $env:LOCAL_PYTHON_EXE
if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
Require-Reclaim ($python -and [IO.Path]::IsPathFullyQualified($python) -and (Test-Path -LiteralPath $python -PathType Leaf)) 'Configure the existing local packaging Python.'
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$artifacts = Join-Path $workspace 'artifacts'
Assert-ReclaimPath $artifacts
$archive = Join-Path $artifacts 'source.tar.gz'
$verifiedFile = Join-Path $artifacts 'ecs/evidence/verification-receipt.json'
foreach ($file in @($archive, $verifiedFile)) { Assert-ReclaimPath $file }
Require-Reclaim ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256) 'The fixed source archive changed.'
$verified = Get-Content -LiteralPath $verifiedFile -Raw -Encoding UTF8 | ConvertFrom-Json
Require-Reclaim ($verified.status -ceq 'PASS' -and $verified.verificationExitCode -eq 0 -and $verified.release -ceq $Tag -and $verified.commit -ceq $Commit -and $verified.sourceSha256 -ceq $SourceSha256 -and $verified.identity.instanceId -ceq $instance -and $verified.identity.machineId -ceq $machine -and $verified.identity.executionLocation -ceq 'ECS') 'The current build lacks a matching passing ECS verification receipt.'
$localPlan = Join-Path $artifacts 'build-cleanup-plan.json'
$localReceipt = Join-Path $artifacts 'build-cleanup-receipt.json'
$localResult = Join-Path $artifacts 'build-cleanup-result.json'
foreach ($file in @($localPlan, $localReceipt, $localResult)) {
    Require-Reclaim (-not (Test-Path -LiteralPath $file)) 'Cleanup evidence already exists; use a fresh build.'
}

# Byte inspection only: never import a project helper or run a local test.
$archiveReader = @'
import hashlib,json,sys,tarfile
wanted={'script/jenkins/cleanup-ecs-builds.py','script/jenkins/verify-remote.py'}; result={}
with tarfile.open(sys.argv[1],'r:gz') as archive:
    for entry in archive:
        if entry.name not in wanted: continue
        if not entry.isfile() or not 0<entry.size<=1048576 or entry.name in result: raise ValueError('Invalid fixed helper member')
        raw=archive.extractfile(entry).read(1048577)
        if len(raw)!=entry.size: raise ValueError('Truncated fixed helper')
        result[entry.name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    if archive.pax_headers.get('comment')!=sys.argv[2] or set(result)!=wanted: raise ValueError('Fixed helper commit differs')
print(json.dumps(result))
'@
$helpers = (Invoke-Reclaim $python @('-I', '-B', '-c', $archiveReader, $archive, $Commit) | Select-Object -Last 1) | ConvertFrom-Json -AsHashtable
$context = @{ root = $RemoteRoot; tag = $Tag; commit = $Commit; sourceSha256 = $SourceSha256;
    instanceId = $instance; machineId = $machine; helpers = $helpers;
    verificationReceiptSha256 = (Get-FileHash -LiteralPath $verifiedFile -Algorithm SHA256).Hash.ToLowerInvariant() }
$remoteProgram = @'
import base64,gzip,hashlib,json,os,stat,sys,tarfile
from pathlib import Path
from urllib.request import ProxyHandler,Request,build_opener
def need(v):
    if not v: raise ValueError('Fixed cleanup admission failed')
def owned(path,directory=False,maximum=33554432):
    need(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True)==path)
    for item in (path,*path.parents): need(not item.is_symlink())
    info=path.lstat(); need(info.st_uid==os.getuid() and not info.st_mode&0o022)
    need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=maximum)
    return info
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()
data=json.loads(base64.b64decode(sys.argv[1])); mode=sys.argv[2]
need(sys.platform=='linux' and Path('/etc/machine-id').read_text().strip()==data['machineId'])
opener=build_opener(ProxyHandler({})); base='http://100.100.100.200/latest/'
with opener.open(Request(base+'api/token',data=b'',method='PUT',headers={'X-aliyun-ecs-metadata-token-ttl-seconds':'60'}),timeout=4) as response:token=response.read(4096).decode()
with opener.open(Request(base+'meta-data/instance-id',headers={'X-aliyun-ecs-metadata-token':token}),timeout=4) as response:need(response.read(256).decode().strip()==data['instanceId'])
root=Path(data['root']); inbox=root/'inbox'/data['tag']
for path in (root,root/'inbox',inbox,root/'verification',root/'verification'/data['tag']): owned(path,True)
receipt=root/'verification'/data['tag']/'verification-receipt.json';owned(receipt,maximum=262144)
need(digest(receipt)==data['verificationReceiptSha256']); accepted=json.loads(receipt.read_text())
identity={'instanceId':data['instanceId'],'machineId':data['machineId'],'executionLocation':'ECS'}
need(all(accepted.get(k)==v for k,v in {'status':'PASS','verificationExitCode':0,'release':data['tag'],'commit':data['commit'],'sourceSha256':data['sourceSha256'],'identity':identity}.items()))
archive=inbox/'source.tar.gz';owned(archive,maximum=134217728);need(digest(archive)==data['sourceSha256'])
if mode=='prepare':
    class Bounded:
        def __init__(self,s):self.s,self.n=s,0
        def read(self,size=-1):
            remaining=536870912-self.n;raw=self.s.read(remaining+1 if size<0 else min(size,remaining+1));self.n+=len(raw);need(self.n<=536870912);return raw
    found={}
    with gzip.open(archive,'rb') as expanded,tarfile.open(fileobj=Bounded(expanded),mode='r|') as source:
        for entry in source:
            if entry.name not in data['helpers']:continue
            need(entry.isfile() and entry.name not in found and 0<entry.size<=1048576)
            raw=source.extractfile(entry).read(1048577);expected=data['helpers'][entry.name]
            need(len(raw)==entry.size==expected['bytes'] and hashlib.sha256(raw).hexdigest()==expected['sha256']);found[entry.name]=raw
        need(source.pax_headers.get('comment')==data['commit'] and set(found)==set(data['helpers']))
    for name,raw in found.items():
        target=inbox/Path(name).name
        if target.exists() or target.is_symlink():owned(target,maximum=1048576);need(digest(target)==data['helpers'][name]['sha256'])
        else:
            with os.fdopen(os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
    print(json.dumps({'status':'PREPARED','release':data['tag'],'sourceSha256':data['sourceSha256']}))
else:
    need(mode=='inspect');files={}
    for label,name in [('plan','build-cleanup-plan.json'),('receipt','build-cleanup-receipt.json')]:
        path=inbox/name
        if path.exists() or path.is_symlink():
            info=owned(path);files[label]={'bytes':info.st_size,'sha256':digest(path)}
    print(json.dumps({'status':'INSPECTED','release':data['tag'],'files':files}))
'@
$encodedProgram = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteProgram))
$encodedContext = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($context | ConvertTo-Json -Depth 8 -Compress)))
$launcher = 'import base64;exec(compile(base64.b64decode("' + $encodedProgram + '"),"fixed-build-cleanup-controller","exec"))'
$baseCommand = "python3 -I -B -c '$launcher' '$encodedContext'"
$remoteInbox = "$RemoteRoot/inbox/$Tag"
$helper = "$remoteInbox/cleanup-ecs-builds.py"
$arguments = "--root '$RemoteRoot' --current-tag '$Tag' --commit '$Commit' --source-archive '$remoteInbox/source.tar.gz' --source-sha256 '$SourceSha256' --instance-id '$instance' --machine-id '$machine'"

function Copy-ReclaimEvidence([string]$Name, [string]$LocalPath, $Expected) {
    Require-Reclaim ($Expected.bytes -gt 0 -and $Expected.bytes -le 32MB -and $Expected.sha256 -cmatch '^[a-f0-9]{64}$') 'Cleanup evidence exceeds its bound or lacks its actual hash.'
    if (-not (Test-Path -LiteralPath $LocalPath)) {
        $null = Invoke-Reclaim $scp ($SshOptions + @('-P', $PortText, "${Destination}:$remoteInbox/$Name", $LocalPath))
    }
    Assert-ReclaimPath $LocalPath
    Require-Reclaim ((Get-Item -LiteralPath $LocalPath).Length -eq $Expected.bytes -and (Get-FileHash -LiteralPath $LocalPath -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $Expected.sha256) 'Cleanup evidence changed during collection; existing evidence is retained.'
}
$evidenceReader = @'
import hashlib,json,sys
from pathlib import Path
def unique(pairs):
    value={}
    for k,v in pairs:
        if k in value:raise ValueError('Duplicate cleanup evidence field')
        value[k]=v
    return value
raw=Path(sys.argv[1]).read_bytes()
if not 0<len(raw)<=33554432:raise ValueError('Cleanup evidence exceeds its bound')
v=json.loads(raw,object_pairs_hook=unique);result={'rawSha256':hashlib.sha256(raw).hexdigest(),'canonicalSha256':hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()}
result.update({k:v[k] for k in ('kind','currentRelease','identity')})
if 'status' in v:result['status']=v['status']
for k in ('planSha256','originalEvidencePreserved','sharedMavenCachePreserved','publishedArtifactsPreserved','oldMavenRepositoriesPreserved','businessDataDeleted'):
    if k in v:result[k]=v[k]
print(json.dumps(result))
'@
$admitted = $false
$applyAttempted = $false
$completed = $false
$planProof = $null
$receiptProof = $null
$collectionFailed = $false
$failure = $null
try {
    $ready = (Invoke-Reclaim $ssh ($SshOptions + @('-p', $PortText, $Destination, "$baseCommand prepare")) | Select-Object -Last 1) | ConvertFrom-Json
    Require-Reclaim ($ready.status -ceq 'PREPARED' -and $ready.release -ceq $Tag -and $ready.sourceSha256 -ceq $SourceSha256) 'Current fixed cleanup helpers were not admitted.'
    $admitted = $true
    $null = Invoke-Reclaim $ssh ($SshOptions + @('-p', $PortText, $Destination, "python3 -I -B '$helper' plan $arguments --output '$remoteInbox/build-cleanup-plan.json'"))
    $inspection = (Invoke-Reclaim $ssh ($SshOptions + @('-p', $PortText, $Destination, "$baseCommand inspect")) | Select-Object -Last 1) | ConvertFrom-Json -AsHashtable
    Require-Reclaim ($inspection.files.ContainsKey('plan')) 'Read-only cleanup produced no plan.'
    Copy-ReclaimEvidence 'build-cleanup-plan.json' $localPlan $inspection.files.plan
    $planProof = (Invoke-Reclaim $python @('-I', '-B', '-c', $evidenceReader, $localPlan) | Select-Object -Last 1) | ConvertFrom-Json
    Require-Reclaim ($planProof.kind -ceq 'doorhandle-old-build-cleanup-plan' -and $planProof.currentRelease -ceq $Tag -and $planProof.identity.instanceId -ceq $instance -and $planProof.identity.machineId -ceq $machine -and $planProof.identity.executionLocation -ceq 'ECS') 'Collected cleanup plan belongs to another build or ECS.'
    $applyAttempted = $true
    $null = Invoke-Reclaim $ssh ($SshOptions + @('-p', $PortText, $Destination, "python3 -I -B '$helper' apply $arguments --plan '$remoteInbox/build-cleanup-plan.json' --plan-sha256 '$($planProof.rawSha256)' --output '$remoteInbox/build-cleanup-receipt.json'"))
    $completed = $true
} catch {
    $failure = $_
} finally {
    if ($admitted) {
        try {
            $inspection = (Invoke-Reclaim $ssh ($SshOptions + @('-p', $PortText, $Destination, "$baseCommand inspect")) | Select-Object -Last 1) | ConvertFrom-Json -AsHashtable
            if ($inspection.files.ContainsKey('plan')) { Copy-ReclaimEvidence 'build-cleanup-plan.json' $localPlan $inspection.files.plan }
            if ($inspection.files.ContainsKey('receipt')) {
                Copy-ReclaimEvidence 'build-cleanup-receipt.json' $localReceipt $inspection.files.receipt
                $receiptProof = (Invoke-Reclaim $python @('-I', '-B', '-c', $evidenceReader, $localReceipt) | Select-Object -Last 1) | ConvertFrom-Json
                Require-Reclaim ($null -ne $planProof -and $receiptProof.kind -ceq 'doorhandle-old-build-cleanup-receipt' -and $receiptProof.currentRelease -ceq $Tag -and $receiptProof.identity.instanceId -ceq $instance -and $receiptProof.identity.machineId -ceq $machine -and $receiptProof.identity.executionLocation -ceq 'ECS' -and $receiptProof.planSha256 -ceq $planProof.canonicalSha256 -and $receiptProof.status -cin @('REMOVED', 'NO_ACTION', 'PARTIAL_FAILURE') -and $receiptProof.originalEvidencePreserved -eq $true -and $receiptProof.sharedMavenCachePreserved -eq $true -and $receiptProof.publishedArtifactsPreserved -eq $true -and $receiptProof.oldMavenRepositoriesPreserved -eq $true -and $receiptProof.businessDataDeleted -eq $false) 'Collected cleanup receipt lacks its exact build, plan or preservation boundary.'
            }
            Require-Reclaim (-not $applyAttempted -or $null -ne $receiptProof) 'Cleanup execution lacks its original receipt; keep the build failed.'
        } catch { $collectionFailed = $true }
    }
    $status = if ($completed -and -not $collectionFailed -and $null -ne $receiptProof -and $receiptProof.status -cin @('REMOVED', 'NO_ACTION')) { $receiptProof.status } else { 'FAILED_OR_UNKNOWN' }
    $result = @{ schema = 1; kind = 'doorhandle-build-cleanup-controller'; status = $status; currentRelease = $Tag;
        commit = $Commit; sourceSha256 = $SourceSha256; identity = @{ instanceId = $instance; machineId = $machine; executionLocation = 'ECS' };
        applyAttempted = $applyAttempted; planCollected = (Test-Path -LiteralPath $localPlan); receiptCollected = (Test-Path -LiteralPath $localReceipt);
        collectionFailed = $collectionFailed; planRawSha256 = $(if ($null -ne $planProof) { $planProof.rawSha256 } else { $null });
        receiptRawSha256 = $(if ($null -ne $receiptProof) { $receiptProof.rawSha256 } else { $null });
        helperStatus = $(if ($null -ne $receiptProof) { $receiptProof.status } else { $null }) }
    $stream = [IO.File]::Open($localResult, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($result | ConvertTo-Json -Depth 6)); $stream.Write($bytes, 0, $bytes.Length) }
    finally { $stream.Dispose() }
}
if ($null -ne $failure -or $result.status -ceq 'FAILED_OR_UNKNOWN') {
    throw 'Old build output cleanup did not complete with verified original evidence; collected files are retained.'
}
Write-Host ('Old build output cleanup: ' + $result.status + '. Business data, original reports, source archives, published artifacts and dependency caches are retained.')
