param(
    [ValidateSet('Verified', 'Maintenance', 'Terminal')][string]$Mode = 'Verified',
    [switch]$GeneratedArtifacts,
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

if ($Mode -ceq 'Maintenance') {
    Require-Reclaim ($env:ACTION -ceq 'reclaim-build-outputs' -and $env:CI_ECS_VERIFIED -ceq 'false' -and $env:DOORHANDLE_CI_SCOPE -ceq 'source') 'Maintenance requires its explicit action without a test PASS.'
    foreach ($name in @('LEGACY_SOURCE_SNAPSHOT', 'LEGACY_SOURCE_ECS_SNAPSHOT', 'LOCAL_ARTIFACTS_SNAPSHOT', 'LOCAL_ARTIFACTS_ECS_SNAPSHOT', 'COLD_STORES_SNAPSHOT', 'COLD_STORES_ECS_SNAPSHOT', 'COLD_HISTORY_SNAPSHOT', 'COLD_HISTORY_ECS_SNAPSHOT', 'LOCAL_MYSQL_SNAPSHOT', 'LOCAL_MYSQL_ECS_SNAPSHOT', 'LOCAL_MYSQL_FIXTURE_SETTINGS', 'DOORHANDLE_CI_FIXTURE_MANIFEST', 'DOORHANDLE_CI_FIXTURE_SETTINGS', 'CANDIDATE_BUILD_TOOLS_ARCHIVE', 'COMPACT_CUTOVER_SETTINGS', 'COMPATIBLE_BACKEND_IMAGE', 'COMPATIBLE_RUNNER_IMAGE', 'REHEARSAL_MEMORY_EXTRACTION_MODEL')) {
        Require-Reclaim ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) 'Maintenance cannot accept business, fixture, model or build-image inputs.'
    }
    foreach ($name in @('DOORHANDLE_CI_AUTO_COMPACT_FIXTURES', 'PRODUCTION_RELEASE_ENABLED', 'DOORHANDLE_COMPACT_RELEASE_READY', 'DOORHANDLE_COMPACT_REHEARSAL_READY', 'REHEARSAL_KEEP')) {
        Require-Reclaim ([Environment]::GetEnvironmentVariable($name) -cne 'true') 'Maintenance cannot enable fixtures or application release.'
    }
} elseif ($Mode -ceq 'Terminal') {
    Require-Reclaim ($GeneratedArtifacts -and $env:CI_EVIDENCE_ARCHIVED -ceq 'true' -and
        $env:CI_GENERATED_CLEANUP_ELIGIBLE -ceq 'true' -and $env:CI_TERMINAL_RESULT -cin @('SUCCESS','UNSTABLE','FAILURE','ABORTED','NOT_BUILT')) 'Terminal cleanup requires completed remote-stage cleanup and archived original evidence, not a business-test PASS.'
} else { Require-Reclaim ($env:CI_ECS_VERIFIED -ceq 'true') 'Cleanup requires this build passing ECS verification.' }
Require-Reclaim (-not $GeneratedArtifacts -or $Mode -cin @('Maintenance','Terminal')) 'Generated lifecycle is an explicit maintenance or terminal operation.'
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
Assert-ReclaimPath $archive
Require-Reclaim ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256) 'The fixed source archive changed.'
$sourceBytes = (Get-Item -LiteralPath $archive).Length
Require-Reclaim ($sourceBytes -gt 0 -and $sourceBytes -le 128MB) 'The fixed source archive exceeds its byte bound.'
if ($Mode -ceq 'Maintenance') {
    $packageFile = Join-Path $artifacts 'release.json'; Assert-ReclaimPath $packageFile
    $package = Get-Content -LiteralPath $packageFile -Raw -Encoding UTF8 | ConvertFrom-Json
    Require-Reclaim ($package.schema -is [long] -and $package.schema -eq 1 -and $package.kind -ceq 'doorhandle-maintenance-source' -and $package.action -ceq 'reclaim-build-outputs' -and $package.maintenanceOnly -is [bool] -and $package.maintenanceOnly -ceq $true -and $package.testsExecuted -is [bool] -and $package.testsExecuted -ceq $false -and $package.applicationBuilt -is [bool] -and $package.applicationBuilt -ceq $false -and $package.release -ceq $Tag -and $package.commit -ceq $Commit -and $package.sourceSha256 -ceq $SourceSha256 -and $package.sourceBytes -is [long] -and $package.sourceBytes -eq $sourceBytes -and @($package.PSObject.Properties).Count -eq 10) 'Maintenance requires its exact source-only package without application build or test evidence.'
    Require-Reclaim (-not (Test-Path -LiteralPath $verifiedFile)) 'Maintenance must not carry a test verification receipt.'
} elseif ($Mode -ceq 'Verified') {
    Assert-ReclaimPath $verifiedFile
    $verified = Get-Content -LiteralPath $verifiedFile -Raw -Encoding UTF8 | ConvertFrom-Json
    Require-Reclaim ($verified.status -ceq 'PASS' -and $verified.verificationExitCode -eq 0 -and $verified.release -ceq $Tag -and $verified.commit -ceq $Commit -and $verified.sourceSha256 -ceq $SourceSha256 -and $verified.identity.instanceId -ceq $instance -and $verified.identity.machineId -ceq $machine -and $verified.identity.executionLocation -ceq 'ECS') 'The current build lacks a matching passing ECS verification receipt.'
}
$evidencePrefix = if ($GeneratedArtifacts) { 'generated-cleanup' } else { 'build-cleanup' }
$localPlan = Join-Path $artifacts "$evidencePrefix-plan.json"
$localReceipt = Join-Path $artifacts "$evidencePrefix-receipt.json"
$localResult = Join-Path $artifacts "$evidencePrefix-result.json"
foreach ($file in @($localPlan, $localReceipt, $localResult)) {
    Require-Reclaim (-not (Test-Path -LiteralPath $file)) 'Cleanup evidence already exists; use a fresh build.'
}

# Byte inspection only: never import a project helper or run a local test.
$archiveReader = @'
import gzip,hashlib,json,os,stat,sys,tarfile
wanted={'script/jenkins/cleanup-ecs-builds.py','script/jenkins/verify-remote.py'}; result={}
if sys.argv[3]=='True':wanted.add('script/jenkins/retire-source-pytest.py')
class Bounded:
    def __init__(self,s):self.s,self.n=s,0
    def read(self,size=-1):
        remaining=536870912-self.n;raw=self.s.read(remaining+1 if size<0 else min(size,remaining+1));self.n+=len(raw)
        if self.n>536870912:raise ValueError('Source archive expansion exceeded')
        return raw
info=os.stat(sys.argv[1],follow_symlinks=False)
if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<info.st_size<=134217728:raise ValueError('Invalid fixed source archive')
with gzip.open(sys.argv[1],'rb') as expanded,tarfile.open(fileobj=Bounded(expanded),mode='r|') as archive:
    count=0
    for entry in archive:
        count+=1
        if count>50000 or entry.size<0 or entry.size>33554432:raise ValueError('Source member bound exceeded')
        if entry.name not in wanted: continue
        if entry.type not in (tarfile.REGTYPE,tarfile.AREGTYPE) or entry.sparse is not None or not 0<entry.size<=1048576 or entry.name in result: raise ValueError('Invalid fixed helper member')
        raw=archive.extractfile(entry).read(1048577)
        if len(raw)!=entry.size: raise ValueError('Truncated fixed helper')
        result[entry.name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    if archive.pax_headers.get('comment')!=sys.argv[2]: raise ValueError('Fixed helper commit differs')
    if set(result)!=wanted: raise ValueError('Required cleanup helper missing from fixed source archive')
print(json.dumps(result))
'@
$helpers = (Invoke-Reclaim $python @('-I', '-B', '-c', $archiveReader, $archive, $Commit, ([bool]$GeneratedArtifacts).ToString()) | Select-Object -Last 1) | ConvertFrom-Json -AsHashtable
$context = @{ root = $RemoteRoot; tag = $Tag; commit = $Commit; sourceSha256 = $SourceSha256;
    instanceId = $instance; machineId = $machine; helpers = $helpers; mode = $Mode; sourceBytes = $sourceBytes;
    evidencePrefix = $evidencePrefix; generated = [bool]$GeneratedArtifacts }
if ($Mode -ceq 'Verified') { $context.verificationReceiptSha256 = (Get-FileHash -LiteralPath $verifiedFile -Algorithm SHA256).Hash.ToLowerInvariant() }
if ($GeneratedArtifacts -and $Mode -ceq 'Maintenance') {
    $manifestPath = $env:GENERATED_RETENTION_MANIFEST
    Require-Reclaim ($manifestPath -and [IO.Path]::IsPathFullyQualified($manifestPath)) 'Generated maintenance requires the approved exact historical input manifest.'
    Assert-ReclaimPath $manifestPath
    $inputManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
    Require-Reclaim ($inputManifest.schemaVersion -eq 1 -and $inputManifest.root -ceq $RemoteRoot -and
        $inputManifest.identity.instanceId -ceq $instance -and $inputManifest.identity.machineId -ceq $machine -and
        $inputManifest.rows.Count -gt 0 -and $inputManifest.rows.Count -le 128) 'Generated input belongs to another ECS or exceeds its exact bound.'
    Assert-ReclaimPath $inputManifest.authorizationFile
    $authorization = Get-Content -LiteralPath $inputManifest.authorizationFile -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
    Require-Reclaim ($authorization.version -eq 1 -and $authorization.userReply -and
        $authorization.diskExpansionAuthorized -eq $false -and $authorization.blanketDockerPruneAuthorized -eq $false -and
        'ci-266-f6e062edc7b6' -cin $authorization.excluded) 'Generated maintenance lacks the recorded scoped authorization.'
    $kindMap = @{OFFICIAL_OCI='GENERATED_OCI_CACHE';OFFICIAL_IMAGE_TAR='GENERATED_IMAGE_ARCHIVE';NPM_CACACHE='NPM_CACHE';OLD_PRIVATE_MAVEN='RETIRED_PRIVATE_MAVEN'}
    $rows = @()
    foreach ($row in $inputManifest.rows) {
        Require-Reclaim ($row.release -cmatch '^ci-[0-9]+-[a-f0-9]{12}$' -and $row.commit -cmatch '^[a-f0-9]{40}$' -and
            $row.release.EndsWith('-'+$row.commit.Substring(0,12)) -and $row.sourceSha256 -cmatch '^[a-f0-9]{64}$' -and
            $row.release -cne 'ci-266-f6e062edc7b6') 'Historical generated source identity is invalid or protected.'
        $terminal = @{kind='REMOTE_VERIFICATION';result='FAILURE';completed=$true;evidenceArchived=$true}
        if ($row.jenkinsOriginal.buildXmlExists) {
            $xmlPath = $row.jenkinsOriginal.buildXml; Assert-ReclaimPath $xmlPath
            $settings = [Xml.XmlReaderSettings]::new(); $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit; $settings.XmlResolver = $null
            $raw = Get-Content -LiteralPath $xmlPath -Raw -Encoding UTF8
            $reader = [Xml.XmlReader]::Create([IO.StringReader]::new(($raw -replace '\A<\?xml version=["'']1\.1["'']','<?xml version="1.0"')), $settings)
            try { $doc = [Xml.XmlDocument]::new(); $doc.XmlResolver=$null; $doc.Load($reader) } finally { $reader.Dispose() }
            $resultNode=$doc.SelectSingleNode('/*/result'); $completedNode=$doc.SelectSingleNode('/*/completed'); $doneNode=$doc.SelectSingleNode('/*/execution/done')
            Require-Reclaim ($resultNode -and $resultNode.InnerText -cin @('SUCCESS','UNSTABLE','FAILURE','ABORTED','NOT_BUILT') -and
                $completedNode -and $completedNode.InnerText -ceq 'true' -and $doneNode -and $doneNode.InnerText -ceq 'true') 'Historical Jenkins run is not actually terminal.'
            $original = $row.originalRelease.path; Assert-ReclaimPath $original
            $release = Get-Content -LiteralPath $original -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
            Require-Reclaim ($release.release -ceq $row.release -and $release.commit -ceq $row.commit -and $release.sourceSha256 -ceq $row.sourceSha256) 'Original release metadata differs from historical generated source.'
            Assert-ReclaimPath $row.localOriginalPreservation.path
            $terminal = @{kind='JENKINS_HISTORY';result=$resultNode.InnerText;completed=$true;evidenceArchived=$true;
                buildXmlSha256=(Get-FileHash -LiteralPath $xmlPath -Algorithm SHA256).Hash.ToLowerInvariant();
                originalReleaseSha256=(Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash.ToLowerInvariant()}
        } else {
            Require-Reclaim ($row.evidenceType -ceq 'SOURCE_TERMINAL_ECS' -and $row.verification.exists -eq $true -and
                $row.verificationEvidenceArchive.exists -eq $true) 'Missing historical Jenkins evidence requires original terminal ECS source evidence.'
            $terminal.result = if ($row.verification.projection.status -ceq 'PASS') { 'SUCCESS' } else { 'FAILURE' }
        }
        $targets = @()
        foreach ($target in $row.targets) {
            Require-Reclaim ($kindMap.ContainsKey($target.kind)) 'Historical generated target category is unsupported.'
            $targets += @{kind=$kindMap[$target.kind];path=$target.path}
        }
        $rows += @{release=$row.release;commit=$row.commit;sourceSha256=$row.sourceSha256;terminal=$terminal;targets=$targets}
    }
    $requestValue = @{schema=1;kind='doorhandle-generated-artifact-cleanup-request';currentRelease=$Tag;
        identity=@{instanceId=$instance;machineId=$machine;executionLocation='ECS'};protectedReleases=@('ci-266-f6e062edc7b6');currentPost=$false;candidates=$rows}
    $requestLocal = Join-Path $artifacts 'generated-cleanup-request.json'
    Require-Reclaim (-not (Test-Path -LiteralPath $requestLocal)) 'Generated request must use a fresh controller output.'
    $requestBytes = [Text.UTF8Encoding]::new($false).GetBytes(($requestValue | ConvertTo-Json -Depth 16 -Compress))
    Require-Reclaim ($requestBytes.Length -gt 0 -and $requestBytes.Length -le 1MB) 'Generated request exceeds its transfer bound.'
    [IO.File]::WriteAllBytes($requestLocal,$requestBytes)
    $context.generatedRequest = @{bytes=$requestBytes.Length;sha256=(Get-FileHash -LiteralPath $requestLocal -Algorithm SHA256).Hash.ToLowerInvariant()}

}
$remoteProgram = @'
import base64,gzip,hashlib,json,os,stat,sys,tarfile
from contextlib import contextmanager
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

def chain(path,directory=False,maximum=33554432):
    need(path==root or path.is_relative_to(root))
    owned(root,True)
    for parent in reversed(path.parents):
        if parent!=root and parent.is_relative_to(root):owned(parent,True)
    info=owned(path,directory,maximum);need(info.st_dev==root.stat().st_dev)
    return info

def fingerprint(info):
    return [info.st_dev,info.st_ino,info.st_uid,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns]

@contextmanager
def held(path,maximum):
    before=chain(path,maximum=maximum)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        need(fingerprint(os.fstat(fd))==fingerprint(before))
        with os.fdopen(os.dup(fd),'rb') as stream:yield stream
        need(fingerprint(os.fstat(fd))==fingerprint(before)==fingerprint(chain(path,maximum=maximum)))
    finally:os.close(fd)
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()
data=json.loads(base64.b64decode(sys.argv[1])); mode=sys.argv[2]
need(sys.platform=='linux' and os.getuid()==os.geteuid()==1000 and Path('/etc/machine-id').read_text().strip()==data['machineId'])
need(data['mode'] in ('Verified','Maintenance','Terminal') and mode in ('bootstrap','prepare','inspect'))
need(data['evidencePrefix'] == ('generated-cleanup' if data['generated'] else 'build-cleanup'))
opener=build_opener(ProxyHandler({})); base='http://100.100.100.200/latest/'
with opener.open(Request(base+'api/token',data=b'',method='PUT',headers={'X-aliyun-ecs-metadata-token-ttl-seconds':'60'}),timeout=4) as response:token=response.read(4096).decode()
with opener.open(Request(base+'meta-data/instance-id',headers={'X-aliyun-ecs-metadata-token':token}),timeout=4) as response:need(response.read(256).decode().strip()==data['instanceId'])
root=Path(data['root']); inbox=root/'inbox'/data['tag']
identity={'instanceId':data['instanceId'],'machineId':data['machineId'],'executionLocation':'ECS'}
for path in (root,root/'inbox',root/'verification'):chain(path,True)
archive=inbox/('cleanup-source.tar.gz' if data['mode']=='Maintenance' else 'source.tar.gz')
def control_growth(include_source):
    usage=os.statvfs(root); unit=max(4096,usage.f_frsize)
    need(unit<=1048576 and unit&(unit-1)==0)
    expected={'script/jenkins/cleanup-ecs-builds.py','script/jenkins/verify-remote.py'}
    if data['generated']:expected.add('script/jenkins/retire-source-pytest.py')
    need(set(data['helpers'])==expected)
    sizes=[value['bytes'] for value in data['helpers'].values()]
    need(all(type(size) is int and 0<size<=1048576 for size in sizes))
    if include_source:sizes.append(data['sourceBytes'])
    if data.get('generatedRequest'):sizes.append(data['generatedRequest']['bytes'])
    # Only fixed archive/helper bytes and the existing directory/inode allowance
    # are written by this stage. The generated plan/journal/receipt are admitted
    # later from the actual in-memory plan; no file limit is reduced here.
    growth=sum(((size+unit-1)//unit)*unit for size in sizes)+1048576
    available=usage.f_bavail*usage.f_frsize
    need(available>=2147483648+growth)
    return growth,available,unit
if mode=='bootstrap':
    need(data['mode']=='Maintenance' and 0<data['sourceBytes']<=134217728)
    growth,available,unit=control_growth(True)
    targets=(inbox,root/'verification'/data['tag'])
    need(all(not os.path.lexists(path) for path in targets))
    for path in targets:
        parent=path.parent;fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            need(fingerprint(os.fstat(fd))==fingerprint(chain(parent,True)))
            # mkdir is atomic and fails if any prior attempt already owns name.
            os.mkdir(path.name,0o700,dir_fd=fd);os.fsync(fd);chain(path,True)
        finally:os.close(fd)
    fd=os.open(archive,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    try:
        os.fsync(fd);info=os.fstat(fd);need(info.st_uid==1000 and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600)
        uploadIdentity={'device':info.st_dev,'inode':info.st_ino}
    finally:os.close(fd)
    fd=os.open(inbox,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
    if data.get('generatedRequest'):
        fd=os.open(inbox/'generated-cleanup-request.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        try:os.fsync(fd)
        finally:os.close(fd)
    print(json.dumps({'status':'UPLOAD_REQUIRED','release':data['tag'],'commit':data['commit'],'sourceSha256':data['sourceSha256'],'sourceBytes':data['sourceBytes'],'identity':identity,'file':str(archive),'uploadIdentity':uploadIdentity,'availableBytes':available,'requiredBytes':2147483648+growth,'reserveBytes':2147483648,'controlGrowthBytes':growth-data['sourceBytes'],'allocationUnitBytes':unit}))
    raise SystemExit(0)
chain(inbox,True)
if data['mode']!='Terminal' or (root/'verification'/data['tag']).exists():chain(root/'verification'/data['tag'],True)
if data['mode']=='Verified':
    receipt=root/'verification'/data['tag']/'verification-receipt.json';chain(receipt,maximum=262144)
    need(digest(receipt)==data['verificationReceiptSha256']); accepted=json.loads(receipt.read_text())
    need(all(accepted.get(k)==v for k,v in {'status':'PASS','verificationExitCode':0,'release':data['tag'],'commit':data['commit'],'sourceSha256':data['sourceSha256'],'identity':identity}.items()))
elif data['mode']=='Maintenance':
    info=chain(archive,maximum=134217728)
    need(stat.S_IMODE(info.st_mode)==0o600 and info.st_size==data['sourceBytes'] and {'device':info.st_dev,'inode':info.st_ino}==data['uploadIdentity'])
    need(not os.path.lexists(root/'verification'/data['tag']/'verification-receipt.json'))
chain(archive,maximum=134217728);need(digest(archive)==data['sourceSha256'])
if mode=='prepare':
    control_growth(False)
    class Bounded:
        def __init__(self,s):self.s,self.n=s,0
        def read(self,size=-1):
            remaining=536870912-self.n;raw=self.s.read(remaining+1 if size<0 else min(size,remaining+1));self.n+=len(raw);need(self.n<=536870912);return raw
    found={};count=0
    with held(archive,134217728) as original:
        need(hashlib.file_digest(original,'sha256').hexdigest()==data['sourceSha256']);original.seek(0)
        with gzip.GzipFile(fileobj=original,mode='rb') as expanded,tarfile.open(fileobj=Bounded(expanded),mode='r|') as source:
            for entry in source:
                count+=1;need(count<=50000 and 0<=entry.size<=33554432)
                if entry.name not in data['helpers']:continue
                need(entry.type in (tarfile.REGTYPE,tarfile.AREGTYPE) and entry.sparse is None and entry.name not in found and 0<entry.size<=1048576)
                raw=source.extractfile(entry).read(1048577);expected=data['helpers'][entry.name]
                need(len(raw)==entry.size==expected['bytes'] and hashlib.sha256(raw).hexdigest()==expected['sha256']);found[entry.name]=raw
            need(source.pax_headers.get('comment')==data['commit'] and set(found)==set(data['helpers']))
        original.seek(0);need(hashlib.file_digest(original,'sha256').hexdigest()==data['sourceSha256'])
    for name,raw in found.items():
        target=inbox/Path(name).name
        if target.exists() or target.is_symlink():
            need(data['mode'] in ('Verified','Terminal'));chain(target,maximum=1048576);need(digest(target)==data['helpers'][name]['sha256'])
        else:
            with os.fdopen(os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
    fd=os.open(inbox,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
    need(digest(archive)==data['sourceSha256'])
    prepared={'status':'PREPARED','release':data['tag'],'sourceSha256':data['sourceSha256'],'mode':data['mode']}
    if data.get('generatedRequest') is not None:
        need(data['generated'] and data['mode']=='Maintenance')
        request_path=inbox/'generated-cleanup-request.json'
        request_info=chain(request_path,maximum=1048576)
        need(stat.S_IMODE(request_info.st_mode)==0o600 and request_info.st_size==data['generatedRequest']['bytes'])
        need(digest(request_path)==data['generatedRequest']['sha256'])
        request=json.loads(request_path.read_bytes())
        need(request['currentRelease']==data['tag'] and request['identity']==identity)
        prepared['request']=data['generatedRequest']
    print(json.dumps(prepared))
else:
    need(mode=='inspect');files={}
    for label,name in [('plan',data['evidencePrefix']+'-plan.json'),('receipt',data['evidencePrefix']+'-receipt.json'),('journal',data['evidencePrefix']+'-journal.jsonl')]:
        path=inbox/name
        if path.exists() or path.is_symlink():
            info=chain(path);files[label]={'bytes':info.st_size,'sha256':digest(path)}
    print(json.dumps({'status':'INSPECTED','release':data['tag'],'files':files}))
'@
$encodedProgram = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteProgram))
$launcher = 'import base64;exec(compile(base64.b64decode("' + $encodedProgram + '"),"fixed-build-cleanup-controller","exec"))'
function Get-ReclaimCommand {
    $encodedContext = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($context | ConvertTo-Json -Depth 16 -Compress)))
    return "python3 -I -B -c '$launcher' '$encodedContext'"
}
$baseCommand = Get-ReclaimCommand
$remoteInbox = "$RemoteRoot/inbox/$Tag"
$helper = "$remoteInbox/cleanup-ecs-builds.py"
$remoteArchiveName = if ($Mode -ceq 'Maintenance') { 'cleanup-source.tar.gz' } else { 'source.tar.gz' }
$arguments = "--root '$RemoteRoot' --current-tag '$Tag' --commit '$Commit' --source-archive '$remoteInbox/$remoteArchiveName' --source-sha256 '$SourceSha256' --instance-id '$instance' --machine-id '$machine'"
if ($GeneratedArtifacts) { $arguments += ' --generated' }
if ($Mode -ceq 'Terminal') { $arguments += " --evidence-archived --terminal-result '$($env:CI_TERMINAL_RESULT)'" }

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
for k in ('planSha256','originalEvidencePreserved','sharedMavenCachePreserved','publishedArtifactsPreserved','oldMavenRepositoriesPreserved','businessDataDeleted','generatedLifecycle','unselectedMavenRepositoriesPreserved','retention'):
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
$bootstrap = $null
try {
    if ($Mode -ceq 'Maintenance') {
        # This is the first remote write path. Its program validates Linux actor,
        # IMDS, machine ID and private root chains before creating fresh names.
        $bootstrap = (Invoke-Reclaim $ssh ($SshOptions + @('-p', $PortText, $Destination, "$baseCommand bootstrap")) | Select-Object -Last 1) | ConvertFrom-Json
        $unit=$bootstrap.allocationUnitBytes
        Require-Reclaim ($unit -is [long] -and $unit -ge 4096 -and $unit -le 1048576 -and ($unit -band ($unit-1)) -eq 0) 'Maintenance filesystem allocation unit is invalid.'
        $expectedGrowth=1048576L + [long]([Math]::Ceiling($sourceBytes/[double]$unit)*$unit)
        foreach ($binding in $helpers.Values) { $expectedGrowth += [long]([Math]::Ceiling($binding.bytes/[double]$unit)*$unit) }
        if ($context.ContainsKey('generatedRequest')) { $expectedGrowth += [long]([Math]::Ceiling($context.generatedRequest.bytes/[double]$unit)*$unit) }
        Require-Reclaim ($bootstrap.status -ceq 'UPLOAD_REQUIRED' -and $bootstrap.release -ceq $Tag -and $bootstrap.commit -ceq $Commit -and $bootstrap.sourceSha256 -ceq $SourceSha256 -and $bootstrap.sourceBytes -eq $sourceBytes -and $bootstrap.identity.instanceId -ceq $instance -and $bootstrap.identity.machineId -ceq $machine -and $bootstrap.identity.executionLocation -ceq 'ECS' -and $bootstrap.file -ceq "$remoteInbox/cleanup-source.tar.gz" -and $bootstrap.reserveBytes -eq 2147483648 -and $bootstrap.requiredBytes -eq (2147483648L + $expectedGrowth) -and $bootstrap.controlGrowthBytes -eq ($expectedGrowth-$sourceBytes) -and $bootstrap.availableBytes -ge $bootstrap.requiredBytes -and $bootstrap.uploadIdentity.device -is [long] -and $bootstrap.uploadIdentity.inode -is [long] -and $bootstrap.uploadIdentity.device -ge 0 -and $bootstrap.uploadIdentity.inode -gt 0 -and @($bootstrap.uploadIdentity.PSObject.Properties).Count -eq 2) 'Maintenance source upload lacks its exact fresh directory, ECS identity or bounded reserve.'
        if ($context.ContainsKey('generatedRequest')) {
            Assert-ReclaimPath $requestLocal
            Require-Reclaim ((Get-FileHash -LiteralPath $requestLocal -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $context.generatedRequest.sha256) 'Generated request changed before upload.'
            $null = Invoke-Reclaim $scp ($SshOptions + @('-P', $PortText, $requestLocal, "${Destination}:$remoteInbox/generated-cleanup-request.json"))
        }
        $context.uploadIdentity = @{ device = $bootstrap.uploadIdentity.device; inode = $bootstrap.uploadIdentity.inode }
        $baseCommand = Get-ReclaimCommand
        Assert-ReclaimPath $archive
        Require-Reclaim ((Get-Item -LiteralPath $archive).Length -eq $sourceBytes -and (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256) 'The fixed source archive changed before maintenance upload.'
        $null = Invoke-Reclaim $scp ($SshOptions + @('-P', $PortText, $archive, "${Destination}:$remoteInbox/cleanup-source.tar.gz"))
        Assert-ReclaimPath $archive
        Require-Reclaim ((Get-Item -LiteralPath $archive).Length -eq $sourceBytes -and (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256) 'The fixed source archive changed during maintenance upload.'
    }
    $ready = (Invoke-Reclaim $ssh ($SshOptions + @('-p', $PortText, $Destination, "$baseCommand prepare")) | Select-Object -Last 1) | ConvertFrom-Json
    Require-Reclaim ($ready.status -ceq 'PREPARED' -and $ready.release -ceq $Tag -and $ready.sourceSha256 -ceq $SourceSha256 -and $ready.mode -ceq $Mode) 'Current fixed cleanup helpers were not admitted.'
    $admitted = $true
    $planArguments = $arguments
    if ($GeneratedArtifacts -and $Mode -ceq 'Maintenance') {
        Require-Reclaim ($ready.request.bytes -gt 0 -and $ready.request.bytes -le 1MB -and $ready.request.sha256 -cmatch '^[a-f0-9]{64}$') 'Generated maintenance request lacks its exact fixed transfer proof.'
        Copy-ReclaimEvidence 'generated-cleanup-request.json' (Join-Path $artifacts 'generated-cleanup-request.json') $ready.request
        $planArguments += " --request '$remoteInbox/generated-cleanup-request.json' --request-sha256 '$($ready.request.sha256)'"
    }
    $null = Invoke-Reclaim $ssh ($SshOptions + @('-p', $PortText, $Destination, "exec python3 -I -B '$helper' plan $planArguments --output '$remoteInbox/$evidencePrefix-plan.json'"))
    $inspection = (Invoke-Reclaim $ssh ($SshOptions + @('-p', $PortText, $Destination, "$baseCommand inspect")) | Select-Object -Last 1) | ConvertFrom-Json -AsHashtable
    Require-Reclaim ($inspection.files.ContainsKey('plan')) 'Read-only cleanup produced no plan.'
    Copy-ReclaimEvidence "$evidencePrefix-plan.json" $localPlan $inspection.files.plan
    $planProof = (Invoke-Reclaim $python @('-I', '-B', '-c', $evidenceReader, $localPlan) | Select-Object -Last 1) | ConvertFrom-Json
    Require-Reclaim ($planProof.kind -ceq 'doorhandle-old-build-cleanup-plan' -and $planProof.currentRelease -ceq $Tag -and $planProof.identity.instanceId -ceq $instance -and $planProof.identity.machineId -ceq $machine -and $planProof.identity.executionLocation -ceq 'ECS') 'Collected cleanup plan belongs to another build or ECS.'
    $applyAttempted = $true
    $null = Invoke-Reclaim $ssh ($SshOptions + @('-p', $PortText, $Destination, "exec python3 -I -B '$helper' apply $arguments --plan '$remoteInbox/$evidencePrefix-plan.json' --plan-sha256 '$($planProof.rawSha256)' --output '$remoteInbox/$evidencePrefix-receipt.json'"))
    $completed = $true
} catch {
    $failure = $_
} finally {
    if ($admitted) {
        try {
            $inspection = (Invoke-Reclaim $ssh ($SshOptions + @('-p', $PortText, $Destination, "$baseCommand inspect")) | Select-Object -Last 1) | ConvertFrom-Json -AsHashtable
            if ($GeneratedArtifacts -and $inspection.files.ContainsKey('journal')) { Copy-ReclaimEvidence "$evidencePrefix-journal.jsonl" (Join-Path $artifacts "$evidencePrefix-journal.jsonl") $inspection.files.journal }
            if ($inspection.files.ContainsKey('plan')) { Copy-ReclaimEvidence "$evidencePrefix-plan.json" $localPlan $inspection.files.plan }
            if ($inspection.files.ContainsKey('receipt')) {
                Copy-ReclaimEvidence "$evidencePrefix-receipt.json" $localReceipt $inspection.files.receipt
                $receiptProof = (Invoke-Reclaim $python @('-I', '-B', '-c', $evidenceReader, $localReceipt) | Select-Object -Last 1) | ConvertFrom-Json
                $mavenPreserved = if ($GeneratedArtifacts) { $receiptProof.generatedLifecycle -eq $true -and $receiptProof.unselectedMavenRepositoriesPreserved -eq $true } else { $receiptProof.oldMavenRepositoriesPreserved -eq $true }
                Require-Reclaim ($null -ne $planProof -and $receiptProof.kind -ceq 'doorhandle-old-build-cleanup-receipt' -and $receiptProof.currentRelease -ceq $Tag -and $receiptProof.identity.instanceId -ceq $instance -and $receiptProof.identity.machineId -ceq $machine -and $receiptProof.identity.executionLocation -ceq 'ECS' -and $receiptProof.planSha256 -ceq $planProof.canonicalSha256 -and $receiptProof.status -cin @('REMOVED', 'NO_ACTION', 'PARTIAL_FAILURE') -and $receiptProof.originalEvidencePreserved -eq $true -and $receiptProof.sharedMavenCachePreserved -eq $true -and $receiptProof.publishedArtifactsPreserved -eq $true -and $mavenPreserved -and $receiptProof.businessDataDeleted -eq $false) 'Collected cleanup receipt lacks its exact build, plan or preservation boundary.'
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
    if ($Mode -ceq 'Maintenance') {
        $result.mode = 'Maintenance'; $result.testsExecuted = $false; $result.applicationBuilt = $false
        $result.sourceBytes = $sourceBytes; $result.admission = $bootstrap
    }
    if ($GeneratedArtifacts) {
        $result.generatedLifecycle = $true
        $result.retention = if ($receiptProof) { $receiptProof.retention } else { @{status='UNKNOWN';budgetVerdict='UNKNOWN'} }
        if ($result.retention.status -cne 'SATISFIED') { $result.status='RETAINED_OUTPUTS_REQUIRE_ACTION' }
    }
    $stream = [IO.File]::Open($localResult, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($result | ConvertTo-Json -Depth 6)); $stream.Write($bytes, 0, $bytes.Length) }
    finally { $stream.Dispose() }
}
if ($null -ne $failure -or $result.status -cin @('FAILED_OR_UNKNOWN','RETAINED_OUTPUTS_REQUIRE_ACTION')) {
    throw 'Old build output cleanup did not complete with verified original evidence; collected files are retained.'
}
Write-Host ('Old build output cleanup: ' + $result.status + '. Business data, original reports, source archives, published artifacts and shared Maven dependencies are retained.')
