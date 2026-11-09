param(
    [ValidateSet('Verified','Maintenance')][string]$Mode = 'Verified',
    [Parameter(Mandatory=$true)][string[]]$SshOptions,
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][string]$PortText,
    [Parameter(Mandatory=$true)][string]$RemoteRoot,
    [Parameter(Mandatory=$true)][string]$Tag,
    [Parameter(Mandatory=$true)][string]$Commit,
    [Parameter(Mandatory=$true)][string]$SourceSha256,
    [string]$RetainedControlRoot = 'D:/AI/lunwen1/DoorHandleCatch/work/jenkins/data-residency-20261107'
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
function Require-NativeJar([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }
function Assert-NativeJarPath([string]$Path) {
    $item=Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        Require-NativeJar (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Native JAR controls cannot contain links or junctions.'
        $item=if ($item -is [IO.FileInfo]) {$item.Directory} else {$item.Parent}
    }
}
function Invoke-NativeJar([string]$Executable,[string[]]$Arguments) {
    $lines=@(& $Executable @Arguments)
    if ($LASTEXITCODE -ne 0) { throw 'Native JAR retirement admission failed; original artifacts are retained.' }
    return $lines
}
Require-NativeJar ($Mode -ceq 'Maintenance' -or ($env:CI_ECS_VERIFIED -ceq 'true' -and $env:DOORHANDLE_CI_SCOPE -ceq 'source')) 'Verified retirement follows this build actual source PASS only.'
Require-NativeJar ($Mode -cne 'Maintenance' -or ($env:ACTION -ceq 'reclaim-build-outputs' -and $env:CI_ECS_VERIFIED -ceq 'false' -and $env:DOORHANDLE_CI_SCOPE -ceq 'source')) 'Maintenance must be the explicit source-only Jenkins action.'
Require-NativeJar ($Destination -cmatch '^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}$' -and $PortText -match '^[0-9]{1,5}$' -and [int]$PortText -ge 1 -and [int]$PortText -le 65535) 'Invalid fixed SSH endpoint.'
Require-NativeJar ($RemoteRoot -cmatch '^/(home|srv|opt)/[A-Za-z0-9_./-]+$' -and $RemoteRoot -notmatch '(^|/)\.\.(/|$)|//' -and -not $RemoteRoot.EndsWith('/')) 'Invalid explicit ECS CI root.'
Require-NativeJar ($Tag -cmatch '^ci-[1-9][0-9]*-[a-f0-9]{12}$' -and $Commit -cmatch '^[a-f0-9]{40}$' -and $Tag.EndsWith('-'+$Commit.Substring(0,12)) -and $SourceSha256 -cmatch '^[a-f0-9]{64}$') 'Invalid fixed source context.'
Require-NativeJar ($SshOptions -ccontains 'StrictHostKeyChecking=yes' -and $SshOptions -ccontains 'HostKeyAlias=doorhandle-bj') 'Pinned ECS host authentication is required.'
$instance=$env:DOORHANDLE_ECS_INSTANCE_ID; $machine=$env:DOORHANDLE_ECS_MACHINE_ID
Require-NativeJar ($instance -cmatch '^i-[a-z0-9]+$' -and $machine -cmatch '^[a-f0-9]{32}$') 'Explicit expected ECS identity required.'
$ssh=(Get-Command ssh.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$scp=(Get-Command scp.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$python=$env:LOCAL_PYTHON_EXE; if ([string]::IsNullOrWhiteSpace($python)) {$python=$env:PYTHON_EXE}
Require-NativeJar ($python -and [IO.Path]::IsPathFullyQualified($python) -and (Test-Path -LiteralPath $python -PathType Leaf)) 'Existing local packaging Python is required.'
$workspace=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$archive=Join-Path $workspace 'artifacts/source.tar.gz'; Assert-NativeJarPath $archive
Require-NativeJar ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256) 'Current immutable source archive differs.'
$currentReceipt=if ($Mode -ceq 'Verified') {Join-Path $workspace 'artifacts/ecs/evidence/verification-receipt.json'} else {Join-Path $workspace 'artifacts/release.json'}
Assert-NativeJarPath $currentReceipt
$currentReceiptSha=(Get-FileHash -LiteralPath $currentReceipt -Algorithm SHA256).Hash.ToLowerInvariant()
$jenkinsHome=$env:JENKINS_HOME
if ([string]::IsNullOrWhiteSpace($jenkinsHome)) {$jenkinsHome=Join-Path ([Environment]::GetFolderPath('UserProfile')) '.jenkins'}
Require-NativeJar ([IO.Path]::IsPathFullyQualified($RetainedControlRoot) -and [IO.Path]::IsPathFullyQualified($jenkinsHome)) 'Existing absolute C/D custody locations are required.'

# Stdlib byte/metadata inspection only. No project module, DB, application or
# test is imported or run on the workstation. D evidence is pinned to original
# preservation manifests reviewed for these thirteen exact historical attempts.
$reader=@'
import gzip,hashlib,json,os,stat,sys,tarfile
from pathlib import Path
def need(v,code='LOCAL_CONTROL_ADMISSION_REJECTED'):
 if not v:raise ValueError(code)
def stable(path,maximum=2097152):
 path=Path(path);need(path.resolve(strict=True)==path)
 for p in (path,*path.parents):need(not p.is_symlink())
 with path.open('rb') as f:
  a=os.fstat(f.fileno());need(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and 0<a.st_size<=maximum)
  raw=f.read(maximum+1);b=os.fstat(f.fileno());c=path.stat()
 sig=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
 need(sig(a)==sig(b)==sig(c) and len(raw)==a.st_size);return raw
def sha(raw):return hashlib.sha256(raw).hexdigest()
def unique(pairs):
 result={}
 for k,v in pairs:need(k not in result);result[k]=v
 return result
archive,commit,retained,jhome,remote,current=sys.argv[1:]
approved=[(117,'8c898996cc28ce30fd6531710511f833cccb4864','e1eec611a0dcbb93158d8e5a68fc5d16e6f96d65dcb82e6930f54abdd84d2e2c'),
 (118,'6481f7fa6021eb36592a081d04f385886c03412a','e73474da34762eedf1438c835dbc741091f02c69fb5c3664dbba6cca30395f8a'),
 (130,'9a588271dadb135ec4284392ef7b9c9c55ea511d','f53a73fa4ce45e44b666cbf963145b353f6e478c7cc594ca849b59bfe0b924d2'),
 (132,'69f2ef0fb3091cc204b75194aa6da96c696136f0','a52af50762c2b5629aa6ab3f2f453ab50252d1ac965471b4e0ee3fed46b1c3e5'),
 (134,'df30e17036de96863957b13e57f12b129bbfa951','78039d10d7e9415a5c9c798ad67e01ca5760e525814d0874c64703fe7fb9f62b'),
 (137,'facc2ed94047d7cc01da8072195e6d769c6f1385','ae89a08f1c3d046a3a02bdfff4583b97b34d7ad64497f7b0cf4d08cfadf0ae69'),
 (139,'384439388a8c6de52ca90be62722c382ff8973bb','8981260defa80777c4c09d8c1dd9a4230fe5dcc4ac50578544da3b1fa7ec0404'),
 (141,'56da3c4f780055e4f1f1ae835888189e85807bec','c00b42067d0b6786e1daaad88c57570ecab0a14901c31cbc0ddea44e30bba9bc'),
 (143,'f4b5c8d9e39bfe621c97fb1d9e82aea667bab08f','032b3ae99967219534fe34131be8f8af7c6acd133ec61238d0cf005c3a9b8afa'),
 (145,'dd85b09748a996f68e909fa54bc9412110e78134','372c5f0713c02051be0f5c9bcd2179e805a39e1c0aea4d96a3e1aee88fe9dac4'),
 (154,'38293aa306b368964bbc2a7f66bb6a6b5c414016','ba9dccb622fd030ae877b861ac53b1006b6021ecfcd7f247f4d51d30b72cd76e'),
 (156,'9e1927880595e78c778288e45423bdd27bd818a8','f1acdd4775932c06ca2bcb0aa548b6074083ca80d45f83d5d300ef924158640c'),
 (160,'9d011d9d5ed8ef1b6e5526c0964ee5f405ed421b','4b9e9eea10bfe6badb2d3a4cbaeb10e99ed1aa7ff6e54b1f59ed6c43f2dd6ff3')]
helpers={};wanted={'script/jenkins/retire-failed-native-jar-duplicates.py','script/jenkins/cleanup-ecs-builds.py','script/jenkins/verify-remote.py','script/docker/compact-build-resources.py'}
class Bounded:
 def __init__(self,s):self.s,self.n=s,0
 def read(self,size=-1):
  rem=536870912-self.n;raw=self.s.read(rem+1 if size<0 else min(size,rem+1));self.n+=len(raw);need(self.n<=536870912);return raw
with gzip.open(archive,'rb') as gz,tarfile.open(fileobj=Bounded(gz),mode='r|') as arc:
 count=0
 for member in arc:
  count+=1;need(count<=50000 and 0<=member.size<=33554432)
  if member.name not in wanted:continue
  need(member.name not in helpers and member.isfile() and 0<member.size<=1048576)
  raw=arc.extractfile(member).read(1048577);need(len(raw)==member.size);helpers[member.name]={'bytes':len(raw),'sha256':sha(raw)}
 need(set(helpers)==wanted and arc.pax_headers.get('comment')==commit)
rows=[];skipped=[];custody=[]
for number,oldcommit,preservation_sha in approved:
 tag='ci-'+str(number)+'-'+oldcommit[:12];folder=Path(retained)/('ci-'+str(number)+'-raw-receipts');preservation=None
 try:
  files={};origins={}
  for role,name in [('buildXml','build.xml'),('release','release.json'),('localBuild','local-build.json'),('fixtureCleanupPublic','fixture-cleanup.json')]:
   source=Path(jhome)/'jobs/doorhandle-java/builds'/str(number)/('build.xml' if role=='buildXml' else 'archive/artifacts/'+name)
   if source.is_file():
    raw=stable(source);origin='ACTUAL_JENKINS_ORIGINAL'
   elif (folder/name).is_file():
    if preservation is None:
     proof=stable(folder/'preservation.json');need(sha(proof)==preservation_sha,'PRESERVED_CUSTODY_SHA_DRIFT');preservation=json.loads(proof,object_pairs_hook=unique)
     need(preservation.get('build')==number and type(preservation.get('files')) is list)
    matches=[r for r in preservation['files'] if r.get('path')==name];need(len(matches)==1)
    source=folder/name;raw=stable(source);row=matches[0]
    suffix='/jobs/doorhandle-java/builds/'+str(number)+('/build.xml' if role=='buildXml' else '/archive/artifacts/'+name)
    need(row.get('bytes')==len(raw) and row.get('sha256')==sha(raw) and str(row.get('original','')).replace(chr(92),'/').endswith(suffix),'PRESERVED_ORIGINAL_CONTROL_DRIFT')
    origin='PINNED_PRESERVED_JENKINS_ORIGINAL'
   else:
    need(role not in ('buildXml','release'),'MISSING_LOCAL_CONTROL_'+role.upper());continue
   files[role]={'source':str(source),'file':name,'bytes':len(raw),'sha256':sha(raw)};origins[role]={'origin':origin,'bytes':len(raw),'sha256':sha(raw)}
  rel=json.loads(stable(files['release']['source']),object_pairs_hook=unique)
  need(rel.get('release')==tag and rel.get('commit')==oldcommit and type(rel.get('sourceSha256')) is str and len(rel['sourceSha256'])==64)
  rows.append({'release':tag,'commit':oldcommit,'sourceSha256':rel['sourceSha256'],'files':files})
  custody.append({'release':tag,'controls':origins,'preservationSha256':preservation_sha if preservation else None})
 except Exception as error:skipped.append({'release':tag,'reason':str(error) if type(error) is ValueError and str(error).replace('_','').isalnum() else type(error).__name__})
print(json.dumps({'helpers':helpers,'rows':rows,'skipped':skipped,'custody':custody}))
'@
$local=(Invoke-NativeJar $python @('-I','-B','-c',$reader,$archive,$Commit,$RetainedControlRoot,$jenkinsHome,$RemoteRoot,$Tag) | Select-Object -Last 1) | ConvertFrom-Json -AsHashtable
$spec=[ordered]@{schemaVersion=1;kind='doorhandle-failed-native-jar-duplicate-request';current=@{release=$Tag;commit=$Commit;sourceSha256=$SourceSha256};identity=@{instanceId=$instance;machineId=$machine;executionLocation='ECS'};protectedReleases=@($Tag);candidates=@()}
$uploads=@()
foreach ($row in $local.rows) {
    $controls=@{}
    foreach ($entry in $row.files.GetEnumerator()) {
        $binding=$entry.Value
        $relative="inbox/$Tag/native-jar-duplicate-controls/$($row.release)/$($binding.file)"
        $controls[$entry.Key]=@{path=$relative;bytes=$binding.bytes;sha256=$binding.sha256}
        $uploads+=@{relative=$relative;source=$binding.source;bytes=$binding.bytes;sha256=$binding.sha256}
    }
    $spec.candidates+=@{release=$row.release;commit=$row.commit;sourceSha256=$row.sourceSha256;controls=$controls}
}
$work=Join-Path $workspace 'work'; New-Item -ItemType Directory -Path $work -Force | Out-Null
$specFile=Join-Path $work ('native-jar-duplicate-local-spec-'+$Tag+'.json')
Require-NativeJar (-not (Test-Path -LiteralPath $specFile)) 'Use a fresh build; local retirement request already exists.'
$spec | ConvertTo-Json -Depth 12 -Compress | Set-Content -LiteralPath $specFile -Encoding utf8
$uploads+=@{relative="inbox/$Tag/native-jar-duplicate-local-spec.json";source=$specFile;bytes=(Get-Item -LiteralPath $specFile).Length;sha256=(Get-FileHash -LiteralPath $specFile -Algorithm SHA256).Hash.ToLowerInvariant()}
$specSha=$uploads[-1].sha256
if ($Mode -ceq 'Maintenance') {
    $uploads+=@{relative="inbox/$Tag/native-jar-duplicate-maintenance-package.json";source=$currentReceipt;bytes=(Get-Item -LiteralPath $currentReceipt).Length;sha256=$currentReceiptSha}
}
# Local source paths are used only by the SCP loop; the remote byte verifier
# receives its exact relative path/length/SHA contract without unused D paths.
$remoteUploads=@($uploads | ForEach-Object { @{relative=$_.relative;bytes=$_.bytes;sha256=$_.sha256} })
$context=@{root=$RemoteRoot;tag=$Tag;commit=$Commit;sourceSha256=$SourceSha256;mode=$Mode;instanceId=$instance;machineId=$machine;helpers=$local.helpers;uploads=$remoteUploads}
$bootstrap=@'
import base64,gzip,hashlib,json,os,stat,sys,tarfile
from pathlib import Path
from urllib.request import ProxyHandler,Request,build_opener
def need(v):
 if not v:raise ValueError('Native JAR fixed-source bootstrap refused')
data=json.loads(base64.b64decode(sys.argv[1]));root=Path(data['root']);inbox=root/'inbox'/data['tag']
need(sys.platform=='linux' and os.getuid()==os.geteuid()==1000 and Path('/etc/machine-id').read_text().strip()==data['machineId'])
opener=build_opener(ProxyHandler({}));base='http://100.100.100.200/latest/'
with opener.open(Request(base+'api/token',data=b'',method='PUT',headers={'X-aliyun-ecs-metadata-token-ttl-seconds':'60'}),timeout=4) as r:token=r.read(4096).decode()
with opener.open(Request(base+'meta-data/instance-id',headers={'X-aliyun-ecs-metadata-token':token}),timeout=4) as r:need(r.read(256).decode().strip()==data['instanceId'])
def owned(p,directory=False):
 need(p.is_absolute() and '..' not in p.parts and p.resolve(strict=True)==p and (p==root or p.is_relative_to(root)))
 for parent in (p,*p.parents):need(not parent.is_symlink())
 s=p.stat();need(s.st_uid==1000 and not s.st_mode&0o022 and (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode) and s.st_nlink==1));return s
owned(root,True);owned(inbox,True)
archive=inbox/('source.tar.gz' if data['mode']=='Verified' else 'cleanup-source.tar.gz');info=owned(archive)
need(0<info.st_size<=134217728)
with archive.open('rb') as f:need(hashlib.file_digest(f,'sha256').hexdigest()==data['sourceSha256'])
class Bounded:
 def __init__(self,s):self.s,self.n=s,0
 def read(self,size=-1):
  rem=536870912-self.n;raw=self.s.read(rem+1 if size<0 else min(size,rem+1));self.n+=len(raw);need(self.n<=536870912);return raw
found={};count=0
with gzip.open(archive,'rb') as gz,tarfile.open(fileobj=Bounded(gz),mode='r|') as arc:
 for entry in arc:
  count+=1;need(count<=50000 and 0<=entry.size<=33554432)
  if entry.name not in data['helpers']:continue
  need(entry.name not in found and entry.isfile() and 0<entry.size<=1048576)
  raw=arc.extractfile(entry).read(1048577);want=data['helpers'][entry.name]
  need(len(raw)==entry.size==want['bytes'] and hashlib.sha256(raw).hexdigest()==want['sha256']);found[entry.name]=raw
 need(arc.pax_headers.get('comment')==data['commit'] and set(found)==set(data['helpers']))
need(os.statvfs(root).f_bavail*os.statvfs(root).f_frsize>=2147483648+sum(r['bytes'] for r in data['uploads'])+8388608)
for name,raw in found.items():
 target=inbox/Path(name).name
 if target.exists() or target.is_symlink():
  owned(target)
  with target.open('rb') as f:need(f.read(1048577)==raw)
 else:
  with os.fdopen(os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
if len(sys.argv)>2 and sys.argv[2]=='finish':
 for row in data['uploads']:
  p=root/row['relative'];owned(p);expected=data['uploadIdentities'][row['relative']]
  with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
   a=os.fstat(f.fileno());need([a.st_dev,a.st_ino]==expected and a.st_size==row['bytes'] and hashlib.file_digest(f,'sha256').hexdigest()==row['sha256'])
   need([p.lstat().st_dev,p.lstat().st_ino]==expected);os.fchmod(f.fileno(),0o600);os.fsync(f.fileno())
 print(json.dumps({'status':'FINALIZED','release':data['tag']}));raise SystemExit(0)
identities={}
for row in data['uploads']:
 p=root/row['relative'];need(p.is_relative_to(inbox) and '..' not in p.parts and not p.exists() and not p.is_symlink())
 parents=[];parent=p.parent
 while not parent.exists():parents.append(parent);parent=parent.parent
 owned(parent,True)
 for parent in reversed(parents):parent.mkdir(mode=0o700);owned(parent,True)
 with os.fdopen(os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as f:
  f.flush();os.fsync(f.fileno());s=os.fstat(f.fileno());identities[row['relative']]=[s.st_dev,s.st_ino]
print(json.dumps({'status':'PREPARED','release':data['tag'],'commit':data['commit'],'sourceSha256':data['sourceSha256'],'uploadIdentities':identities,'identity':{'instanceId':data['instanceId'],'machineId':data['machineId'],'executionLocation':'ECS'}}))
'@
$encodedProgram=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($bootstrap))
$encodedContext=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($context | ConvertTo-Json -Depth 12 -Compress)))
$launcher='import base64;exec(compile(base64.b64decode("'+$encodedProgram+'"),"fixed-native-jar-bootstrap","exec"))'
$prepared=(Invoke-NativeJar $ssh ($SshOptions+@('-p',$PortText,$Destination,"python3 -I -B -c '$launcher' '$encodedContext'")) | Select-Object -Last 1) | ConvertFrom-Json
Require-NativeJar ($prepared.status -ceq 'PREPARED' -and $prepared.release -ceq $Tag -and $prepared.commit -ceq $Commit -and $prepared.sourceSha256 -ceq $SourceSha256 -and $prepared.identity.instanceId -ceq $instance -and $prepared.identity.machineId -ceq $machine) 'The fixed helper was not prepared on the admitted ECS.'
foreach ($upload in $uploads) {
    Assert-NativeJarPath $upload.source
    Require-NativeJar ((Get-Item -LiteralPath $upload.source).Length -eq $upload.bytes -and (Get-FileHash -LiteralPath $upload.source -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $upload.sha256) 'Original control drifted before upload.'
    $null=Invoke-NativeJar $scp ($SshOptions+@('-P',$PortText,$upload.source,"${Destination}:$RemoteRoot/$($upload.relative)"))
    Require-NativeJar ((Get-Item -LiteralPath $upload.source).Length -eq $upload.bytes -and (Get-FileHash -LiteralPath $upload.source -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $upload.sha256) 'Original control drifted during upload.'
}
$context.uploadIdentities=$prepared.uploadIdentities
$finalContext=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($context | ConvertTo-Json -Depth 12 -Compress)))
$finalized=(Invoke-NativeJar $ssh ($SshOptions+@('-p',$PortText,$Destination,"python3 -I -B -c '$launcher' '$finalContext' finish")) | Select-Object -Last 1) | ConvertFrom-Json
Require-NativeJar ($finalized.status -ceq 'FINALIZED' -and $finalized.release -ceq $Tag) 'The original uploaded control files changed or lost their private identity.'
$helper="$RemoteRoot/inbox/$Tag/retire-failed-native-jar-duplicates.py"
$helperSha=$local.helpers.'script/jenkins/retire-failed-native-jar-duplicates.py'.sha256
$common="--root '$RemoteRoot' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --mode '$Mode' --instance-id '$instance' --machine-id '$machine' --current-receipt-sha256 '$currentReceiptSha'"
function Invoke-NativeJarPhase([string]$Phase,[string]$Flags='') {
    $guard="test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$helperSha' && "
    return (Invoke-NativeJar $ssh ($SshOptions+@('-p',$PortText,$Destination,"${guard}python3 -I -B '$helper' --phase '$Phase' $common $Flags")) | Select-Object -Last 1) | ConvertFrom-Json
}
$captured=Invoke-NativeJarPhase 'capture-request' "--local-spec-sha256 '$specSha'"
Require-NativeJar ($captured.status -ceq 'CAPTURED' -and $captured.request.sha256 -cmatch '^[a-f0-9]{64}$') 'The actual ECS control snapshot was not captured.'
$requestSha=$captured.request.sha256
$builderPlanned=Invoke-NativeJarPhase 'plan-builders' "--request-sha256 '$requestSha'"
Require-NativeJar ($builderPlanned.status -ceq 'PLANNED' -and $builderPlanned.plan.sha256 -cmatch '^[a-f0-9]{64}$') 'No exact historical builder retirement plan was produced.'
function Copy-NativeJarEvidence($Observed) {
    foreach ($entry in @(@('capture','native-jar-duplicate-capture.json'),@('request','native-jar-duplicate-request.json'),@('plan','native-jar-duplicate-plan.json'),@('receipt','native-jar-duplicate-receipt.json'),@('journal','native-jar-duplicate-journal.jsonl'),@('builderPlan','native-builder-retirement-plan.json'),@('builderReceipt','native-builder-retirement-receipt.json'),@('builderJournal','native-builder-retirement-journal.jsonl'),@('publicLayerPlan','native-public-layer-duplicate-plan.json'),@('publicLayerReceipt','native-public-layer-duplicate-receipt.json'),@('publicLayerJournal','native-public-layer-duplicate-journal.jsonl'),@('generatedArchivePlan','native-generated-public-image-archive-plan.json'),@('generatedArchiveReceipt','native-generated-public-image-archive-receipt.json'),@('generatedArchiveJournal','native-generated-public-image-archive-journal.jsonl'),@('pythonCachePlan','native-python-build-cache-plan.json'),@('pythonCacheReceipt','native-python-build-cache-receipt.json'),@('pythonCacheJournal','native-python-build-cache-journal.jsonl'))) {
        $property=$Observed.files.PSObject.Properties[$entry[0]]
        if ($null -eq $property) {continue}
        $binding=$property.Value
        Require-NativeJar ($binding.file -ceq $entry[1] -and $binding.bytes -gt 0 -and $binding.bytes -le 2MB -and $binding.sha256 -cmatch '^[a-f0-9]{64}$') 'Native retirement evidence escaped its bounded allowlist.'
        $destinationFile=Join-Path $workspace ('artifacts/'+$entry[1]); Require-NativeJar (-not (Test-Path -LiteralPath $destinationFile)) 'Existing original evidence cannot be overwritten.'
        $null=Invoke-NativeJar $scp ($SshOptions+@('-P',$PortText,"${Destination}:$RemoteRoot/inbox/$Tag/$($entry[1])",$destinationFile))
        Assert-NativeJarPath $destinationFile
        Require-NativeJar ((Get-Item -LiteralPath $destinationFile).Length -eq $binding.bytes -and (Get-FileHash -LiteralPath $destinationFile -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $binding.sha256) 'Collected native retirement evidence changed.'
    }
    $originals=$Observed.PSObject.Properties['pythonCacheOriginals']
    if ($null -ne $originals) {
        $rows=@($originals.Value)
        Require-NativeJar ($rows.Count -le 64 -and @($rows | ForEach-Object {$_.file} | Select-Object -Unique).Count -eq $rows.Count) 'Python cache originals must be a bounded unique catalog.'
        foreach ($binding in $rows) {
            Require-NativeJar ($binding.file -cmatch '^native-python-build-cache-inspect/(container|image|owner)-[a-f0-9]{64}\.json$' -and $binding.bytes -gt 0 -and $binding.bytes -le 2MB -and $binding.sha256 -cmatch '^[a-f0-9]{64}$') 'Python cache original escaped its fixed bounded catalog.'
            $destinationFile=Join-Path $workspace ('artifacts/'+$binding.file)
            Require-NativeJar (-not (Test-Path -LiteralPath $destinationFile)) 'Existing Python cache original cannot be overwritten.'
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinationFile) | Out-Null
            $null=Invoke-NativeJar $scp ($SshOptions+@('-P',$PortText,"${Destination}:$RemoteRoot/inbox/$Tag/$($binding.file)",$destinationFile))
            Assert-NativeJarPath $destinationFile
            Require-NativeJar ((Get-Item -LiteralPath $destinationFile).Length -eq $binding.bytes -and (Get-FileHash -LiteralPath $destinationFile -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $binding.sha256) 'Collected Python cache original changed.'
        }
    }
}
$builderFailed=$false
try {$builderResult=Invoke-NativeJarPhase 'apply-builders' "--request-sha256 '$requestSha' --plan-sha256 '$($builderPlanned.plan.sha256)'"} catch {$builderFailed=$true}
if ($builderFailed) {
    Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')
    throw 'Historical builder retirement failed or is unknown; frozen evidence is retained and JAR deletion was not started.'
}
try {
    $planned=Invoke-NativeJarPhase 'plan' "--request-sha256 '$requestSha'"
    Require-NativeJar ($planned.status -ceq 'PLANNED' -and $planned.plan.sha256 -cmatch '^[a-f0-9]{64}$') 'No exact native JAR retirement plan was produced.'
} catch {
    Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')
    throw 'JAR planning failed after historical builder retirement; original builder receipts were collected.'
}
$applyFailed=$false
try {$result=Invoke-NativeJarPhase 'apply' "--request-sha256 '$requestSha' --plan-sha256 '$($planned.plan.sha256)'"} catch {$applyFailed=$true}
$publicLayerFailed=$false; $publicLayerPlanned=$null
if (-not $applyFailed) {
    try {
        $publicLayerPlanned=Invoke-NativeJarPhase 'plan-public-layers' "--request-sha256 '$requestSha'"
        Require-NativeJar ($publicLayerPlanned.status -ceq 'PLANNED' -and $publicLayerPlanned.plan.sha256 -cmatch '^[a-f0-9]{64}$') 'No exact public BuildKit layer plan was produced.'
        $publicLayerResult=Invoke-NativeJarPhase 'apply-public-layers' "--request-sha256 '$requestSha' --plan-sha256 '$($publicLayerPlanned.plan.sha256)'"
    } catch {$publicLayerFailed=$true}
}
$generatedArchiveFailed=$false; $generatedArchivePlanned=$null
if (-not $applyFailed -and -not $publicLayerFailed) {
    try {
        $generatedArchivePlanned=Invoke-NativeJarPhase 'plan-generated-image-archives' "--request-sha256 '$requestSha'"
        Require-NativeJar ($generatedArchivePlanned.status -ceq 'PLANNED' -and $generatedArchivePlanned.plan.sha256 -cmatch '^[a-f0-9]{64}$') 'No exact generated public image archive cache plan was produced.'
        $generatedArchiveResult=Invoke-NativeJarPhase 'apply-generated-image-archives' "--request-sha256 '$requestSha' --plan-sha256 '$($generatedArchivePlanned.plan.sha256)'"
    } catch {$generatedArchiveFailed=$true}
}
$pythonCacheRequested=$Mode -ceq 'Maintenance'; $pythonCacheFailed=$false; $pythonCachePlanned=$null
if ($pythonCacheRequested -and -not $applyFailed -and -not $publicLayerFailed -and -not $generatedArchiveFailed) {
    try {
        $pythonCachePlanned=Invoke-NativeJarPhase 'plan-python-build-cache'
        Require-NativeJar ($pythonCachePlanned.status -ceq 'PLANNED' -and $pythonCachePlanned.plan.sha256 -cmatch '^[a-f0-9]{64}$') 'No exact historical Python cache retirement plan was produced.'
        $pythonCacheResult=Invoke-NativeJarPhase 'apply-python-build-cache' "--plan-sha256 '$($pythonCachePlanned.plan.sha256)'"
    } catch {$pythonCacheFailed=$true}
}
$observed=Invoke-NativeJarPhase 'inspect'
Copy-NativeJarEvidence $observed
$builderReceiptFile=Join-Path $workspace 'artifacts/native-builder-retirement-receipt.json'
Require-NativeJar (Test-Path -LiteralPath $builderReceiptFile -PathType Leaf) 'Historical builder retirement lacks its original server receipt.'
$builderReceipt=Get-Content -LiteralPath $builderReceiptFile -Raw -Encoding utf8 | ConvertFrom-Json -Depth 24
Require-NativeJar ($builderReceipt.status -cin @('REMOVED','NO_ACTION') -and $builderReceipt.current.release -ceq $Tag -and $builderReceipt.current.commit -ceq $Commit -and $builderReceipt.current.sourceSha256 -ceq $SourceSha256 -and $builderReceipt.identity.instanceId -ceq $instance -and $builderReceipt.identity.machineId -ceq $machine -and $builderReceipt.requestSha256 -ceq $requestSha -and $builderReceipt.planSha256 -ceq $builderPlanned.plan.sha256 -and $builderReceipt.imagesPreserved -eq $true -and $builderReceipt.volumesPreserved -eq $true -and $builderReceipt.directoriesPreserved -eq $true -and $builderReceipt.mysqlDataDirectoriesPreserved -eq $true -and $builderReceipt.jarDeletionPerformed -eq $false) 'Historical builder retirement lacks matching source, host or preservation evidence.'
$receiptFile=Join-Path $workspace 'artifacts/native-jar-duplicate-receipt.json'
Require-NativeJar (Test-Path -LiteralPath $receiptFile -PathType Leaf) 'Native JAR retirement lacks an actual server receipt.'
$receipt=Get-Content -LiteralPath $receiptFile -Raw -Encoding utf8 | ConvertFrom-Json -Depth 20
Require-NativeJar (-not $applyFailed -and $receipt.status -cin @('REMOVED','NO_ACTION') -and $receipt.current.release -ceq $Tag -and $receipt.current.commit -ceq $Commit -and $receipt.current.sourceSha256 -ceq $SourceSha256 -and $receipt.identity.instanceId -ceq $instance -and $receipt.identity.machineId -ceq $machine -and $receipt.requestSha256 -ceq $requestSha -and $receipt.planSha256 -ceq $planned.plan.sha256 -and $receipt.inboxKeepersPreserved -is [bool] -and $receipt.inboxKeepersPreserved) 'Native JAR retirement failed or has an unknown outcome; review the retained originals.'
$publicLayerReceiptFile=Join-Path $workspace 'artifacts/native-public-layer-duplicate-receipt.json'
Require-NativeJar (-not $publicLayerFailed -and $null -ne $publicLayerPlanned -and (Test-Path -LiteralPath $publicLayerReceiptFile -PathType Leaf)) 'Public BuildKit layer retirement failed or is unknown; original controls were collected.'
$publicLayerReceipt=Get-Content -LiteralPath $publicLayerReceiptFile -Raw -Encoding utf8 | ConvertFrom-Json -Depth 24
Require-NativeJar ($publicLayerReceipt.status -cin @('REMOVED','NO_ACTION') -and $publicLayerReceipt.current.release -ceq $Tag -and $publicLayerReceipt.current.commit -ceq $Commit -and $publicLayerReceipt.current.sourceSha256 -ceq $SourceSha256 -and $publicLayerReceipt.identity.instanceId -ceq $instance -and $publicLayerReceipt.identity.machineId -ceq $machine -and $publicLayerReceipt.requestSha256 -ceq $requestSha -and $publicLayerReceipt.planSha256 -ceq $publicLayerPlanned.plan.sha256 -and $publicLayerReceipt.upstreamTarAndKeeper117Preserved -eq $true -and $publicLayerReceipt.directoriesImagesAndBusinessDataPreserved -eq $true -and $publicLayerReceipt.testsRunByRetirement -eq $false) 'Public layer retirement lacks exact source, host, plan or preservation evidence.'
$generatedArchiveReceiptFile=Join-Path $workspace 'artifacts/native-generated-public-image-archive-receipt.json'
Require-NativeJar (-not $generatedArchiveFailed -and $null -ne $generatedArchivePlanned -and (Test-Path -LiteralPath $generatedArchiveReceiptFile -PathType Leaf)) 'Generated public image cache retirement failed or is unknown; original controls were collected.'
$generatedArchiveReceipt=Get-Content -LiteralPath $generatedArchiveReceiptFile -Raw -Encoding utf8 | ConvertFrom-Json -Depth 24
Require-NativeJar ($generatedArchiveReceipt.status -cin @('REMOVED','NO_ACTION') -and $generatedArchiveReceipt.current.release -ceq $Tag -and $generatedArchiveReceipt.current.commit -ceq $Commit -and $generatedArchiveReceipt.current.sourceSha256 -ceq $SourceSha256 -and $generatedArchiveReceipt.identity.instanceId -ceq $instance -and $generatedArchiveReceipt.identity.machineId -ceq $machine -and $generatedArchiveReceipt.requestSha256 -ceq $requestSha -and $generatedArchiveReceipt.planSha256 -ceq $generatedArchivePlanned.plan.sha256 -and $generatedArchiveReceipt.publicInputsDirectoriesImagesAndBusinessDataPreserved -eq $true -and $generatedArchiveReceipt.sameBytesAsSeedClaimed -eq $false -and $generatedArchiveReceipt.testsRunByRetirement -eq $false) 'Generated cache retirement lacks exact source, host, plan or preserved public inputs.'
$pythonCacheReceipt=$null
if ($pythonCacheRequested) {
    $pythonCacheReceiptFile=Join-Path $workspace 'artifacts/native-python-build-cache-receipt.json'
    Require-NativeJar (-not $pythonCacheFailed -and $null -ne $pythonCachePlanned -and (Test-Path -LiteralPath $pythonCacheReceiptFile -PathType Leaf)) 'Historical Python cache retirement failed or is unknown; original controls were collected.'
    $pythonCacheReceipt=Get-Content -LiteralPath $pythonCacheReceiptFile -Raw -Encoding utf8 | ConvertFrom-Json -Depth 24
    Require-NativeJar ($pythonCacheReceipt.kind -ceq 'doorhandle-historical-python-build-cache-receipt' -and $pythonCacheReceipt.status -cin @('REMOVED','NO_ACTION') -and $pythonCacheReceipt.current.release -ceq $Tag -and $pythonCacheReceipt.current.commit -ceq $Commit -and $pythonCacheReceipt.current.sourceSha256 -ceq $SourceSha256 -and $pythonCacheReceipt.identity.instanceId -ceq $instance -and $pythonCacheReceipt.identity.machineId -ceq $machine -and $pythonCacheReceipt.planSha256 -ceq $pythonCachePlanned.plan.sha256 -and $pythonCacheReceipt.cachedInputsPreserved -is [bool] -and $pythonCacheReceipt.cachedInputsPreserved -and $pythonCacheReceipt.businessDataVolumesDirectoriesSourcesReportsPreserved -is [bool] -and $pythonCacheReceipt.businessDataVolumesDirectoriesSourcesReportsPreserved -and $pythonCacheReceipt.testsRunByRetirement -is [bool] -and -not $pythonCacheReceipt.testsRunByRetirement) 'Historical Python cache retirement lacks exact source, host, plan or protected-data evidence.'
}
$summary=[ordered]@{schemaVersion=1;kind='doorhandle-failed-native-jar-duplicate-ci';current=$spec.current;identity=$spec.identity;status=$receipt.status;requestSha256=$requestSha;planSha256=$planned.plan.sha256;deletedFiles=@($receipt.deleted).Count;candidateAllocatedBytes=$planned.candidateAllocatedBytes;localControlCustody=$local.custody;localSkipped=$local.skipped;captureSkipped=$captured.skipped;planSkipped=$planned.skipped;builderStatus=$builderReceipt.status;retiredBuilders=@($builderReceipt.removed).Count;retiredMysqlObjects=@($builderReceipt.retiredMysqlObjects).Count;mysqlDataDirectoriesPreserved=$true;builderSkipped=$builderReceipt.skipped;builderPlanSha256=$builderPlanned.plan.sha256;availableBytesBefore=$receipt.availableBytesBefore;availableBytesAfter=$receipt.availableBytesAfter;inboxKeepersPreserved=$true;imagesPreserved=$true;volumesPreserved=$true;testsRunByRetirement=$false}
$summary.publicLayerStatus=$publicLayerReceipt.status
$summary.publicLayerDeletedFiles=@($publicLayerReceipt.deleted).Count
$summary.publicLayerDeletedBytes=[long]0
$summary.publicLayerDeletedAllocatedBytes=[long]0
foreach ($deletedLayer in @($publicLayerReceipt.deleted)) {
    $summary.publicLayerDeletedBytes += [long]$deletedLayer.bytes
    $summary.publicLayerDeletedAllocatedBytes += [long]$deletedLayer.allocatedBytes
}
$summary.publicLayerCandidateAllocatedBytes=$publicLayerPlanned.candidateAllocatedBytes
$summary.publicLayerPlanSha256=$publicLayerPlanned.plan.sha256
$summary.publicLayerSkipped=$publicLayerReceipt.skipped
$summary.upstreamTarAndKeeper117Preserved=$true
$summary.generatedArchiveStatus=$generatedArchiveReceipt.status
$summary.generatedArchiveDeletedFiles=@($generatedArchiveReceipt.deleted).Count
$summary.generatedArchiveDeletedBytes=[long]0
$summary.generatedArchiveDeletedAllocatedBytes=[long]0
foreach ($deletedArchive in @($generatedArchiveReceipt.deleted)) {
    $summary.generatedArchiveDeletedBytes += [long]$deletedArchive.bytes
    $summary.generatedArchiveDeletedAllocatedBytes += [long]$deletedArchive.allocatedBytes
}
$summary.generatedArchivePlanSha256=$generatedArchivePlanned.plan.sha256
$summary.generatedArchiveSkipped=$generatedArchiveReceipt.skipped
$summary.availableBytesAfter=$generatedArchiveReceipt.availableBytesAfter
$summary.status=if ($receipt.status -ceq 'REMOVED' -or $publicLayerReceipt.status -ceq 'REMOVED' -or $generatedArchiveReceipt.status -ceq 'REMOVED') {'REMOVED'} else {'NO_ACTION'}
if ($null -ne $pythonCacheReceipt) {
    $summary.pythonCacheStatus=$pythonCacheReceipt.status
    $summary.pythonCacheRemovedContainers=@($pythonCacheReceipt.removedContainers).Count
    $summary.pythonCacheRemovedImages=@($pythonCacheReceipt.removedImages).Count
    $summary.pythonCacheCandidateContainerWritableBytes=$pythonCachePlanned.candidateContainerWritableBytes
    $summary.pythonCacheCandidateImageUniqueBytes=$pythonCachePlanned.candidateImageUniqueBytes
    $summary.pythonCachePlanSha256=$pythonCachePlanned.plan.sha256
    $summary.pythonCacheSkipped=$pythonCacheReceipt.skipped
    $summary.pythonCacheAvailableBytesBefore=$pythonCacheReceipt.availableBytesBefore
    $summary.availableBytesAfter=$pythonCacheReceipt.availableBytesAfter
    $summary.imagesPreserved=@($pythonCacheReceipt.removedImages).Count -eq 0
    $summary.cachedInputsPreserved=$true
    $summary.businessDataVolumesDirectoriesSourcesReportsPreserved=$true
    if ($pythonCacheReceipt.status -ceq 'REMOVED') {$summary.status='REMOVED'}
}
$summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $workspace 'artifacts/native-jar-duplicate-ci.json') -Encoding utf8
Write-Output ($summary | ConvertTo-Json -Depth 12 -Compress)
