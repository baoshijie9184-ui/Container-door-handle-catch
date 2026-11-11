param(
    [ValidateSet('Verified','Maintenance')][string]$Mode = 'Verified',
    [ValidateSet('Historical','Recent','RetiredCopies','ClosedRuntime','FailedNative')][string]$CanonicalBatch = 'Historical',
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
function Invoke-NativeJar([string]$Executable,[string[]]$Arguments,[string]$InputText) {
    $lines=@(if ($PSBoundParameters.ContainsKey('InputText')) {$InputText | & $Executable @Arguments} else {& $Executable @Arguments})
    if ($LASTEXITCODE -ne 0) { throw 'Native JAR retirement admission failed; original artifacts are retained.' }
    return $lines
}
Require-NativeJar ($Mode -ceq 'Maintenance' -or ($env:CI_ECS_VERIFIED -ceq 'true' -and $env:DOORHANDLE_CI_SCOPE -ceq 'source')) 'Verified retirement follows this build actual source PASS only.'
Require-NativeJar ($Mode -cne 'Maintenance' -or ($env:ACTION -ceq 'reclaim-build-outputs' -and $env:CI_ECS_VERIFIED -ceq 'false' -and $env:DOORHANDLE_CI_SCOPE -ceq 'source')) 'Maintenance must be the explicit source-only Jenkins action.'
Require-NativeJar ($CanonicalBatch -cne 'Recent' -or $Mode -ceq 'Maintenance') 'The recent batch only retires the three closed failed canonical binaries in explicit maintenance.'
Require-NativeJar ($CanonicalBatch -cne 'RetiredCopies' -or $Mode -ceq 'Maintenance') 'Retired candidate copies require the explicit source-only maintenance action.'
Require-NativeJar ($CanonicalBatch -cne 'ClosedRuntime' -or $Mode -ceq 'Maintenance') 'The exact 204/207 batch requires source-only maintenance.'
Require-NativeJar ($Destination -cmatch '^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}$' -and $PortText -match '^[0-9]{1,5}$' -and [int]$PortText -ge 1 -and [int]$PortText -le 65535) 'Invalid fixed SSH endpoint.'
Require-NativeJar ($RemoteRoot -cmatch '^/(home|srv|opt)/[A-Za-z0-9_./-]+$' -and $RemoteRoot -notmatch '(^|/)\.\.(/|$)|//' -and -not $RemoteRoot.EndsWith('/')) 'Invalid explicit ECS CI root.'
Require-NativeJar ($Tag -cmatch '^ci-[1-9][0-9]*-[a-f0-9]{12}$' -and $Commit -cmatch '^[a-f0-9]{40}$' -and $Tag.EndsWith('-'+$Commit.Substring(0,12)) -and $SourceSha256 -cmatch '^[a-f0-9]{64}$') 'Invalid fixed source context.'
Require-NativeJar ($SshOptions -ccontains 'StrictHostKeyChecking=yes' -and $SshOptions -ccontains 'HostKeyAlias=doorhandle-bj') 'Pinned ECS host authentication is required.'
Require-NativeJar ($CanonicalBatch -cne 'FailedNative' -or $Mode -ceq 'Maintenance') 'Failed native retention requires source-only maintenance.'
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
# preservation manifests reviewed for each selected closed batch.
$reader=@'
import gzip,hashlib,json,os,stat,sys,tarfile
import xml.etree.ElementTree as ET
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
archive,commit,retained,jhome,remote,current,batch=sys.argv[1:]
need(batch in ('Historical','Recent','RetiredCopies','ClosedRuntime','FailedNative'))
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
 (160,'9d011d9d5ed8ef1b6e5526c0964ee5f405ed421b','4b9e9eea10bfe6badb2d3a4cbaeb10e99ed1aa7ff6e54b1f59ed6c43f2dd6ff3'),
 (166,'a3c084e1cf568206baca89908542537ad825fef8','1cf175ceb8f1dee1e6164a112e400f3427d9bffd55d1632ef7398a58cbd44553'),
 (168,'a40c779d03a43b894ead5569b8eb26ee7dc22a2e','cc986ad9ae3483d8663e811b73e0e2d53d7bdc1e886c4904071b5f996aa993ce'),
 (173,'45465e873d92822abe446fd7be3f9f00b7816f70','135267928288ee0c86c3c550815bf17b251d74ff61111d55eab2e3aadfe4789c')]
if batch in ('Recent','RetiredCopies'):
 approved=[(195,'2c2e65a0daa94d96b327c59d720871ab70bff0a1','f923d108fd9c867f052f722fc0cef57231d2420928a881ca7780d16408dc5a8a'),
  (198,'7af0903ee84011dc51f4abac4f4a4d9679db7322','054a2b4bdfda1c97a006c2b78d0877e06260b4cef6e0df4177f58eef8ddf8ffe'),
  (201,'803baf401b5f9566283a59cb6a885a794b9d7d85','baaddc7acf7eb643f68e2e0c104decb35a90a394564dc94f601914e6710e731b')]
closed_originals={
 204:{'build.xml':(302416,'36e27ddb0d87daa0d94c3d72cc64e8f70fd4a28ecf7cadecd51054cfafaa5b09'),
      'release.json':(379,'5b0bdad3f157a07a7024f31302525f98ff07e477b1fa86aac5afa5fcbd80546d'),
      'local-build.json':(551,'6cc1cb1d0caa01d59948c6a2813644ff3d1172218fdc301e481d61d3f10623f8'),
      'fixture-cleanup.json':(356,'f5e900897ee241d09f1bd2bdff710332ec34b9d043723dffef2d4b292b2c66ab'),
      'ecs-tool-preparation.json':(4010,'e544cfa0ba169186acafa3568e787c0136748e8efd043eaa78bcbdd32c7a7f18'),
      'candidate-build-tools-transport.json':(2794,'5f247ecfcda3d838628b2ddf57cae7ae024dbb1bf0f6539787b5b5c4cde7ca28')},
 207:{'build.xml':(300291,'33d1b5f6388700d769e2900ac567568f15ed864e26b0721f9a70a0e985b7b958'),
      'release.json':(379,'9bda38c284695d2332a9c6d818722565d5b67a8f0baa55f855c072b5a88cfa08'),
      'local-build.json':(551,'08c2864766436a21c6108cc5f1e2ba1294c225edff3d285d467f53f86148970d'),
      'fixture-cleanup.json':(356,'94c913a4d310e5420facb24669bcfc166adba7c8ecc52be04621cf1c6904fa91'),
      'ecs-tool-preparation.json':(4010,'7e6d27ef907b8dd5c93ace7607a8c28487c1103efcdae2420e55d2e1601354cc'),
      'candidate-build-tools-transport.json':(2794,'136ae21a4b0498e4983d8b5cfa2920a45678d51fa70df3e5070a276aa688513a')}}
def closed_original(number,name):
 source=Path(jhome)/'jobs/doorhandle-java/builds'/str(number)/('build.xml' if name=='build.xml' else 'archive/artifacts/'+name)
 if source.is_file():raw=stable(source);origin='ACTUAL_JENKINS_ORIGINAL'
 else:
  folder=Path(retained)/('ci-204-collaboration-raw' if number==204 else 'ci-207-raw-receipts')
  filename='sha256-manifest.json' if number==204 else 'preservation.json'
  proof=stable(folder/filename);expected='f13a384b51cc8f2eaee8464c148fdcf915c89c8f32eaac0958c58a513683e088' if number==204 else '3c5c15b15c57544e7e7195059607d33b0c807989c2fb672d36d4c4db2eefe01a'
  need(sha(proof)==expected,'CLOSED_ORIGINAL_CUSTODY_DRIFT');record=json.loads(proof,object_pairs_hook=unique)
  need(record.get('build')==number and record.get('result')=='FAILURE' and type(record.get('files')) is list,'CLOSED_ORIGINAL_CUSTODY_CONTEXT_DIFFERS')
  source=folder/name;raw=stable(source)
  if name=='build.xml':need(record.get('buildXmlSha256')==sha(raw),'CLOSED_TERMINAL_CUSTODY_DRIFT')
  else:
   rows=[r for r in record['files'] if r.get('path')==name];need(len(rows)==1)
   row=rows[0];suffix='/jobs/doorhandle-java/builds/'+str(number)+'/archive/artifacts/'+name
   need(row.get('bytes')==len(raw) and row.get('sha256')==sha(raw) and str(row.get('original','')).replace(chr(92),'/').endswith(suffix),'CLOSED_ORIGINAL_MEMBER_DRIFT')
  origin='PINNED_PRESERVED_JENKINS_ORIGINAL'
 need((len(raw),sha(raw))==closed_originals[number][name],'CLOSED_RUNTIME_ORIGINAL_BYTES_DRIFT')
 return source,raw,origin
if batch=='ClosedRuntime':
 approved=[(204,'24f8eb4b02bf290c6dd4e186eb78c5f3c80f3b88',None),
  (207,'eb286c623177b9d1bc23fe88223d81862c00bc71','3c5c15b15c57544e7e7195059607d33b0c807989c2fb672d36d4c4db2eefe01a')]
if batch=='FailedNative':
 approved=[];current_number=int(current.split('-')[1]);builds=Path(jhome)/'jobs/doorhandle-java/builds'
 for directory in sorted((p for p in builds.iterdir() if p.name.isdigit() and 221<=int(p.name)<current_number),key=lambda p:int(p.name),reverse=True):
  raw=stable(directory/'build.xml');need(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper())
  node=ET.fromstring(raw)
  if node.findtext('result') not in ('FAILURE','ABORTED') or node.findtext('completed')!='true' or node.findtext('execution/done')!='true':continue
  params={}
  for item in node.findall('.//hudson.model.ParametersAction/parameters/*'):
   key=item.findtext('name');need(key and key not in params);params[key]=item.findtext('value')
  if any(params.get(k)!=v for k,v in {'ACTION':'verify-runtime','DOORHANDLE_CI_SCOPE':'mysql','PRODUCTION_RELEASE_ENABLED':'false'}.items()):continue
  source=directory/'archive/artifacts/release.json'
  if not source.is_file():continue
  release=json.loads(stable(source),object_pairs_hook=unique);oldcommit=params.get('TRUSTED_COMMIT')
  if not isinstance(oldcommit,str) or len(oldcommit)!=40 or release.get('commit')!=oldcommit or release.get('release')!='ci-'+directory.name+'-'+oldcommit[:12]:continue
  jar=directory/'archive/artifacts/application.jar'
  if not jar.is_file():continue
  with jar.open('rb') as stream:
   meta=os.fstat(stream.fileno());need(stat.S_ISREG(meta.st_mode) and meta.st_nlink==1 and 0<meta.st_size<=536870912)
   digest=hashlib.sha256()
   for block in iter(lambda:stream.read(1048576),b''):digest.update(block)
   after=os.fstat(stream.fileno());need((after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns,after.st_nlink)==(meta.st_dev,meta.st_ino,meta.st_size,meta.st_mtime_ns,meta.st_ctime_ns,meta.st_nlink) and digest.hexdigest()==release.get('applicationJarSha256'),'RETAINED_JENKINS_BINARY_DIFFERS')
  approved.append((int(directory.name),oldcommit,None))
  if len(approved)==16:break
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
rows=[];skipped=[];custody=[];builder_files=[]
for number,oldcommit,preservation_sha in approved:
 tag='ci-'+str(number)+'-'+oldcommit[:12];folder=Path(retained)/('ci-'+str(number)+'-raw-receipts');preservation=None
 try:
  files={};origins={}
  for role,name in [('buildXml','build.xml'),('release','release.json'),('localBuild','local-build.json'),('fixtureCleanupPublic','fixture-cleanup.json')]:
   source=Path(jhome)/'jobs/doorhandle-java/builds'/str(number)/('build.xml' if role=='buildXml' else 'archive/artifacts/'+name)
   if batch=='ClosedRuntime':source,raw,origin=closed_original(number,name)
   elif batch=='FailedNative' and role=='fixtureCleanupPublic' and not source.is_file():
    recoveries=list(Path(retained).glob('ci-'+str(number)+'-recovery-cleanup-*.json'))
    need(len(recoveries)<=1,'AMBIGUOUS_GUARDED_RECOVERY_PUBLIC_RECEIPT')
    if not recoveries:continue
    source=recoveries[0];raw=stable(source);proof=json.loads(raw,object_pairs_hook=unique)
    need(set(proof)=={'status','commit','release','cleanupReceipt','cleanupReceiptSha256'} and proof['status']=='STOPPED' and proof['commit']==oldcommit and proof['release']==tag and proof['cleanupReceipt']==remote+'/verification/'+tag+'/checkout/work/compact-fixtures/cleanup-receipt.json','GUARDED_RECOVERY_PUBLIC_RECEIPT_DIFFERS')
    origin='ACTUAL_GUARDED_RECOVERY_PUBLIC_RECEIPT'
   elif source.is_file():
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
    need(batch!='ClosedRuntime' and role not in ('buildXml','release'),'MISSING_LOCAL_CONTROL_'+role.upper());continue
   if batch=='ClosedRuntime':need((len(raw),sha(raw))==closed_originals[number][name],'CLOSED_RUNTIME_ORIGINAL_BYTES_DRIFT')
   files[role]={'source':str(source),'file':name,'bytes':len(raw),'sha256':sha(raw)};origins[role]={'origin':origin,'bytes':len(raw),'sha256':sha(raw)}
  rel=json.loads(stable(files['release']['source']),object_pairs_hook=unique)
  need(rel.get('release')==tag and rel.get('commit')==oldcommit and type(rel.get('sourceSha256')) is str and len(rel['sourceSha256'])==64)
  if batch=='ClosedRuntime':
   for name in ('ecs-tool-preparation.json','candidate-build-tools-transport.json'):
    source,raw,origin=closed_original(number,name)
    builder_files.append({'release':tag,'file':name,'source':str(source),'bytes':len(raw),'sha256':sha(raw),'origin':origin})
  rows.append({'release':tag,'commit':oldcommit,'sourceSha256':rel['sourceSha256'],'files':files})
  custody.append({'release':tag,'controls':origins,'preservationSha256':preservation_sha if preservation else None})
 except Exception as error:skipped.append({'release':tag,'reason':str(error) if type(error) is ValueError and str(error).replace('_','').isalnum() else type(error).__name__})
authority_files=[];authority_custody=[]
if batch=='RetiredCopies':
 authority_tag='ci-203-24f8eb4b02bf';authority_commit='24f8eb4b02bf290c6dd4e186eb78c5f3c80f3b88'
 originals={
  'build.xml':(298698,'0cd9460dc8e062d6e88cdb0042ef9bd9d9db6d0ed7768b1d44631aa1d54d1643'),
  'release.json':(393,'5c0a0c7038eaf7c38898aa03b89e50691e9a3585d96d1e9da12e7cd40052dbf5'),
  'source.tar.gz':(102379,'bb6e43405b0c696923aa3f7e699872706b1cd14323e83a475c44b734d1bcc882'),
  'native-jar-duplicate-request.json':(5101,'67ed4014faf649b1f3d269c10d70bdc6022cc16ea456af89bb8f8e8bfe1c5fd3'),
  'native-jar-duplicate-canonical-plan.json':(12244,'1130700b7cc6a79cb50a944d18f2e2e0e55fc3df20d75f37138ecab155845cc3'),
  'native-jar-duplicate-canonical-receipt.json':(2311,'8035c82ff336a9d39e02b8ce9f35390c7b7f6e776b2b6967d7901b57e91df9c1'),
  'native-jar-duplicate-canonical-journal.jsonl':(2592,'2da56d51b56359cd349842bfc5cca11fd08d935adbeef5d0c9b6f2c51ab49d83'),
 }
 folder=Path(retained)/'ci-203-raw-receipts';preservation=None;authority_raw={}
 for name,(size,checksum) in originals.items():
  suffix='/jobs/doorhandle-java/builds/203'+('/build.xml' if name=='build.xml' else '/archive/artifacts/'+name)
  source=Path(jhome)/'jobs/doorhandle-java/builds/203'/('build.xml' if name=='build.xml' else 'archive/artifacts/'+name)
  if source.is_file():raw=stable(source);origin='ACTUAL_JENKINS_ORIGINAL'
  else:
   if preservation is None:
    proof=stable(folder/'preservation.json');need(sha(proof)=='c28ba9766654a9637e18ae9e4085fc160cdb41f7751ddf92e9266ffac428d8b9','RETIRED_AUTHORITY_CUSTODY_SHA_DRIFT')
    preservation=json.loads(proof,object_pairs_hook=unique)
    need(preservation.get('build')==203 and preservation.get('commit')==authority_commit and preservation.get('result')=='SUCCESS' and type(preservation.get('files')) is list,'RETIRED_AUTHORITY_CUSTODY_CONTEXT_DRIFT')
   source=folder/name;raw=stable(source)
   if name=='build.xml':need(preservation.get('buildXmlSha256')==checksum,'RETIRED_AUTHORITY_TERMINAL_CUSTODY_DRIFT')
   else:
    matches=[r for r in preservation['files'] if r.get('path')==name];need(len(matches)==1,'RETIRED_AUTHORITY_CUSTODY_MEMBER_MISSING')
    row=matches[0];need(row.get('bytes')==size and row.get('sha256')==checksum and str(row.get('original','')).replace(chr(92),'/').endswith(suffix),'RETIRED_AUTHORITY_CUSTODY_MEMBER_DRIFT')
   origin='PINNED_PRESERVED_JENKINS_ORIGINAL'
  need(len(raw)==size and sha(raw)==checksum,'RETIRED_AUTHORITY_ORIGINAL_BYTES_DRIFT')
  authority_raw[name]=raw
  authority_files.append({'source':str(source),'file':name,'bytes':size,'sha256':checksum})
  authority_custody.append({'file':name,'origin':origin,'bytes':size,'sha256':checksum})
 rel=json.loads(authority_raw['release.json'],object_pairs_hook=unique)
 need(rel.get('kind')=='doorhandle-maintenance-source' and rel.get('action')=='reclaim-build-outputs' and rel.get('release')==authority_tag and rel.get('commit')==authority_commit and rel.get('sourceSha256')==originals['source.tar.gz'][1] and rel.get('maintenanceOnly') is True and rel.get('testsExecuted') is False and rel.get('applicationBuilt') is False,'RETIRED_AUTHORITY_RELEASE_CONTEXT_DRIFT')
print(json.dumps({'helpers':helpers,'rows':rows,'skipped':skipped,'custody':custody,'builderFiles':builder_files,'authorityFiles':authority_files,'authorityCustody':authority_custody}))
'@
$local=(Invoke-NativeJar $python @('-I','-B','-c',$reader,$archive,$Commit,$RetainedControlRoot,$jenkinsHome,$RemoteRoot,$Tag,$CanonicalBatch) | Select-Object -Last 1) | ConvertFrom-Json -AsHashtable
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
if ($CanonicalBatch -ceq 'RetiredCopies') {
    Require-NativeJar (@($local.authorityFiles).Count -eq 7 -and @($local.authorityFiles.file | Select-Object -Unique).Count -eq 7) 'Retired copies require the complete fixed seven-original authority bundle.'
    foreach ($binding in $local.authorityFiles) {
        Require-NativeJar ($binding.file -cin @('build.xml','release.json','source.tar.gz','native-jar-duplicate-request.json','native-jar-duplicate-canonical-plan.json','native-jar-duplicate-canonical-receipt.json','native-jar-duplicate-canonical-journal.jsonl')) 'Unknown retired-copy authority member.'
        $uploads+=@{relative="inbox/$Tag/native-retired-candidate-controls/ci-203-24f8eb4b02bf/$($binding.file)";source=$binding.source;bytes=$binding.bytes;sha256=$binding.sha256}
    }
}
if ($CanonicalBatch -ceq 'ClosedRuntime') {
    Require-NativeJar (@($local.builderFiles).Count -eq 4) 'Both closed builder original Jenkins references are required.'
    foreach($binding in $local.builderFiles) {
        Require-NativeJar ($binding.release -cin @('ci-204-24f8eb4b02bf','ci-207-eb286c623177') -and $binding.file -cin @('ecs-tool-preparation.json','candidate-build-tools-transport.json')) 'Unknown closed builder original reference.'
        $uploads+=@{relative="inbox/$Tag/native-jar-duplicate-controls/$($binding.release)/$($binding.file)";source=$binding.source;bytes=$binding.bytes;sha256=$binding.sha256}
    }
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
encoded=sys.stdin.buffer.read(131073).strip() if sys.argv[1]=='--context-stdin' else sys.argv[1].encode('ascii')
need(0<len(encoded)<=131072)
data=json.loads(base64.b64decode(encoded,validate=True));root=Path(data['root']);inbox=root/'inbox'/data['tag']
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
Require-NativeJar ($finalContext.Length -le 131072) 'The fixed final control context exceeds its bounded stdin transport.'
$finalized=(Invoke-NativeJar $ssh ($SshOptions+@('-p',$PortText,$Destination,"python3 -I -B -c '$launcher' --context-stdin finish")) -InputText $finalContext | Select-Object -Last 1) | ConvertFrom-Json
Require-NativeJar ($finalized.status -ceq 'FINALIZED' -and $finalized.release -ceq $Tag) 'The original uploaded control files changed or lost their private identity.'
$helper="$RemoteRoot/inbox/$Tag/retire-failed-native-jar-duplicates.py"
$helperSha=$local.helpers.'script/jenkins/retire-failed-native-jar-duplicates.py'.sha256
$common="--root '$RemoteRoot' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --mode '$Mode' --instance-id '$instance' --machine-id '$machine' --current-receipt-sha256 '$currentReceiptSha'"
if($CanonicalBatch -ceq 'ClosedRuntime') {$common+=" --jar-batch failed-204-207"}
if($CanonicalBatch -ceq 'FailedNative') {$common+=" --jar-batch failed-native-retention-v1"}
function Invoke-NativeJarPhase([string]$Phase,[string]$Flags='') {
    $guard="test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$helperSha' && "
    return (Invoke-NativeJar $ssh ($SshOptions+@('-p',$PortText,$Destination,"${guard}python3 -I -B '$helper' --phase '$Phase' $common $Flags")) | Select-Object -Last 1) | ConvertFrom-Json
}
$capturePhase=if($CanonicalBatch -cin @('Recent','RetiredCopies','ClosedRuntime','FailedNative')){'capture-canonical-request'}else{'capture-request'}
$captured=Invoke-NativeJarPhase $capturePhase "--local-spec-sha256 '$specSha'"
Require-NativeJar ($captured.status -ceq 'CAPTURED' -and $captured.request.sha256 -cmatch '^[a-f0-9]{64}$') 'The actual ECS control snapshot was not captured.'
$requestSha=$captured.request.sha256
function Copy-NativeJarEvidence($Observed) {
    foreach ($entry in @(@('capture','native-jar-duplicate-capture.json'),@('request','native-jar-duplicate-request.json'),@('plan','native-jar-duplicate-plan.json'),@('receipt','native-jar-duplicate-receipt.json'),@('journal','native-jar-duplicate-journal.jsonl'),@('builderPlan','native-builder-retirement-plan.json'),@('builderReceipt','native-builder-retirement-receipt.json'),@('builderJournal','native-builder-retirement-journal.jsonl'),@('publicLayerPlan','native-public-layer-duplicate-plan.json'),@('publicLayerReceipt','native-public-layer-duplicate-receipt.json'),@('publicLayerJournal','native-public-layer-duplicate-journal.jsonl'),@('generatedArchivePlan','native-generated-public-image-archive-plan.json'),@('generatedArchiveReceipt','native-generated-public-image-archive-receipt.json'),@('generatedArchiveJournal','native-generated-public-image-archive-journal.jsonl'),@('pythonCachePlan','native-python-build-cache-plan.json'),@('pythonCacheReceipt','native-python-build-cache-receipt.json'),@('pythonCacheJournal','native-python-build-cache-journal.jsonl'),@('canonicalPlan','native-jar-duplicate-canonical-plan.json'),@('canonicalReceipt','native-jar-duplicate-canonical-receipt.json'),@('canonicalJournal','native-jar-duplicate-canonical-journal.jsonl'),@('recentFixturePlan','native-jar-duplicate-fixture-object-plan.json'),@('recentFixtureReceipt','native-jar-duplicate-fixture-object-receipt.json'),@('recentFixtureJournal','native-jar-duplicate-fixture-object-journal.jsonl'),@('retiredCandidatePlan','native-retired-candidate-copy-plan.json'),@('retiredCandidateReceipt','native-retired-candidate-copy-receipt.json'),@('retiredCandidateJournal','native-retired-candidate-copy-journal.jsonl'))) {
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
    $builders=$Observed.PSObject.Properties['builderOriginals']
    if($null -ne $builders) {
        Require-NativeJar (@($builders.Value).Count -le 2) 'Closed builder frozen originals exceed the exact batch.'
        foreach($binding in @($builders.Value)) {
            Require-NativeJar ($binding.file -cin @('native-builder-retirement-inspect/ci-204-24f8eb4b02bf.json','native-builder-retirement-inspect/ci-207-eb286c623177.json') -and $binding.bytes -gt 0 -and $binding.bytes -le 2MB -and $binding.sha256 -cmatch '^[a-f0-9]{64}$') 'Unknown frozen builder inspection original.'
            $file=Join-Path $workspace ('artifacts/'+$binding.file.Replace('/','-'))
            Require-NativeJar (-not (Test-Path -LiteralPath $file)) 'Frozen builder originals cannot be overwritten.'
            $null=Invoke-NativeJar $scp ($SshOptions+@('-P',$PortText,"${Destination}:$RemoteRoot/inbox/$Tag/$($binding.file)",$file))
            Assert-NativeJarPath $file
            Require-NativeJar ((Get-Item -LiteralPath $file).Length -eq $binding.bytes -and (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $binding.sha256) 'A frozen builder inspection changed during collection.'
        }
    }
}
if($CanonicalBatch -ceq 'FailedNative') {
    $failedPlans=@{};$failedResults=@{};$failedError=$false;$failedStage='admission'
    try {
        Require-NativeJar (@($local.skipped).Count -eq 0 -and @($captured.skipped | Where-Object {$_.reason -cne 'FAILED_NATIVE_BINARIES_NOT_PRESENT'}).Count -eq 0) 'Failed native retention lacks complete terminal originals or has unknown binary state.'
        foreach($step in @(@('fixtures','plan-recent-fixtures','apply-recent-fixtures'),@('copies','plan','apply'),@('canonical','plan-canonical','apply-canonical'))) {
            $key=$step[0];$failedStage=$key+'-plan'
            $planned=Invoke-NativeJarPhase $step[1] "--request-sha256 '$requestSha'"
            Require-NativeJar ($planned.status -ceq 'PLANNED' -and $planned.failedNativePolicy -ceq 'failed-native-retention-v1' -and $planned.plan.sha256 -cmatch '^[a-f0-9]{64}$') 'Failed native retention did not produce its exact plan.'
            Require-NativeJar (@($planned.skipped | Where-Object {$key -cne 'copies' -or $_.reason -cne 'FAILED_NATIVE_COPY_NOT_PRESENT'}).Count -eq 0) 'An eligible old binary or fixture could not be admitted; retain the batch.'
            $failedPlans[$key]=$planned;$failedStage=$key+'-apply'
            $applied=Invoke-NativeJarPhase $step[2] "--request-sha256 '$requestSha' --plan-sha256 '$($planned.plan.sha256)'"
            Require-NativeJar ($applied.status -cin @('REMOVED','NO_ACTION') -and $applied.failedNativePolicy -ceq 'failed-native-retention-v1' -and $applied.receipt.sha256 -cmatch '^[a-f0-9]{64}$') 'Failed native retention did not complete; preserve its original partial evidence.'
            $failedResults[$key]=$applied
        }
    } catch {$failedError=$true}
    finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}
    Require-NativeJar (-not $failedError -and $failedResults.Count -eq 3) ('Failed native retention failed or is unknown at '+$failedStage+'; original controls are retained.')
    $receipts=@{}
    foreach($step in @(@('fixtures','native-jar-duplicate-fixture-object-receipt.json'),@('copies','native-jar-duplicate-receipt.json'),@('canonical','native-jar-duplicate-canonical-receipt.json'))) {
        $receipt=Get-Content -LiteralPath (Join-Path $workspace ('artifacts/'+$step[1])) -Raw -Encoding utf8 | ConvertFrom-Json -Depth 24
        Require-NativeJar ($receipt.status -cin @('REMOVED','NO_ACTION') -and $receipt.failedNativePolicy -ceq 'failed-native-retention-v1' -and $receipt.current.release -ceq $Tag -and $receipt.current.commit -ceq $Commit -and $receipt.current.sourceSha256 -ceq $SourceSha256 -and $receipt.identity.instanceId -ceq $instance -and $receipt.identity.machineId -ceq $machine -and $receipt.requestSha256 -ceq $requestSha -and $receipt.planSha256 -ceq $failedPlans[$step[0]].plan.sha256 -and $null -eq $receipt.failure) 'Collected failed native receipt differs from its exact successful operation.'
        $receipts[$step[0]]=$receipt
    }
    Require-NativeJar ($receipts.fixtures.dataDirectoriesPreserved -eq $true -and $receipts.fixtures.imagesPreserved -eq $true -and $receipts.fixtures.volumesPreserved -eq $true -and $receipts.fixtures.jarDeletionPerformed -eq $false -and $receipts.copies.inboxKeepersPreserved -eq $true -and $receipts.canonical.sourceArchivesDataAndReportsHaveNoDeletionApi -eq $true -and $receipts.canonical.testsRunByRetirement -eq $false) 'Failed native retention lacks required preservation proof.'
    [ordered]@{schemaVersion=1;kind='doorhandle-failed-native-retention-ci';policy='failed-native-retention-v1';current=$spec.current;identity=$spec.identity;status='COMPLETE';selectedFailures=$spec.candidates.Count;alreadyAbsent=@($captured.skipped);deletedJarFiles=(@($receipts.copies.deleted).Count+@($receipts.canonical.deleted).Count);candidateAllocatedBytes=($failedPlans.copies.candidateAllocatedBytes+$failedPlans.canonical.candidateAllocatedBytes);retiredMysqlObjects=@($receipts.fixtures.removed).Count;localControlCustody=$local.custody;sourceArchivesDataAndReportsHaveNoDeletionApi=$true;imagesPreserved=$true;volumesPreserved=$true;testsRunByRetirement=$false;binaryRebuildByteIdentityClaimed=$false} | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath (Join-Path $workspace 'artifacts/native-jar-duplicate-ci.json') -Encoding utf8
    return
}
if($CanonicalBatch -ceq 'ClosedRuntime') {
    $closedPlans=@{};$closedResults=@{};$closedFailed=$false;$closedStage='builder-plan'
    try {
        Require-NativeJar ($spec.candidates.Count -eq 2 -and @($local.skipped).Count -eq 0 -and @($captured.skipped).Count -eq 0) 'Closed runtime maintenance requires both complete original control bundles.'
        $closedPlans.builder=Invoke-NativeJarPhase 'plan-closed-builders' "--request-sha256 '$requestSha'"
        $p=$closedPlans.builder
        Require-NativeJar ($p.status -ceq 'PLANNED' -and $p.scope -ceq 'CLOSED_RUNTIME_BUILDERS' -and $p.plan.sha256 -cmatch '^[a-f0-9]{64}$' -and $p.skipped -is [array] -and @($p.skipped).Count -eq 0 -and ($p.builderCount+$p.alreadyAbsent) -eq 2) 'Both exact stopped builders require complete original ownership evidence.'
        $closedStage='builder-apply'
        $closedResults.builder=Invoke-NativeJarPhase 'apply-closed-builders' "--request-sha256 '$requestSha' --plan-sha256 '$($p.plan.sha256)'"
        $r=$closedResults.builder
        Require-NativeJar ($r.status -cin @('REMOVED','NO_ACTION') -and $r.scope -ceq 'CLOSED_RUNTIME_BUILDERS' -and ($r.removedBuilders+$r.alreadyAbsent) -eq 2 -and $r.retiredMysqlObjects -eq 0 -and -not $r.jarDeletionPerformed -and $r.volumesPreserved -and $r.imagesPreserved -and $r.directoriesPreserved) 'Builder retirement is incomplete; all fixture and JAR phases remain blocked.'
        $closedStage='fixture-plan'
        $closedPlans.fixture=Invoke-NativeJarPhase 'plan-recent-fixtures' "--request-sha256 '$requestSha'"
        $p=$closedPlans.fixture
        Require-NativeJar ($p.status -ceq 'PLANNED' -and $p.plan.sha256 -cmatch '^[a-f0-9]{64}$' -and $p.skipped -is [array] -and @($p.skipped).Count -eq 0 -and ($p.objectCount+$p.alreadyAbsent) -eq 1 -and $p.noObject -eq 1) 'The 204 stopped object and 207 no-object proof must both be admitted.'
        $closedStage='fixture-apply'
        $closedResults.fixture=Invoke-NativeJarPhase 'apply-recent-fixtures' "--request-sha256 '$requestSha' --plan-sha256 '$($p.plan.sha256)'"
        $r=$closedResults.fixture
        Require-NativeJar ($r.status -cin @('REMOVED','NO_ACTION') -and ($r.removedContainers+$r.alreadyAbsent) -eq 1 -and $r.noObject -eq 1 -and -not $r.jarDeletionPerformed) 'Fixture object cleanup is incomplete; both JAR phases remain blocked.'
        $closedStage='duplicate-plan'
        $closedPlans.duplicate=Invoke-NativeJarPhase 'plan' "--request-sha256 '$requestSha'"
        $p=$closedPlans.duplicate
        Require-NativeJar ($p.status -ceq 'PLANNED' -and $p.plan.sha256 -cmatch '^[a-f0-9]{64}$' -and $p.skipped -is [array] -and @($p.skipped).Count -eq 0 -and $p.closedJarBatch -ceq 'failed-204-207' -and $p.candidateCount -eq 2 -and $p.candidateBytes -eq 760603852) 'Both candidate copies need a complete exact plan before any JAR removal.'
        $closedStage='duplicate-apply'
        $closedResults.duplicate=Invoke-NativeJarPhase 'apply' "--request-sha256 '$requestSha' --plan-sha256 '$($p.plan.sha256)'"
        $r=$closedResults.duplicate
        Require-NativeJar ($r.status -ceq 'REMOVED' -and $r.closedJarBatch -ceq 'failed-204-207' -and $r.deletedFiles -eq 2) 'Both candidate copies must be removed with their inbox keepers retained.'
        $closedStage='canonical-plan'
        $closedPlans.canonical=Invoke-NativeJarPhase 'plan-canonical' "--request-sha256 '$requestSha'"
        $p=$closedPlans.canonical
        Require-NativeJar ($p.status -ceq 'PLANNED' -and $p.plan.sha256 -cmatch '^[a-f0-9]{64}$' -and $p.skipped -is [array] -and @($p.skipped).Count -eq 0 -and $p.closedJarBatch -ceq 'failed-204-207' -and $p.candidateCount -eq 2 -and $p.candidateBytes -eq 760603852) 'Both failed unpublished inbox JARs need a complete exact plan.'
        $closedStage='canonical-apply'
        $closedResults.canonical=Invoke-NativeJarPhase 'apply-canonical' "--request-sha256 '$requestSha' --plan-sha256 '$($p.plan.sha256)'"
        $r=$closedResults.canonical
        Require-NativeJar ($r.status -ceq 'REMOVED' -and $r.closedJarBatch -ceq 'failed-204-207' -and $r.deletedFiles -eq 2) 'The closed four-file retirement is incomplete.'
    } catch {$closedFailed=$true}
    finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}
    Require-NativeJar (-not $closedFailed) ('Closed runtime maintenance failed or is unknown at '+$closedStage+'; original evidence was collected and no partial success is permitted.')
    function Read-ClosedRuntimeOriginal([string]$Name,$Binding) {
        $file=Join-Path $workspace ('artifacts/'+$Name)
        Require-NativeJar ((Get-Item -LiteralPath $file).Length -eq $Binding.bytes -and (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $Binding.sha256) 'Collected closed runtime plan or receipt differs from its original server bytes.'
        return Get-Content -LiteralPath $file -Raw -Encoding utf8 | ConvertFrom-Json -Depth 32
    }
    function Require-ClosedRuntimeContext($Document,[string]$Kind) {
        Require-NativeJar ($Document.kind -ceq $Kind -and $Document.closedJarBatch -ceq 'failed-204-207' -and $Document.current.release -ceq $Tag -and $Document.current.commit -ceq $Commit -and $Document.current.sourceSha256 -ceq $SourceSha256 -and $Document.identity.instanceId -ceq $instance -and $Document.identity.machineId -ceq $machine -and $Document.identity.executionLocation -ceq 'ECS' -and $Document.requestSha256 -ceq $requestSha -and $Document.skipped -is [array] -and @($Document.skipped).Count -eq 0) 'A closed runtime original has different source, host, batch or skipped members.'
    }
    $builderPlan=Read-ClosedRuntimeOriginal 'native-builder-retirement-plan.json' $closedPlans.builder.plan
    $builderReceipt=Read-ClosedRuntimeOriginal 'native-builder-retirement-receipt.json' $closedResults.builder.receipt
    Require-ClosedRuntimeContext $builderPlan 'doorhandle-historical-builder-retirement-plan'
    Require-ClosedRuntimeContext $builderReceipt 'doorhandle-historical-builder-retirement-receipt'
    $builderIds=@($builderReceipt.removed | ForEach-Object {$_.containerId})+@($builderReceipt.alreadyAbsent)
    $exactBuilderIds=@('09646d9dcc4d135e804e40dcfb9718917d2b29c4296ef9fcf8fc9bf975461724','ee23bee6a53f673e013f0e92e0fd838c91514d0e30f845204ba9695dc7bce673')
    Require-NativeJar ($builderReceipt.status -cin @('REMOVED','NO_ACTION') -and $builderReceipt.failure -eq $null -and $builderReceipt.scope -ceq 'CLOSED_RUNTIME_BUILDERS' -and $builderReceipt.planSha256 -ceq $closedPlans.builder.plan.sha256 -and $builderIds.Count -eq 2 -and @($builderIds | Select-Object -Unique).Count -eq 2 -and @($builderIds | Where-Object {$_ -cnotin $exactBuilderIds}).Count -eq 0 -and $builderReceipt.retiredMysqlObjects -is [array] -and @($builderReceipt.retiredMysqlObjects).Count -eq 0 -and $builderReceipt.jarDeletionPerformed -is [bool] -and -not $builderReceipt.jarDeletionPerformed) 'The builder receipt must prove precisely the two ordinary container removals without fixture, volume or JAR deletion.'
    foreach($flag in @('mysqlDataDirectoriesPreserved','imagesPreserved','volumesPreserved','directoriesPreserved')) {Require-NativeJar ($builderReceipt.$flag -is [bool] -and $builderReceipt.$flag) 'Builder retirement must preserve all data, directories, state volumes and images.'}
    Require-NativeJar ((Get-FileHash -LiteralPath (Join-Path $workspace 'artifacts/native-builder-retirement-journal.jsonl') -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $builderReceipt.journalSha256) 'The builder journal differs from its original receipt.'
    $fixturePlan=Read-ClosedRuntimeOriginal 'native-jar-duplicate-fixture-object-plan.json' $closedPlans.fixture.plan
    $fixtureReceipt=Read-ClosedRuntimeOriginal 'native-jar-duplicate-fixture-object-receipt.json' $closedResults.fixture.receipt
    Require-ClosedRuntimeContext $fixturePlan 'doorhandle-recent-mysql-fixture-object-plan'
    Require-ClosedRuntimeContext $fixtureReceipt 'doorhandle-recent-mysql-fixture-object-receipt'
    Require-NativeJar ($fixturePlan.prerequisite.sha256 -ceq $closedResults.builder.receipt.sha256 -and $fixturePlan.prerequisite.bytes -eq $closedResults.builder.receipt.bytes) 'Fixture admission lost its exact successful builder predecessor.'
    Require-NativeJar ((Get-FileHash -LiteralPath (Join-Path $workspace 'artifacts/native-jar-duplicate-fixture-object-journal.jsonl') -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $fixtureReceipt.journalSha256) 'The collected fixture journal differs from its original receipt.'
    $fixtureIds=@($fixtureReceipt.removed | ForEach-Object {$_.containerId})+@($fixtureReceipt.alreadyAbsent)
    Require-NativeJar ($fixtureReceipt.status -cin @('REMOVED','NO_ACTION') -and $fixtureReceipt.failure -eq $null -and $fixtureReceipt.planSha256 -ceq $closedPlans.fixture.plan.sha256 -and $fixtureIds.Count -eq 1 -and $fixtureIds[0] -ceq 'cad56ad37f6d63465bad18260464b7c5dfe168e68159121a3308b4a0212de5b9' -and $fixtureReceipt.noObject -is [array] -and @($fixtureReceipt.noObject).Count -eq 1 -and $fixtureReceipt.noObject[0] -ceq 'ci-207-eb286c623177') 'The final fixture receipt lacks the exact 204 object or explicit 207 no-object proof.'
    foreach($flag in @('dataDirectoriesPreserved','imagesPreserved','volumesPreserved','sourceArchivesAndReportsPreserved')) {Require-NativeJar ($fixtureReceipt.$flag -is [bool] -and $fixtureReceipt.$flag) 'Fixture retirement did not preserve all original data and images.'}
    Require-NativeJar ($fixtureReceipt.jarDeletionPerformed -is [bool] -and -not $fixtureReceipt.jarDeletionPerformed) 'The fixture phase cannot remove any JAR.'
    $closedExpected=@{'ci-204-24f8eb4b02bf'='fd5d66a17d2069fc10a0c18403d2399f510b9784b1f404330d7349001e552f67';'ci-207-eb286c623177'='2accfa412ac67a244e5f0e47feba890141a68ed674ef746729c0402e62102ee1'}
    foreach($stage in @('duplicate','canonical')) {
        $stem=if($stage -ceq 'duplicate'){'native-jar-duplicate'}else{'native-jar-duplicate-canonical'}
        $kind=if($stage -ceq 'duplicate'){'doorhandle-failed-native-jar-duplicate'}else{'doorhandle-failed-native-canonical-jar-retirement'}
        $plan=Read-ClosedRuntimeOriginal ($stem+'-plan.json') $closedPlans[$stage].plan
        $proof=Read-ClosedRuntimeOriginal ($stem+'-receipt.json') $closedResults[$stage].receipt
        Require-ClosedRuntimeContext $plan ($kind+'-plan'); Require-ClosedRuntimeContext $proof ($kind+'-receipt')
        Require-NativeJar ((Get-FileHash -LiteralPath (Join-Path $workspace ('artifacts/'+$stem+'-journal.jsonl')) -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $proof.journalSha256) 'A collected JAR journal differs from its original receipt.'
        $previous=if($stage -ceq 'duplicate'){$closedResults.fixture.receipt}else{$closedResults.duplicate.receipt}
        Require-NativeJar ($plan.prerequisite.sha256 -ceq $previous.sha256 -and $plan.prerequisite.bytes -eq $previous.bytes) 'The next JAR phase lost its original successful predecessor binding.'
        Require-NativeJar ($plan.candidates -is [array] -and @($plan.candidates).Count -eq 2 -and $proof.deleted -is [array] -and @($proof.deleted).Count -eq 2 -and $proof.status -ceq 'REMOVED' -and $proof.failure -eq $null -and $proof.planSha256 -ceq $closedPlans[$stage].plan.sha256 -and $proof.retainedQuarantinePaths -is [array] -and @($proof.retainedQuarantinePaths).Count -eq 0 -and $proof.sourceArchivesDataAndReportsHaveNoDeletionApi -is [bool] -and $proof.sourceArchivesDataAndReportsHaveNoDeletionApi) 'A JAR phase has partial removal or unresolved quarantine.'
        foreach($release in $closedExpected.Keys) {
            $path=if($stage -ceq 'duplicate'){"verification/$release/checkout/work/compact-fixtures/candidate-app.jar"}else{"inbox/$release/application.jar"}
            $targets=@($plan.candidates | Where-Object {$_.context.release -ceq $release})
            $deleted=@($proof.deleted | Where-Object {$_.path -ceq $path})
            Require-NativeJar ($targets.Count -eq 1 -and $deleted.Count -eq 1 -and $targets[0].target.path -ceq $path -and $targets[0].target.sha256 -ceq $closedExpected[$release] -and $targets[0].target.bytes -eq 380301926 -and $deleted[0].sha256 -ceq $closedExpected[$release] -and $deleted[0].bytes -eq 380301926 -and $deleted[0].capturedInodeVerified -is [bool] -and $deleted[0].capturedInodeVerified) 'A retired file differs from its exact reviewed plan, bytes, SHA or captured inode.'
            if($stage -ceq 'duplicate') {Require-NativeJar ($deleted[0].keeperPath -ceq "inbox/$release/application.jar" -and $deleted[0].keeperVerifiedAfter -is [bool] -and $deleted[0].keeperVerifiedAfter) 'The candidate phase did not preserve its exact inbox keeper.'}
        }
        if($stage -ceq 'duplicate') {Require-NativeJar ($proof.inboxKeepersPreserved -is [bool] -and $proof.inboxKeepersPreserved) 'Both inbox keepers must remain through candidate retirement.'}
        else {Require-NativeJar ($proof.binaryDisposition -ceq 'RETIRED' -and $proof.testsRunByRetirement -is [bool] -and -not $proof.testsRunByRetirement -and $proof.binaryRebuildByteIdentityClaimed -is [bool] -and -not $proof.binaryRebuildByteIdentityClaimed) 'Canonical retirement cannot claim testing or byte-identical regeneration.'}
    }
    [ordered]@{schemaVersion=1;kind='doorhandle-closed-runtime-jar-ci';scope='CLOSED_RUNTIME_204_207';current=$spec.current;identity=$spec.identity;status='REMOVED';requestSha256=$requestSha;deletedFiles=4;noObject=@('ci-207-eb286c623177');builderPlanSha256=$closedPlans.builder.plan.sha256;builderReceiptSha256=$closedResults.builder.receipt.sha256;fixturePlanSha256=$closedPlans.fixture.plan.sha256;fixtureReceiptSha256=$closedResults.fixture.receipt.sha256;duplicatePlanSha256=$closedPlans.duplicate.plan.sha256;duplicateReceiptSha256=$closedResults.duplicate.receipt.sha256;canonicalPlanSha256=$closedPlans.canonical.plan.sha256;canonicalReceiptSha256=$closedResults.canonical.receipt.sha256;localControlCustody=$local.custody;sourceArchivesDataAndReportsHaveNoDeletionApi=$true;testsRunByRetirement=$false;binaryRebuildByteIdentityClaimed=$false} | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath (Join-Path $workspace 'artifacts/native-jar-duplicate-ci.json') -Encoding utf8
    return
}
if($CanonicalBatch -ceq 'RetiredCopies') {
    $copyPlanned=$null;$copyResult=$null;$copyFailed=$false;$copyStage='plan'
    try {
        Require-NativeJar ($spec.candidates.Count -eq 3 -and @($local.skipped).Count -eq 0 -and @($captured.skipped).Count -eq 0) 'Retired copies require all three original failed-build control bundles.'
        $copyPlanned=Invoke-NativeJarPhase 'plan-retired-candidate-copies' "--request-sha256 '$requestSha'"
        foreach($count in @($copyPlanned.candidateTargetCount,$copyPlanned.candidateBytes,$copyPlanned.candidateAllocatedBytes)) {Require-NativeJar (($count -is [int] -or $count -is [long]) -and $count -gt 0) 'Retired-copy planning omitted strict positive target and byte counts.'}
        Require-NativeJar ($copyPlanned.status -ceq 'PLANNED' -and $copyPlanned.candidateTargetCount -eq 3 -and $copyPlanned.current.release -ceq $Tag -and $copyPlanned.current.commit -ceq $Commit -and $copyPlanned.current.sourceSha256 -ceq $SourceSha256 -and $copyPlanned.identity.instanceId -ceq $instance -and $copyPlanned.identity.machineId -ceq $machine -and $copyPlanned.plan.sha256 -cmatch '^[a-f0-9]{64}$' -and $copyPlanned.skipped -is [array] -and @($copyPlanned.skipped).Count -eq 0) 'Retired candidate copies lack a complete exact plan for this build and ECS.'
        $copyStage='apply'
        $copyResult=Invoke-NativeJarPhase 'apply-retired-candidate-copies' "--request-sha256 '$requestSha' --plan-sha256 '$($copyPlanned.plan.sha256)'"
        foreach($count in @($copyResult.deletedFiles,$copyResult.candidateTargetCount)) {Require-NativeJar (($count -is [int] -or $count -is [long]) -and $count -eq 3) 'Retired-copy execution requires three actual verified deletions.'}
        foreach($flag in @('sourceArchivesDataAndReportsHaveNoDeletionApi','inboxKeepersRecreated','binaryRebuildByteIdentityClaimed','testsRunByRetirement','imagesPreserved','volumesPreserved','directoriesPreserved')) {Require-NativeJar ($copyResult.$flag -is [bool]) 'Retired-copy execution omitted a strict preservation boolean.'}
        Require-NativeJar ($copyResult.directoriesPreserved) 'Retired-copy execution must preserve every original directory.'
        Require-NativeJar ($copyResult.status -ceq 'REMOVED' -and $copyResult.binaryDisposition -ceq 'RETIRED' -and $copyResult.current.release -ceq $Tag -and $copyResult.current.commit -ceq $Commit -and $copyResult.current.sourceSha256 -ceq $SourceSha256 -and $copyResult.identity.instanceId -ceq $instance -and $copyResult.identity.machineId -ceq $machine -and $copyResult.requestSha256 -ceq $requestSha -and $copyResult.planSha256 -ceq $copyPlanned.plan.sha256 -and $copyResult.sourceArchivesDataAndReportsHaveNoDeletionApi -and $copyResult.imagesPreserved -and $copyResult.volumesPreserved -and -not $copyResult.inboxKeepersRecreated -and -not $copyResult.binaryRebuildByteIdentityClaimed -and -not $copyResult.testsRunByRetirement) 'Retired-copy removal failed or is unknown; no successful maintenance result is permitted.'
    } catch {$copyFailed=$true}
    finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}
    $copyReceiptFile=Join-Path $workspace 'artifacts/native-retired-candidate-copy-receipt.json'
    $copyPlanFile=Join-Path $workspace 'artifacts/native-retired-candidate-copy-plan.json'
    Require-NativeJar (-not $copyFailed -and $null -ne $copyPlanned -and $null -ne $copyResult -and (Test-Path -LiteralPath $copyReceiptFile -PathType Leaf) -and (Test-Path -LiteralPath $copyPlanFile -PathType Leaf)) ('Retired candidate-copy maintenance failed or is unknown at '+$copyStage+'; original controls were collected.')
    Require-NativeJar ((Get-FileHash -LiteralPath $copyPlanFile -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $copyPlanned.plan.sha256 -and (Get-FileHash -LiteralPath $copyReceiptFile -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $copyResult.receipt.sha256) 'Collected retired-copy plan or receipt differs from its original server digest.'
    $copyReceipt=Get-Content -LiteralPath $copyReceiptFile -Raw -Encoding utf8 | ConvertFrom-Json -Depth 24
    foreach($list in @('deleted','skipped')) {Require-NativeJar ($copyReceipt.$list -is [array]) 'Collected retired-copy receipt omitted an exact operation list.'}
    foreach($flag in @('sourceArchivesDataAndReportsHaveNoDeletionApi','inboxKeepersRecreated','binaryRebuildByteIdentityClaimed','testsRunByRetirement','imagesPreserved','volumesPreserved','directoriesPreserved')) {Require-NativeJar ($copyReceipt.$flag -is [bool]) 'Collected retired-copy receipt omitted a strict preservation boolean.'}
    Require-NativeJar ($copyReceipt.directoriesPreserved) 'Collected retired-copy receipt must confirm all original directories were preserved.'
    Require-NativeJar (($copyReceipt.candidateTargetCount -is [int] -or $copyReceipt.candidateTargetCount -is [long]) -and $copyReceipt.candidateTargetCount -eq 3) 'Collected retired-copy receipt omitted the exact target count.'
    Require-NativeJar ($copyReceipt.kind -ceq 'doorhandle-retired-candidate-jar-copy-retirement-receipt' -and $copyReceipt.status -ceq 'REMOVED' -and $copyReceipt.binaryDisposition -ceq 'RETIRED' -and $copyReceipt.current.release -ceq $Tag -and $copyReceipt.current.commit -ceq $Commit -and $copyReceipt.current.sourceSha256 -ceq $SourceSha256 -and $copyReceipt.identity.instanceId -ceq $instance -and $copyReceipt.identity.machineId -ceq $machine -and $copyReceipt.requestSha256 -ceq $requestSha -and $copyReceipt.planSha256 -ceq $copyPlanned.plan.sha256 -and @($copyReceipt.deleted).Count -eq 3 -and @($copyReceipt.skipped).Count -eq 0 -and $copyReceipt.sourceArchivesDataAndReportsHaveNoDeletionApi -and $copyReceipt.imagesPreserved -and $copyReceipt.volumesPreserved -and -not $copyReceipt.inboxKeepersRecreated -and -not $copyReceipt.binaryRebuildByteIdentityClaimed -and -not $copyReceipt.testsRunByRetirement) 'Collected retired-copy receipt lacks exact source, host, plan, counts or preserved-data proof.'
    $summary=[ordered]@{schemaVersion=1;kind='doorhandle-retired-candidate-jar-copy-ci';current=$spec.current;identity=$spec.identity;status=$copyReceipt.status;requestSha256=$requestSha;planSha256=$copyPlanned.plan.sha256;receiptSha256=$copyResult.receipt.sha256;candidateTargetCount=$copyReceipt.candidateTargetCount;deletedFiles=@($copyReceipt.deleted).Count;candidateBytes=$copyPlanned.candidateBytes;candidateAllocatedBytes=$copyPlanned.candidateAllocatedBytes;localControlCustody=$local.custody;authorityControlCustody=$local.authorityCustody;binaryDisposition=$copyReceipt.binaryDisposition;sourceArchivesDataAndReportsHaveNoDeletionApi=$copyReceipt.sourceArchivesDataAndReportsHaveNoDeletionApi;inboxKeepersRecreated=$copyReceipt.inboxKeepersRecreated;binaryRebuildByteIdentityClaimed=$copyReceipt.binaryRebuildByteIdentityClaimed;testsRunByRetirement=$copyReceipt.testsRunByRetirement;imagesPreserved=$copyReceipt.imagesPreserved;volumesPreserved=$copyReceipt.volumesPreserved}
    $summary.directoriesPreserved=$copyReceipt.directoriesPreserved
    $summary|ConvertTo-Json -Depth 20|Set-Content -LiteralPath (Join-Path $workspace 'artifacts/native-retired-candidate-copy-ci.json') -Encoding utf8
    Write-Output ($summary|ConvertTo-Json -Depth 8 -Compress)
    return
}
if($CanonicalBatch -ceq 'Recent') {
    $canonicalPlanned=$null;$canonicalFailed=$false;$fixturePlanned=$null;$builderPlanned=$null;$recentStage='builder-plan'
    try {
        Require-NativeJar ($spec.candidates.Count -eq 3 -and @($captured.skipped).Count -eq 0) 'Recent maintenance requires all three original control bundles.'
        $builderPlanned=Invoke-NativeJarPhase 'plan-recent-builders' "--request-sha256 '$requestSha'"
        foreach($count in @($builderPlanned.builderCount,$builderPlanned.alreadyAbsent)) {Require-NativeJar (($count -is [int] -or $count -is [long]) -and $count -ge 0 -and $count -le 1) 'Recent builder planning omitted an exact zero-or-one count.'}
        Require-NativeJar ($builderPlanned.status -ceq 'PLANNED' -and $builderPlanned.scope -ceq 'RECENT_201_BUILDER_ONLY' -and $builderPlanned.plan.sha256 -cmatch '^[a-f0-9]{64}$' -and $builderPlanned.skipped -is [array] -and @($builderPlanned.skipped).Count -eq 0 -and ($builderPlanned.builderCount+$builderPlanned.alreadyAbsent) -eq 1) 'Recent #201 builder lacks complete exact admission.'
        $recentStage='builder-apply'
        $builderResult=Invoke-NativeJarPhase 'apply-recent-builders' "--request-sha256 '$requestSha' --plan-sha256 '$($builderPlanned.plan.sha256)'"
        foreach($count in @($builderResult.removedBuilders,$builderResult.alreadyAbsent,$builderResult.retiredMysqlObjects)) {Require-NativeJar (($count -is [int] -or $count -is [long]) -and $count -ge 0 -and $count -le 1) 'Recent builder execution omitted an exact zero-or-one count.'}
        foreach($flag in @('mysqlDataDirectoriesPreserved','imagesPreserved','volumesPreserved','directoriesPreserved','jarDeletionPerformed')) {Require-NativeJar ($builderResult.$flag -is [bool]) 'Recent builder execution omitted a strict preservation boolean.'}
        Require-NativeJar ($builderResult.status -cin @('REMOVED','NO_ACTION') -and $builderResult.scope -ceq 'RECENT_201_BUILDER_ONLY' -and $builderResult.current.release -ceq $Tag -and $builderResult.current.commit -ceq $Commit -and $builderResult.current.sourceSha256 -ceq $SourceSha256 -and $builderResult.identity.instanceId -ceq $instance -and $builderResult.identity.machineId -ceq $machine -and $builderResult.requestSha256 -ceq $requestSha -and $builderResult.planSha256 -ceq $builderPlanned.plan.sha256 -and ($builderResult.removedBuilders+$builderResult.alreadyAbsent) -eq 1 -and $builderResult.removedBuilders -eq $builderPlanned.builderCount -and $builderResult.alreadyAbsent -eq $builderPlanned.alreadyAbsent -and $builderResult.mysqlDataDirectoriesPreserved -and $builderResult.imagesPreserved -and $builderResult.volumesPreserved -and $builderResult.directoriesPreserved -and -not $builderResult.jarDeletionPerformed) 'Recent #201 builder removal failed or is unknown; fixture and canonical JAR retirement are blocked.'
        $recentStage='fixture-plan'
        $fixturePlanned=Invoke-NativeJarPhase 'plan-recent-fixtures' "--request-sha256 '$requestSha'"
        Require-NativeJar ($fixturePlanned.status -ceq 'PLANNED' -and $fixturePlanned.plan.sha256 -cmatch '^[a-f0-9]{64}$' -and @($fixturePlanned.skipped).Count -eq 0 -and ($fixturePlanned.objectCount+$fixturePlanned.alreadyAbsent) -eq 3) 'Recent MySQL fixture objects lack complete exact admission.'
        $recentStage='fixture-apply'
        $fixtureResult=Invoke-NativeJarPhase 'apply-recent-fixtures' "--request-sha256 '$requestSha' --plan-sha256 '$($fixturePlanned.plan.sha256)'"
        foreach($flag in @('dataDirectoriesPreserved','imagesPreserved','volumesPreserved','sourceArchivesAndReportsPreserved','jarDeletionPerformed')) {Require-NativeJar ($fixtureResult.$flag -is [bool]) 'Recent fixture execution omitted a strict preservation boolean.'}
        Require-NativeJar ($fixtureResult.status -cin @('REMOVED','NO_ACTION') -and $fixtureResult.current.release -ceq $Tag -and $fixtureResult.current.commit -ceq $Commit -and $fixtureResult.current.sourceSha256 -ceq $SourceSha256 -and $fixtureResult.identity.instanceId -ceq $instance -and $fixtureResult.identity.machineId -ceq $machine -and $fixtureResult.requestSha256 -ceq $requestSha -and $fixtureResult.planSha256 -ceq $fixturePlanned.plan.sha256 -and ($fixtureResult.removedContainers+$fixtureResult.alreadyAbsent) -eq 3 -and $fixtureResult.dataDirectoriesPreserved -eq $true -and $fixtureResult.imagesPreserved -eq $true -and $fixtureResult.volumesPreserved -eq $true -and $fixtureResult.sourceArchivesAndReportsPreserved -eq $true -and $fixtureResult.jarDeletionPerformed -eq $false) 'Recent MySQL fixture removal failed or is unknown; canonical JAR retirement is blocked.'
        $recentStage='canonical-plan'
        $canonicalPlanned=Invoke-NativeJarPhase 'plan-canonical' "--request-sha256 '$requestSha'"
        Require-NativeJar ($canonicalPlanned.status -ceq 'PLANNED' -and $canonicalPlanned.plan.sha256 -cmatch '^[a-f0-9]{64}$') 'No exact recent canonical JAR retirement plan was produced.'
        $recentStage='canonical-apply'
        $canonicalResult=Invoke-NativeJarPhase 'apply-canonical' "--request-sha256 '$requestSha' --plan-sha256 '$($canonicalPlanned.plan.sha256)'"
    } catch {$canonicalFailed=$true}
    finally {Copy-NativeJarEvidence (Invoke-NativeJarPhase 'inspect')}
    $canonicalReceiptFile=Join-Path $workspace 'artifacts/native-jar-duplicate-canonical-receipt.json'
    Require-NativeJar (-not $canonicalFailed -and $null -ne $canonicalPlanned -and (Test-Path -LiteralPath $canonicalReceiptFile -PathType Leaf)) ('Recent maintenance failed or is unknown at '+$recentStage+'; original controls were collected.')
    $builderReceiptFile=Join-Path $workspace 'artifacts/native-builder-retirement-receipt.json'
    Require-NativeJar (Test-Path -LiteralPath $builderReceiptFile -PathType Leaf) 'Recent #201 builder retirement lacks its original server receipt.'
    $builderReceipt=Get-Content -LiteralPath $builderReceiptFile -Raw -Encoding utf8 | ConvertFrom-Json -Depth 24
    foreach($list in @('removed','alreadyAbsent','retiredMysqlObjects','skipped')) {Require-NativeJar ($builderReceipt.$list -is [array]) 'Collected recent builder receipt omitted an exact operation list.'}
    foreach($flag in @('mysqlDataDirectoriesPreserved','imagesPreserved','volumesPreserved','directoriesPreserved','jarDeletionPerformed')) {Require-NativeJar ($builderReceipt.$flag -is [bool]) 'Collected recent builder receipt omitted a strict preservation boolean.'}
    Require-NativeJar ($builderReceipt.kind -ceq 'doorhandle-historical-builder-retirement-receipt' -and $builderReceipt.scope -ceq 'RECENT_201_BUILDER_ONLY' -and $builderReceipt.status -ceq $builderResult.status -and $builderReceipt.status -cin @('REMOVED','NO_ACTION') -and $builderReceipt.current.release -ceq $Tag -and $builderReceipt.current.commit -ceq $Commit -and $builderReceipt.current.sourceSha256 -ceq $SourceSha256 -and $builderReceipt.identity.instanceId -ceq $instance -and $builderReceipt.identity.machineId -ceq $machine -and $builderReceipt.requestSha256 -ceq $requestSha -and $builderReceipt.planSha256 -ceq $builderPlanned.plan.sha256 -and (@($builderReceipt.removed).Count+@($builderReceipt.alreadyAbsent).Count) -eq 1 -and @($builderReceipt.removed).Count -eq $builderResult.removedBuilders -and @($builderReceipt.alreadyAbsent).Count -eq $builderResult.alreadyAbsent -and @($builderReceipt.retiredMysqlObjects).Count -eq $builderResult.retiredMysqlObjects -and @($builderReceipt.skipped).Count -eq 0 -and $builderReceipt.mysqlDataDirectoriesPreserved -and $builderReceipt.imagesPreserved -and $builderReceipt.volumesPreserved -and $builderReceipt.directoriesPreserved -and -not $builderReceipt.jarDeletionPerformed) 'Collected recent builder retirement lacks exact source, host, plan, counts or preserved-data proof.'
    $fixtureReceipt=Get-Content -LiteralPath (Join-Path $workspace 'artifacts/native-jar-duplicate-fixture-object-receipt.json') -Raw -Encoding utf8 | ConvertFrom-Json -Depth 24
    foreach($flag in @('dataDirectoriesPreserved','imagesPreserved','volumesPreserved','sourceArchivesAndReportsPreserved','jarDeletionPerformed')) {Require-NativeJar ($fixtureReceipt.$flag -is [bool]) 'Collected fixture receipt omitted a strict preservation boolean.'}
    Require-NativeJar ($fixtureReceipt.kind -ceq 'doorhandle-recent-mysql-fixture-object-receipt' -and $fixtureReceipt.status -cin @('REMOVED','NO_ACTION') -and $fixtureReceipt.current.release -ceq $Tag -and $fixtureReceipt.current.commit -ceq $Commit -and $fixtureReceipt.current.sourceSha256 -ceq $SourceSha256 -and $fixtureReceipt.identity.instanceId -ceq $instance -and $fixtureReceipt.identity.machineId -ceq $machine -and $fixtureReceipt.requestSha256 -ceq $requestSha -and $fixtureReceipt.planSha256 -ceq $fixturePlanned.plan.sha256 -and (@($fixtureReceipt.removed).Count+@($fixtureReceipt.alreadyAbsent).Count) -eq 3 -and $fixtureReceipt.dataDirectoriesPreserved -eq $true -and $fixtureReceipt.imagesPreserved -eq $true -and $fixtureReceipt.volumesPreserved -eq $true -and $fixtureReceipt.sourceArchivesAndReportsPreserved -eq $true -and $fixtureReceipt.jarDeletionPerformed -eq $false) 'Collected fixture object retirement lacks exact source, host, plan or preserved-data proof.'
    $canonicalReceipt=Get-Content -LiteralPath $canonicalReceiptFile -Raw -Encoding utf8 | ConvertFrom-Json -Depth 24
    Require-NativeJar ($canonicalReceipt.kind -ceq 'doorhandle-failed-native-canonical-jar-retirement-receipt' -and $canonicalReceipt.status -cin @('REMOVED','NO_ACTION') -and $canonicalReceipt.current.release -ceq $Tag -and $canonicalReceipt.current.commit -ceq $Commit -and $canonicalReceipt.current.sourceSha256 -ceq $SourceSha256 -and $canonicalReceipt.identity.instanceId -ceq $instance -and $canonicalReceipt.identity.machineId -ceq $machine -and $canonicalReceipt.requestSha256 -ceq $requestSha -and $canonicalReceipt.planSha256 -ceq $canonicalPlanned.plan.sha256 -and $canonicalReceipt.sourceArchivesDataAndReportsHaveNoDeletionApi -is [bool] -and $canonicalReceipt.sourceArchivesDataAndReportsHaveNoDeletionApi -and $canonicalReceipt.binaryRebuildByteIdentityClaimed -is [bool] -and -not $canonicalReceipt.binaryRebuildByteIdentityClaimed -and $canonicalReceipt.testsRunByRetirement -is [bool] -and -not $canonicalReceipt.testsRunByRetirement -and (($canonicalReceipt.status -ceq 'REMOVED' -and $canonicalReceipt.binaryDisposition -ceq 'RETIRED') -or ($canonicalReceipt.status -ceq 'NO_ACTION' -and $canonicalReceipt.binaryDisposition -ceq 'UNCHANGED'))) 'Recent canonical JAR retirement lacks matching source, host, plan or explicit binary disposition.'
    $summary=[ordered]@{schemaVersion=1;kind='doorhandle-failed-native-canonical-jar-ci';scope='RECENT_CANONICAL_ONLY';current=$spec.current;identity=$spec.identity;status=$canonicalReceipt.status;requestSha256=$requestSha;planSha256=$canonicalPlanned.plan.sha256;deletedFiles=@($canonicalReceipt.deleted).Count;candidateAllocatedBytes=$canonicalPlanned.candidateAllocatedBytes;localControlCustody=$local.custody;localSkipped=$local.skipped;captureSkipped=$captured.skipped;planSkipped=$canonicalPlanned.skipped;binaryDisposition=$canonicalReceipt.binaryDisposition;binaryRebuildByteIdentityClaimed=$false;sourceArchivesDataAndReportsHaveNoDeletionApi=$true;imagesPreserved=$true;volumesPreserved=$true;testsRunByRetirement=$false}
    $summary.builderStatus=$builderReceipt.status
    $summary.retiredBuilders=@($builderReceipt.removed).Count
    $summary.builderAlreadyAbsent=@($builderReceipt.alreadyAbsent).Count
    $summary.retiredMysqlObjects=@($builderReceipt.retiredMysqlObjects).Count
    $summary.mysqlDataDirectoriesPreserved=$builderReceipt.mysqlDataDirectoriesPreserved
    $summary.builderPlanSha256=$builderPlanned.plan.sha256
    $summary.builderSkipped=$builderReceipt.skipped
    $summary.fixtureObjectStatus=$fixtureReceipt.status
    $summary.retiredFixtureContainers=@($fixtureReceipt.removed).Count
    $summary.fixtureDataDirectoriesPreserved=$fixtureReceipt.dataDirectoriesPreserved
    $summary|ConvertTo-Json -Depth 20|Set-Content -LiteralPath (Join-Path $workspace 'artifacts/native-jar-duplicate-ci.json') -Encoding utf8
    Write-Output ($summary|ConvertTo-Json -Depth 8 -Compress)
    return
}
$builderPlanned=Invoke-NativeJarPhase 'plan-builders' "--request-sha256 '$requestSha'"
Require-NativeJar ($builderPlanned.status -ceq 'PLANNED' -and $builderPlanned.plan.sha256 -cmatch '^[a-f0-9]{64}$') 'No exact historical builder retirement plan was produced.'
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
$canonicalRequested=$Mode -ceq 'Maintenance'; $canonicalFailed=$false; $canonicalPlanned=$null
if ($canonicalRequested -and -not $applyFailed -and -not $publicLayerFailed -and -not $generatedArchiveFailed -and -not $pythonCacheFailed) {
    try {
        $canonicalPlanned=Invoke-NativeJarPhase 'plan-canonical' "--request-sha256 '$requestSha'"
        Require-NativeJar ($canonicalPlanned.status -ceq 'PLANNED' -and $canonicalPlanned.plan.sha256 -cmatch '^[a-f0-9]{64}$') 'No exact failed canonical JAR retirement plan was produced.'
        $canonicalResult=Invoke-NativeJarPhase 'apply-canonical' "--request-sha256 '$requestSha' --plan-sha256 '$($canonicalPlanned.plan.sha256)'"
    } catch {$canonicalFailed=$true}
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
$canonicalReceipt=$null
if ($canonicalRequested) {
    $canonicalReceiptFile=Join-Path $workspace 'artifacts/native-jar-duplicate-canonical-receipt.json'
    Require-NativeJar (-not $canonicalFailed -and $null -ne $canonicalPlanned -and (Test-Path -LiteralPath $canonicalReceiptFile -PathType Leaf)) 'Failed canonical JAR retirement failed or is unknown; original controls were collected.'
    $canonicalReceipt=Get-Content -LiteralPath $canonicalReceiptFile -Raw -Encoding utf8 | ConvertFrom-Json -Depth 24
    Require-NativeJar ($canonicalReceipt.kind -ceq 'doorhandle-failed-native-canonical-jar-retirement-receipt' -and $canonicalReceipt.status -cin @('REMOVED','NO_ACTION') -and $canonicalReceipt.current.release -ceq $Tag -and $canonicalReceipt.current.commit -ceq $Commit -and $canonicalReceipt.current.sourceSha256 -ceq $SourceSha256 -and $canonicalReceipt.identity.instanceId -ceq $instance -and $canonicalReceipt.identity.machineId -ceq $machine -and $canonicalReceipt.requestSha256 -ceq $requestSha -and $canonicalReceipt.planSha256 -ceq $canonicalPlanned.plan.sha256 -and $canonicalReceipt.sourceArchivesDataAndReportsHaveNoDeletionApi -is [bool] -and $canonicalReceipt.sourceArchivesDataAndReportsHaveNoDeletionApi -and $canonicalReceipt.binaryRebuildByteIdentityClaimed -is [bool] -and -not $canonicalReceipt.binaryRebuildByteIdentityClaimed -and $canonicalReceipt.testsRunByRetirement -is [bool] -and -not $canonicalReceipt.testsRunByRetirement -and (($canonicalReceipt.status -ceq 'REMOVED' -and $canonicalReceipt.binaryDisposition -ceq 'RETIRED') -or ($canonicalReceipt.status -ceq 'NO_ACTION' -and $canonicalReceipt.binaryDisposition -ceq 'UNCHANGED'))) 'Canonical JAR retirement lacks matching source, host, plan or explicit retired-binary disposition.'
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
if ($null -ne $canonicalReceipt) {
    $summary.canonicalJarStatus=$canonicalReceipt.status
    $summary.canonicalJarRetiredFiles=@($canonicalReceipt.deleted).Count
    $summary.canonicalJarRetiredBytes=[long]0
    $summary.canonicalJarRetiredAllocatedBytes=[long]0
    foreach ($retiredJar in @($canonicalReceipt.deleted)) {
        $summary.canonicalJarRetiredBytes += [long]$retiredJar.bytes
        $summary.canonicalJarRetiredAllocatedBytes += [long]$retiredJar.allocatedBytes
    }
    $summary.canonicalJarPlanSha256=$canonicalPlanned.plan.sha256
    $summary.canonicalJarSkipped=$canonicalReceipt.skipped
    $summary.canonicalJarBinaryDisposition=$canonicalReceipt.binaryDisposition
    $summary.binaryRebuildByteIdentityClaimed=$false
    $summary.inboxKeepersPreserved=$canonicalReceipt.inboxKeepersPreserved
    $summary.availableBytesAfter=$canonicalReceipt.availableBytesAfter
    if ($canonicalReceipt.status -ceq 'REMOVED') {$summary.status='REMOVED'}
}
$summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $workspace 'artifacts/native-jar-duplicate-ci.json') -Encoding utf8
Write-Output ($summary | ConvertTo-Json -Depth 12 -Compress)
