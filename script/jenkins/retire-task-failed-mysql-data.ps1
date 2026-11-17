param(
    [Parameter(Mandatory=$true)][string[]]$SshOptions,
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][string]$PortText,
    [Parameter(Mandatory=$true)][string]$RemoteRoot,
    [Parameter(Mandatory=$true)][string]$Tag,
    [Parameter(Mandatory=$true)][string]$Commit,
    [Parameter(Mandatory=$true)][string]$SourceSha256,
    [Parameter(Mandatory=$true)][string]$PinnedHelper,
    [Parameter(Mandatory=$true)][string]$FailedBuildNumbers
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$finishedManifest=[Environment]::GetEnvironmentVariable('CI_FINISHED_OUTPUTS_MANIFEST')
$finished=-not [string]::IsNullOrWhiteSpace($finishedManifest)
$task=if($finished){'01a1de46-3b28-7a21-84e7-4f403268fa01'}else{'01a1a46b-d37a-7fb2-8638-afe345c73531'}
$batch=if($finished){'manifest-pre-runtime-outputs-v1'}else{'current-task-failed-verify-mysql-v1'}
function Require-TaskData([bool]$Value,[string]$Message) {if(-not $Value){throw $Message}}
function Assert-TaskControlPath([string]$Path){
    $item=Get-Item -LiteralPath $Path -Force
    while($null -ne $item){
        Require-TaskData (-not($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Task controls cannot follow links or junctions.'
        $item=if($item -is [IO.FileInfo]){$item.Directory}else{$item.Parent}
    }
}
Require-TaskData ($env:ACTION -ceq 'reclaim-build-outputs' -and $env:NATIVE_RETENTION_POLICY -ceq 'FailedNative' -and
    $env:DOORHANDLE_CI_SCOPE -ceq 'source' -and $env:CI_ECS_VERIFIED -ceq 'false' -and $env:PRODUCTION_RELEASE_ENABLED -cne 'true' -and
    ($finished -or $env:DOORHANDLE_FAILED_MYSQL_DATA_TASK_ID -ceq $task) -and
    $RemoteRoot -ceq '/home/ecs-user/doorhandle-ci' -and $env:DOORHANDLE_ECS_INSTANCE_ID -ceq 'i-2zeieuov2aum486jm1ek' -and
    $env:DOORHANDLE_ECS_MACHINE_ID -ceq '1ebe8f77e3104ab6a49a9386e38abd20' -and $Tag -cmatch '\Aci-[1-9][0-9]*-[a-f0-9]{12}\z' -and
    $Commit -cmatch '\A[a-f0-9]{40}\z' -and $Tag.EndsWith('-'+$Commit.Substring(0,12)) -and $SourceSha256 -cmatch '\A[a-f0-9]{64}\z' -and
    $Destination -cmatch '\A[a-z_][a-z0-9_-]*@[A-Za-z0-9.-]+\z' -and $PortText -cmatch '\A[0-9]{1,5}\z' -and
    $SshOptions -ccontains 'StrictHostKeyChecking=yes' -and $SshOptions -ccontains 'HostKeyAlias=doorhandle-bj') 'The current-task data path requires explicit fixed source-only FailedNative maintenance on the original ECS.'
Require-TaskData ($FailedBuildNumbers -cmatch '\A[1-9][0-9]{0,8}(,[1-9][0-9]{0,8}){0,15}\z') 'Select one bounded explicit failed-build list.'
$numbers=@($FailedBuildNumbers.Split(','))
Require-TaskData (@($numbers | Select-Object -Unique).Count -eq $numbers.Count -and
    @($numbers | Where-Object {[long]$_ -lt 287 -or [long]$_ -ge [long]($Tag.Split('-')[1])}).Count -eq 0) 'Only distinct earlier failed verification builds from this task may be selected.'
$authorizationPath='D:/AI/lunwen1/DoorHandleCatch/work/jenkins/data-residency-20261107/failed-test-fixture-retention-authorization-20261113.json'
if($finished){$authorizationPath='D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/cleanup-authorization-20261115.json'}
function Read-TaskDataAuthorization {
    Assert-TaskControlPath $authorizationPath
    $item=Get-Item -LiteralPath $authorizationPath
    Require-TaskData (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -and $item.Length -gt 0 -and $item.Length -le 65536) 'The original task authorization must be a small regular private record.'
    $authorization=Get-Content -LiteralPath $authorizationPath -Raw -Encoding utf8|ConvertFrom-Json
    $fields=@($authorization.PSObject.Properties.Name)
    if($finished){
        Require-TaskData ($authorization.kind -ceq 'doorhandle-ci-regenerable-cleanup-user-authorization' -and $authorization.version -eq 1 -and
            $authorization.taskThreadId -ceq $task -and $authorization.approved -eq $true -and
            $authorization.job -ceq 'doorhandle-java' -and $authorization.branch -ceq 'java-cloud' -and
            $authorization.instanceId -ceq $env:DOORHANDLE_ECS_INSTANCE_ID -and $authorization.machineId -ceq $env:DOORHANDLE_ECS_MACHINE_ID -and
            $authorization.remoteRoot -ceq $RemoteRoot -and $authorization.scope -ceq 'historical-finished-ci-outputs' -and
            (@($authorization.acceptedActions|Sort-Object)-join ',') -ceq 'verify,verify-runtime' -and
            $authorization.requiresExactManifest -eq $true -and $authorization.requiresFinishedBuild -eq $true -and
            $authorization.requiresPreservedOriginals -eq $true -and $authorization.requiresNoActiveReferences -eq $true -and
            $authorization.allowsArbitraryPath -eq $false -and $authorization.allowsGlobalDockerPrune -eq $false -and
            $authorization.allowsDiskExpansion -eq $false -and $authorization.allowsManualDeletionOutsideJenkins -eq $false -and
            $authorization.classes -ccontains 'duplicate-unpublished-application-jars' -and $authorization.classes -ccontains 'isolated-derived-test-mysql-data' -and
            @(@('business-data-and-services','original-sql-and-snapshots','source-originals','original-reports','ci-266-recovery-point','ci-117-pinned-layer-source','current-shared-dependencies','active-or-pending-candidates')|Where-Object{$authorization.protected -cnotcontains $_}).Count -eq 0 -and
            (-not($fields -ccontains 'revoked') -or $authorization.revoked -ne $true)) 'Independent finished-output authorization is absent or differs.'
        return (Get-FileHash -LiteralPath $authorizationPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    Require-TaskData ($authorization.schemaVersion -eq 1 -and $authorization.kind -ceq 'doorhandle-current-task-failed-verify-mysql-data-retirement-authorization' -and
        $authorization.source -ceq 'USER_EXPLICIT_QUESTION_REPLY' -and $authorization.taskThreadId -ceq $task -and
        $authorization.branch -ceq 'java-cloud' -and $authorization.job -ceq 'doorhandle-java' -and
        $authorization.instanceId -ceq $env:DOORHANDLE_ECS_INSTANCE_ID -and $authorization.scope -ceq 'mysql' -and
        @($authorization.acceptedActions).Count -eq 1 -and $authorization.acceptedActions[0] -ceq 'verify' -and
        (@($authorization.acceptedTerminalResults|Sort-Object)-join ',') -ceq 'ABORTED,FAILURE' -and
        $authorization.alwaysPreserve -ccontains 'BUILD_266_RECOVERY_POINT' -and $authorization.alwaysPreserve -ccontains 'PENDING_RELEASE_CANDIDATES' -and
        $authorization.followUpFailedVerifyMysqlBuildsInThisTask -eq $true -and $authorization.authorizationEndsWhenThisTaskCompletes -eq $true -and
        $authorization.allowArbitraryPath -eq $false -and $authorization.allowDiskExpansion -eq $false -and
        (-not($fields -ccontains 'completed') -or $authorization.completed -ne $true) -and
        (-not($fields -ccontains 'revoked') -or $authorization.revoked -ne $true)) 'The original user authorization is absent, expired or outside this task.'
    return (Get-FileHash -LiteralPath $authorizationPath -Algorithm SHA256).Hash.ToLowerInvariant()
}
$authorizationSha=Read-TaskDataAuthorization
$identity=@{instanceId=$env:DOORHANDLE_ECS_INSTANCE_ID;machineId=$env:DOORHANDLE_ECS_MACHINE_ID;executionLocation='ECS'}
$request=[ordered]@{schemaVersion=1;kind='doorhandle-authorized-failed-mysql-data-request';current=@{release=$Tag;commit=$Commit;sourceSha256=$SourceSha256};identity=$identity;
    authorization=@{taskThreadId=$task;sourceSha256=$authorizationSha;endsWithTask=$true;allowArbitraryPath=$false};builds=$numbers;candidates=@()}
$uploads=@();$originalCustody=@()
$expectedNewJarCount=0
$names=@{buildXml='build.xml';release='release.json';localBuild='local-build.json';fixtureCleanupPublic='fixture-cleanup.json'}
$workspaceCustodyValidator=@'
import hashlib,json,os,re,stat,sys,xml.etree.ElementTree as ET
from pathlib import Path,PurePosixPath

ORIGIN='PRESERVED_JENKINS_TERMINAL_WORKSPACE_ORIGINAL'
CONTROL_NAMES={'release':'release.json','localBuild':'local-build.json',
    'fixtureCleanupPublic':'fixture-cleanup.json','preparation':'ecs-tool-preparation.json',
    'transport':'candidate-build-tools-transport.json'}

def native_path(path):
    # Full Java report names exceed Win32 MAX_PATH; preserve canonical recorded
    # names while using the equivalent extended path for local file access.
    return Path('\\\\?\\'+str(path)) if os.name=='nt' and not str(path).startswith('\\\\?\\') else path

def need(value,message):
    if not value: raise ValueError(message)

def regular(path,limit):
    path=native_path(path)
    for parent in (path,*path.parents):
        info=parent.lstat()
        need(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,
             'Workspace custody cannot follow links or junctions')
    before=path.stat()
    need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<=before.st_size<=limit,
         'Bounded single-link custody original required')
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''): digest.update(block)
    after=path.stat()
    fields=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_nlink)
    need(fields(before)==fields(after),'Custody original changed while reading')
    return before.st_size,digest.hexdigest()

def document(path,limit=2*1024**2):
    regular(path,limit)
    return json.loads(native_path(path).read_text(encoding='utf-8-sig'))

def validate_workspace_custody(candidate,custody_root,workspace_root):
    match=re.fullmatch(r'ci-([1-9][0-9]*)-([a-f0-9]{12})',candidate['release'])
    need(match and re.fullmatch(r'[a-f0-9]{40}',candidate['commit'])
         and candidate['commit'].startswith(match[2]),'Canonical workspace build required')
    number=int(match[1]); folder=custody_root/('ci-'+str(number)+'-raw-receipts')
    supplement=folder/'workspace-originals'; catalog_path=supplement/'preservation.json'
    binding=candidate['workspaceCustody']
    need(set(binding)=={'origin','catalogBytes','catalogSha256'} and binding['origin']==ORIGIN,
         'Explicit original workspace custody binding required')
    need(regular(catalog_path,2*1024**2)==(binding['catalogBytes'],binding['catalogSha256']),
         'Workspace preservation catalog changed')
    original=document(folder/'preservation.json'); catalog=document(catalog_path)
    context={key:candidate[key] for key in ('release','commit','sourceSha256')}
    need(original.get('build')==number and original.get('commit')==candidate['commit']
         and original.get('result')=='ABORTED' and original.get('completed') is True
         and original.get('executionDone') is True and original.get('status')=='PRESERVED'
         and catalog.get('build')==number and catalog.get('officialResult')=='ABORTED'
         and catalog.get('status')=='PRESERVED'
         and all(catalog.get(key)==value for key,value in context.items()),
         'Only preserved terminal cancelled workspace originals are admitted')
    xml_path=folder/'build.xml'; xml_bytes,xml_sha=regular(xml_path,2*1024**2)
    need(original.get('buildXmlSha256')==xml_sha and original.get('buildXml',{}).get('bytes')==xml_bytes,
         'Official terminal build XML changed')
    xml=native_path(xml_path).read_bytes()
    need(b'<!DOCTYPE' not in xml.upper() and b'<!ENTITY' not in xml.upper(),'Entity-free build XML required')
    build=ET.fromstring(xml.replace(b'version="1.1"',b'version="1.0"',1))
    params={item.findtext('name'):item.findtext('value') for item in
            build.findall('./actions/hudson.model.ParametersAction/parameters/*')}
    scm=[item.find('hudson.plugins.git.util.Build') for item in build.findall('.//buildsByBranchName/entry')
         if item.findtext('string')=='refs/remotes/origin/java-cloud']
    need(build.tag=='flow-build' and build.findtext('result')=='ABORTED'
         and build.findtext('completed')=='true' and build.findtext('execution/done')=='true'
         and params.get('ACTION') in ('verify','verify-runtime') and params.get('DOORHANDLE_CI_SCOPE')=='mysql'
         and params.get('TRUSTED_COMMIT')==candidate['commit'] and params.get('PRODUCTION_RELEASE_ENABLED')=='false'
         and len(scm)==1 and scm[0] is not None and scm[0].findtext('hudsonBuildNumber')==str(number)
         and scm[0].findtext('marked/sha1')==candidate['commit']
         and (scm[0].findtext('revision/sha1')==candidate['commit']
              or (scm[0].find('revision') is not None and scm[0].find('revision').get('reference')=='../marked')),
         'Official cancelled build/source identity differs')
    entries=catalog.get('files')
    need(type(entries) is list and 0<len(entries)<=4096,'Complete bounded workspace catalog required')
    files={}; total=0
    for entry in entries:
        name=entry.get('path'); pure=PurePosixPath(name) if isinstance(name,str) else None
        need(pure and pure.as_posix()==name and not pure.is_absolute() and
             all(part not in ('','.','..') for part in pure.parts) and '\\' not in name and ':' not in name
             and name!='preservation.json' and name not in files,'Unsafe or duplicate workspace member')
        expected=supplement.joinpath(*pure.parts); source=workspace_root.joinpath(*pure.parts)
        need(entry.get('preserved','').replace('\\','/')==expected.as_posix()
             and entry.get('original','').replace('\\','/')==source.as_posix()
             and entry.get('copyByteComparison')=='IDENTICAL'
             and type(entry.get('bytes')) is int and re.fullmatch(r'[a-f0-9]{64}',entry.get('sha256','')),
             'Workspace original provenance differs')
        need(regular(expected,512*1024**2)==(entry['bytes'],entry['sha256']),
             'Preserved workspace member changed or is partial')
        files[name]=entry; total+=entry['bytes']
        need(total<=1024**3,'Workspace catalog exceeds its complete-artifact bound')
    actual=set()
    actual_root=native_path(supplement)
    for directory,dirs,names in os.walk(actual_root,followlinks=False):
        for name in dirs:
            info=(Path(directory)/name).lstat()
            need(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                 and not getattr(info,'st_file_attributes',0)&0x400,'Unknown workspace directory link')
        actual.update((Path(directory)/name).relative_to(actual_root).as_posix() for name in names)
    need(actual==set(files)|{'preservation.json'} and catalog.get('copiedFiles')==len(files)
         and catalog.get('copiedBytes')==total,'Workspace catalog is incomplete')
    required=set(CONTROL_NAMES.values())|{'application.jar','source.tar.gz','ecs/evidence/verification-receipt.json'}
    need(required<=set(files),'Complete workspace controls and full binary/source originals required')
    release=document(supplement/'release.json'); local=document(supplement/'local-build.json')
    need(all(release.get(key)==value for key,value in context.items())
         and local.get('release')==context['release'] and local.get('commit')==context['commit']
         and local.get('testsExecuted') is False and local.get('status')=='PASS' and local.get('exitCode')==0
         and files['local-build.json']['sha256']==release.get('localBuildReceiptSha256')
         and files['source.tar.gz']['sha256']==context['sourceSha256']
         and files['application.jar']['bytes']==local.get('applicationJarBytes')==candidate['retirement']['jarBytes']
         and files['application.jar']['sha256']==local.get('applicationJarSha256')
             ==release.get('applicationJarSha256')==candidate['retirement']['jarSha256'],
         'Complete original application/source integrity differs')
    receipt=document(supplement/'ecs/evidence/verification-receipt.json')
    need(all(receipt.get(key)==value for key,value in context.items())
         and receipt.get('kind')=='doorhandle-ecs-ci' and receipt.get('schema')==1
         and receipt.get('scope')=='mysql' and receipt.get('status')=='FAILED'
         and type(receipt.get('verificationExitCode')) is int and receipt['verificationExitCode']!=0
         and not receipt.get('evidenceOmissions') and bool(receipt.get('reportFiles')),
         'Complete original remote failure is required; cancellation is not PASS')
    reports=set()
    for item in receipt['reportFiles']:
        name=item.get('path'); key='ecs/evidence/'+str(name)
        need(isinstance(name,str) and name not in reports and key in files
             and item.get('bytes')==files[key]['bytes'] and item.get('sha256')==files[key]['sha256'],
             'Preserved remote report catalog differs')
        reports.add(name)
    need(set(candidate['controls'])=={'buildXml',*CONTROL_NAMES},'Exact original control roles required')
    for role,name in CONTROL_NAMES.items():
        control=candidate['controls'][role]
        need(control.get('origin')==ORIGIN and control.get('source')==(supplement/name).as_posix()
             and control.get('bytes')==files[name]['bytes'] and control.get('sha256')==files[name]['sha256'],
             'Workspace control binding differs')
    return {'origin':ORIGIN,'catalog':catalog_path.as_posix(),'catalogSha256':binding['catalogSha256'],
            'files':len(files),'bytes':total,'completeApplicationJarPreserved':True,**context}

if __name__=='__main__':
    project=Path('D:/AI/lunwen1/DoorHandleCatch')
    candidate=json.load(sys.stdin)
    print(json.dumps(validate_workspace_custody(candidate,
        project/'work/jenkins/data-residency-20261107',project/'work/jenkins/ci-workspaces/monolith/artifacts')))
'@
if($finished){
    Require-TaskData ([IO.Path]::IsPathFullyQualified($finishedManifest) -and [string]::IsNullOrEmpty($env:FAILED_NATIVE_BUILD_NUMBER) -and $env:GENERATED_ARTIFACTS_ONLY -cne 'true') 'Finished outputs require a separate exact manifest and no mixed policy.'
    Assert-TaskControlPath $finishedManifest
    $manifestItem=Get-Item -LiteralPath $finishedManifest
    Require-TaskData (-not($manifestItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -and $manifestItem.Length -gt 0 -and $manifestItem.Length -le 262144) 'A small regular exact manifest is required.'
    $manifestSha=(Get-FileHash -LiteralPath $finishedManifest -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest=Get-Content -LiteralPath $finishedManifest -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable
    Require-TaskData ($manifest.schemaVersion -eq 1 -and $manifest.kind -ceq 'doorhandle-finished-ci-outputs-manifest' -and $manifest.taskThreadId -ceq $task -and
        $manifest.authorizationSha256 -ceq $authorizationSha -and $manifest.policy -ceq $batch -and
        (@($manifest.candidates|ForEach-Object{$_.release.Split('-')[1]})-join ',') -ceq $FailedBuildNumbers) 'The manifest must bind this independent authorization and the exact selected builds.'
    $request.kind='doorhandle-authorized-pre-runtime-outputs-request';$request.authorization.manifestSha256=$manifestSha
    foreach($candidate in $manifest.candidates){
        Require-TaskData ($candidate.release -cmatch '\Aci-[1-9][0-9]*-[a-f0-9]{12}\z' -and $candidate.commit -cmatch '\A[a-f0-9]{40}\z' -and
            $candidate.release.EndsWith('-'+$candidate.commit.Substring(0,12)) -and $candidate.sourceSha256 -cmatch '\A[a-f0-9]{64}\z') 'Manifest controls require a canonical fixed historical release.'
        $number=$candidate.release.Split('-')[1];$folder="D:/AI/lunwen1/DoorHandleCatch/work/jenkins/data-residency-20261107/ci-$number-raw-receipts"
        Assert-TaskControlPath "$folder/preservation.json"
        $preservation=Get-Content -LiteralPath "$folder/preservation.json" -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable
        Require-TaskData ($preservation.build -eq [long]$number -and $preservation.commit -ceq $candidate.commit -and $preservation.result -cin @('FAILURE','ABORTED')) 'Preserved terminal build differs from the manifest.'
        $workspaceProof=$null
        if($candidate.ContainsKey('workspaceCustody')){
            $python=if($env:LOCAL_PYTHON_EXE){$env:LOCAL_PYTHON_EXE}else{$env:PYTHON_EXE}
            Require-TaskData ($python -and [IO.Path]::IsPathFullyQualified($python) -and (Test-Path -LiteralPath $python -PathType Leaf)) 'Use the existing configured local Python for custody verification.'
            $proofLines=@($candidate|ConvertTo-Json -Depth 24 -Compress|& $python -I -B -c $workspaceCustodyValidator)
            Require-TaskData ($LASTEXITCODE -eq 0 -and $proofLines.Count -eq 1) 'Complete original cancelled-workspace custody is required.'
            $workspaceProof=$proofLines[0]|ConvertFrom-Json -AsHashtable
        }
        $controls=@{};$custodyFiles=@()
        $roleNames=@{};foreach($key in $names.Keys){$roleNames[$key]=$names[$key]};$roleNames.preparation='ecs-tool-preparation.json';$roleNames.transport='candidate-build-tools-transport.json'
        Require-TaskData ((@($candidate.controls.Keys|Sort-Object)-join ',') -ceq (@($roleNames.Keys|Sort-Object)-join ',')) 'The finished manifest lacks exact original controls.'
        foreach($role in $roleNames.Keys){
            $file=$candidate.controls[$role];$name=$roleNames[$role]
            $expected="$folder/$name";$recovery="D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/ci-$number-fixture-cleanup.json"
            $workspaceControl=$null -ne $workspaceProof -and $role -cne 'buildXml' -and $file.source -ceq "$folder/workspace-originals/$name" -and $file.origin -ceq 'PRESERVED_JENKINS_TERMINAL_WORKSPACE_ORIGINAL'
            Require-TaskData ($workspaceControl -or $file.source -ceq $expected -or ($role -ceq 'fixtureCleanupPublic' -and $file.origin -ceq 'ACTUAL_GUARDED_RECOVERY_PUBLIC_RECEIPT' -and $file.source -ceq $recovery)) 'The original control is outside its fixed custody location.'
            Assert-TaskControlPath $file.source
            $item=Get-Item -LiteralPath $file.source
            Require-TaskData (-not($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -and $item.Length -gt 0 -and $item.Length -le 2MB -and $item.Length -eq $file.bytes -and
                (Get-FileHash -LiteralPath $file.source -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $file.sha256) 'A manifest-bound original control changed.'
            if($file.source -ceq $expected){
                if($role -ceq 'buildXml'){Require-TaskData ($preservation.buildXmlSha256 -ceq $file.sha256) 'Preserved terminal XML changed.'}
                else{
                    $entries=@($preservation.files|Where-Object{$_.path -ceq $name})
                    Require-TaskData ($entries.Count -eq 1 -and $entries[0].bytes -eq $file.bytes -and $entries[0].sha256 -ceq $file.sha256 -and
                        $entries[0].preserved.Replace('\','/') -ceq $expected -and
                        $entries[0].original.Replace('\','/').EndsWith("/jobs/doorhandle-java/builds/$number/archive/artifacts/$name")) 'Preserved Jenkins control provenance differs.'
                }
            }
            $controls[$role]=@{bytes=$file.bytes;sha256=$file.sha256};$uploads+=@{source=$file.source;release=$candidate.release;file=$name;bytes=$file.bytes;sha256=$file.sha256}
            $custodyFiles+=@{role=$role;source=$file.source;origin=$file.origin;bytes=$file.bytes;sha256=$file.sha256}
        }
        if($candidate.retirement.ContainsKey('completedAttempt')){
            Require-TaskData ($manifest.candidates.Count -eq 1 -and $candidate.release -ceq 'ci-383-5400127dd813' -and
                $candidate.retirement.completedAttempt -ceq 'ci-385-74a0f42e52f3') 'Only the registered partial finished-output continuation is admitted.'
            $priorFolder='D:/AI/lunwen1/DoorHandleCatch/work/jenkins/data-residency-20261107/ci-385-raw-receipts'
            Assert-TaskControlPath "$priorFolder/preservation.json"
            $prior=Get-Content -LiteralPath "$priorFolder/preservation.json" -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable
            $priorXml="$priorFolder/build.xml";Assert-TaskControlPath $priorXml
            Require-TaskData ($prior.build -eq 385 -and $prior.commit -ceq '74a0f42e52f3600a93e83c7123ba52f86e90932b' -and
                $prior.result -ceq 'FAILURE' -and $prior.completed -eq $true -and $prior.executionDone -eq $true -and
                $prior.buildXmlSha256 -ceq '5e535bb22a49a295c650fc330743645513e72bd09c89ddebc61e7089540e7747' -and
                (Get-FileHash -LiteralPath $priorXml -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $prior.buildXmlSha256) 'The original failed maintenance terminal evidence changed.'
            $uploads+=@{source=$priorXml;release=$candidate.release;file='completed-maintenance-build.xml';bytes=(Get-Item -LiteralPath $priorXml).Length;sha256=$prior.buildXmlSha256}
            $custodyFiles+=@{role='completedMaintenanceBuild';source=$priorXml;origin='PRESERVED_JENKINS_ORIGINAL';bytes=(Get-Item -LiteralPath $priorXml).Length;sha256=$prior.buildXmlSha256}
        }else{$expectedNewJarCount+=2}
        $request.candidates+=@{release=$candidate.release;commit=$candidate.commit;sourceSha256=$candidate.sourceSha256;controls=$controls;retirement=$candidate.retirement}
        $originalCustody+=@{release=$candidate.release;commit=$candidate.commit;sourceSha256=$candidate.sourceSha256;files=$custodyFiles;preservation="$folder/preservation.json";workspaceOriginals=$workspaceProof}
    }
    foreach($copy in @(@($finishedManifest,'artifacts/derived-mysql-finished-manifest.json',$manifestSha),@($authorizationPath,'artifacts/derived-mysql-user-authorization.json',$authorizationSha))){
        Require-TaskData (-not(Test-Path -LiteralPath $copy[1])) 'Fresh original authorization evidence is required.'
        Copy-Item -LiteralPath $copy[0] -Destination $copy[1]
        Require-TaskData ((Get-FileHash -LiteralPath $copy[1] -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $copy[2]) 'Original authorization evidence changed during preservation.'
    }
}
else{
foreach($number in $numbers){
    # This new entry returns before upload/capture/retirement. The original APIs are unchanged.
    $local=& (Join-Path $PSScriptRoot 'retire-failed-native-jar-duplicates.ps1') -Mode Maintenance -CanonicalBatch FailedNative -CollectDataControls -FailedNativeBuildNumber $number -SshOptions $SshOptions -Destination $Destination -PortText $PortText -RemoteRoot $RemoteRoot -Tag $Tag -Commit $Commit -SourceSha256 $SourceSha256 | ConvertFrom-Json -AsHashtable
    $row=$local.rows[0]
    Require-TaskData ($row.release -cmatch '\Aci-[1-9][0-9]*-[a-f0-9]{12}\z' -and $row.release.Split('-')[1] -ceq $number -and $row.commit -cmatch '\A[a-f0-9]{40}\z' -and $row.release.EndsWith('-'+$row.commit.Substring(0,12))) 'The original failed Jenkins build does not match its canonical tag.'
    $originalCustody+=@{release=$row.release;commit=$row.commit;sourceSha256=$row.sourceSha256;custody=$local.custody;builderFiles=$local.builderFiles}
    $controls=@{}
    foreach($role in $names.Keys){$file=$row.files[$role];Require-TaskData ($file.file -ceq $names[$role]) 'Unknown original task control file.';$controls[$role]=@{bytes=$file.bytes;sha256=$file.sha256};$uploads+=@{source=$file.source;release=$row.release;file=$file.file;bytes=$file.bytes;sha256=$file.sha256}}
    foreach($pair in @(@('preparation','ecs-tool-preparation.json'),@('transport','ecs-tool-preparation-transport.json'))){
        $files=@($local.builderFiles|Where-Object{$_.release -ceq $row.release -and $_.file -ceq $pair[1]})
        Require-TaskData ($files.Count -eq 1) 'Original verify-only preparation and transport are required; runtime candidates are not eligible.'
        $file=$files[0];$controls[$pair[0]]=@{bytes=$file.bytes;sha256=$file.sha256};$uploads+=@{source=$file.source;release=$row.release;file=$file.file;bytes=$file.bytes;sha256=$file.sha256}
    }
    $request.candidates+=@{release=$row.release;commit=$row.commit;sourceSha256=$row.sourceSha256;controls=$controls}
}
}
$remote="$RemoteRoot/inbox/$Tag";$directory="$remote/derived-failed-mysql-retirement";$helper="$remote/retire-derived-mysql-data.py"
foreach($name in @('derived-mysql-request.json','derived-mysql-plan.json','derived-mysql-receipt.json','derived-mysql-controller.json','derived-mysql-original-custody.json')){Require-TaskData (-not(Test-Path -LiteralPath "artifacts/$name")) 'Fresh task-data evidence is required.'}
@{schemaVersion=1;kind='doorhandle-task-data-original-custody';release=$Tag;commit=$Commit;sourceSha256=$SourceSha256;taskThreadId=$task;authorizationSha256=$authorizationSha;candidates=$originalCustody}|ConvertTo-Json -Depth 24|Set-Content -LiteralPath artifacts/derived-mysql-original-custody.json -Encoding utf8
$request|ConvertTo-Json -Depth 16 -Compress|Set-Content -LiteralPath artifacts/derived-mysql-request.json -Encoding utf8
$requestSha=(Get-FileHash -LiteralPath artifacts/derived-mysql-request.json -Algorithm SHA256).Hash.ToLowerInvariant()
$prepare="umask 077; test ! -e '$directory' && test ! -L '$directory' && test ! -e '$helper' && test ! -L '$helper' && mkdir '$directory' && mkdir '$remote/failed-mysql-data-controls'"
& ssh.exe @SshOptions -p $PortText $Destination $prepare
Require-TaskData ($LASTEXITCODE -eq 0) 'Fresh task-data staging is required; do not replay an unknown operation.'
& scp.exe @SshOptions -P $PortText $PinnedHelper "${Destination}:$helper"
Require-TaskData ($LASTEXITCODE -eq 0) 'The fixed task-data helper upload failed.'
& scp.exe @SshOptions -P $PortText artifacts/derived-mysql-request.json "${Destination}:$directory/request.json"
Require-TaskData ($LASTEXITCODE -eq 0) 'The task request upload failed.'
foreach($row in $request.candidates){& ssh.exe @SshOptions -p $PortText $Destination "mkdir '$remote/failed-mysql-data-controls/$($row.release)'";Require-TaskData ($LASTEXITCODE -eq 0) 'Fresh original control staging is required.'}
foreach($upload in $uploads){
    Require-TaskData ((Get-Item -LiteralPath $upload.source).Length -eq $upload.bytes -and (Get-FileHash -LiteralPath $upload.source -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $upload.sha256) 'An original Jenkins control changed before upload.'
    & scp.exe @SshOptions -P $PortText $upload.source "${Destination}:$remote/failed-mysql-data-controls/$($upload.release)/$($upload.file)"
    Require-TaskData ($LASTEXITCODE -eq 0) 'An original task control upload failed.'
    Require-TaskData ((Get-Item -LiteralPath $upload.source).Length -eq $upload.bytes -and (Get-FileHash -LiteralPath $upload.source -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $upload.sha256) 'An original Jenkins control changed during upload.'
}
$binding="--batch '$batch' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --failed-builds '$FailedBuildNumbers' --request-sha256 '$requestSha'"
$plan=$null;$receipt=$null;$attempted=$false;$failure=$null;$failureDiagnostic=$null;$currentPhase='plan';$currentStep='PLAN_REMOTE'
$secondaryFailures=[Collections.Generic.List[object]]::new()
$remoteCalls=[Collections.Generic.List[object]]::new()
$ssh=(Get-Command ssh.exe -CommandType Application -ErrorAction Stop|Select-Object -First 1).Source
function Get-TaskDataControllerDiagnostic([Management.Automation.ErrorRecord]$Record,[string]$Phase,
    [ValidateSet('PLAN_REMOTE','PLAN_EVIDENCE','PLAN_VALIDATE','AUTHORIZATION_RECHECK','APPLY_REMOTE','STATUS_REMOTE','STATUS_VALIDATE')][string]$Step){
    $exceptionType=$Record.Exception.GetType().Name
    if($exceptionType -cnotmatch '\A[A-Za-z][A-Za-z0-9]{0,95}\z'){$exceptionType='ControllerException'}
    $sourceFile=$null;$sourceLine=$null
    if($Record.InvocationInfo.ScriptName -ceq $PSCommandPath -and $Record.InvocationInfo.ScriptLineNumber -gt 0){
        $sourceFile='script/jenkins/retire-task-failed-mysql-data.ps1';$sourceLine=$Record.InvocationInfo.ScriptLineNumber
    }
    # Report only type and fixed source coordinates, never an exception message,
    # command text, arguments, stack trace or an arbitrary local path.
    return @{errorType='ControllerError';reasonCode='CONTROLLER_OPERATION_FAILED';phase=$Phase;step=$Step;
        exceptionType=$exceptionType;sourceFile=$sourceFile;sourceLine=$sourceLine}
}
function Get-TaskDataRemoteDiagnostic([string]$Phase,[int]$ExitCode,[string]$StderrPath){
    if($ExitCode -eq 0){return $null}
    $fallback=@{errorType='RemoteProcessError';reasonCode=$(if($ExitCode -eq 255){'SSH_TRANSPORT_LOST'}else{'REMOTE_PROCESS_FAILED'});phase=$Phase}
    try{
        if((Get-Item -LiteralPath $StderrPath).Length -gt 1048576){return $fallback}
        $text=[IO.File]::ReadAllText($StderrPath,[Text.UTF8Encoding]::new($false,$true))
        $lines=@($text -split '\r?\n'|Where-Object{-not [string]::IsNullOrWhiteSpace($_)})
        if($lines.Count -eq 0){return $fallback}
        $value=$lines[-1]|ConvertFrom-Json -AsHashtable
        if($value -isnot [Collections.IDictionary] -or $value.status -cne 'FAILED_OR_UNKNOWN' -or $value.phase -cne $Phase -or
            $value.errorType -isnot [string] -or $value.errorType -cnotmatch '\A[A-Za-z][A-Za-z0-9]{0,63}\z' -or
            $value.reasonCode -isnot [string] -or $value.reasonCode -cnotmatch '\A[A-Z][A-Z0-9_]{1,160}\z'){return $fallback}
        # Only the pinned helper's fixed diagnostic fields reach the public
        # controller receipt. Raw messages/paths remain in the original streams.
        return @{errorType=$value.errorType;reasonCode=$value.reasonCode;phase=$Phase}
    }catch{return $fallback}
}
function Invoke-TaskDataRemote([ValidateSet('plan','apply','status')][string]$Phase,[string]$Command){
    $attempt=1+@($remoteCalls|Where-Object{$_.phase -ceq $Phase}).Count
    $stem='artifacts/derived-mysql-{0}-{1:D2}' -f $Phase,$attempt
    $row=[ordered]@{phase=$Phase;attempt=$attempt;exitCode=$null;stdout="$stem.stdout.txt";stderr="$stem.stderr.txt";diagnostic=$null}
    [void]$remoteCalls.Add($row)
    $output=$null;$errorOutput=$null;$process=[Diagnostics.Process]::new()
    try{
        # CreateNew prevents overwriting earlier evidence or replaying a phase.
        $output=[IO.File]::Open([IO.Path]::GetFullPath($row.stdout),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        $errorOutput=[IO.File]::Open([IO.Path]::GetFullPath($row.stderr),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        $process.StartInfo.FileName=$ssh;$process.StartInfo.UseShellExecute=$false;$process.StartInfo.CreateNoWindow=$true
        $process.StartInfo.RedirectStandardOutput=$true;$process.StartInfo.RedirectStandardError=$true
        foreach($argument in @($SshOptions)+@('-p',$PortText,$Destination,$Command)){[void]$process.StartInfo.ArgumentList.Add($argument)}
        Require-TaskData ($process.Start()) 'The task-data SSH process did not start.'
        $stdoutCopy=$process.StandardOutput.BaseStream.CopyToAsync($output)
        $stderrCopy=$process.StandardError.BaseStream.CopyToAsync($errorOutput)
        $process.WaitForExit()
        # PowerShell can expose Task<VoidTaskResult>'s internal result. Keep both
        # waits exception-propagating but keep the success stream to one row.
        [void]$stdoutCopy.GetAwaiter().GetResult();[void]$stderrCopy.GetAwaiter().GetResult()
        $row.exitCode=$process.ExitCode
    }finally{
        if($null -ne $output){$output.Dispose()};if($null -ne $errorOutput){$errorOutput.Dispose()};$process.Dispose()
    }
    $row.diagnostic=Get-TaskDataRemoteDiagnostic $Phase $row.exitCode $row.stderr
    return $row
}
function Copy-TaskDataEvidence([string]$Name,[string]$Local){
    $null=& scp.exe @SshOptions -P $PortText "${Destination}:$directory/$Name" $Local
    if($LASTEXITCODE -ne 0){return $null}
    Require-TaskData ((Get-Item -LiteralPath $Local).Length -le 2097152) 'Task data evidence exceeds its bound.'
    $value=Get-Content -LiteralPath $Local -Raw|ConvertFrom-Json
    Require-TaskData ($value.batch -ceq $batch -and $value.release -ceq $Tag -and $value.commit -ceq $Commit -and $value.sourceSha256 -ceq $SourceSha256 -and $value.requestSha256 -ceq $requestSha -and $value.taskThreadId -ceq $task -and $value.identity.instanceId -ceq $identity.instanceId -and $value.identity.machineId -ceq $identity.machineId -and $value.sourceSqlAndReportsRetained -eq $true) 'Task data evidence differs from this exact authorized source and host.'
    return $value
}
try {
    $privateFiles=@("'$helper'","'$directory/request.json'") + @($uploads|ForEach-Object {"'$remote/failed-mysql-data-controls/$($_.release)/$($_.file)'"})
    $planned=Invoke-TaskDataRemote 'plan' ("chmod 600 " + ($privateFiles -join ' ') + " && python3 -I -B '$helper' plan $binding")
    if($planned.exitCode -ne 0){$failureDiagnostic=$planned.diagnostic}
    Require-TaskData ($planned.exitCode -eq 0) 'Task data planning failed; no apply was issued.'
    $currentStep='PLAN_EVIDENCE'
    $plan=Copy-TaskDataEvidence 'plan.json' 'artifacts/derived-mysql-plan.json'
    $currentStep='PLAN_VALIDATE'
    Require-TaskData ($null -ne $plan -and @($plan.targets).Count -eq $numbers.Count -and $plan.planSha256 -cmatch '\A[a-f0-9]{64}\z') 'The first administrator metadata plan is incomplete.'
    $currentStep='AUTHORIZATION_RECHECK'
    Require-TaskData ((Read-TaskDataAuthorization) -ceq $authorizationSha) 'Task authorization changed after metadata planning; retain all data.'
    if($finished){Require-TaskData ((Get-FileHash -LiteralPath $finishedManifest -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $manifestSha -and @($plan.jarTargets).Count -eq $expectedNewJarCount) 'Exact finished-output manifest or binary plan changed.'}
    $attempted=$true
    $currentPhase='apply';$currentStep='APPLY_REMOTE'
    $applied=Invoke-TaskDataRemote 'apply' "python3 -I -B '$helper' apply $binding --plan-sha256 '$($plan.planSha256)'"
    $applyExit=$applied.exitCode
    if($applyExit -eq 255){
        $state=$null;$currentPhase='status';$lastObservationFailure=$null
        for($i=0;$i -lt 30;$i++){
            $currentStep='STATUS_REMOTE'
            $observed=Invoke-TaskDataRemote 'status' "python3 -I -B '$helper' status $binding"
            if($observed.exitCode -eq 0){
                $currentStep='STATUS_VALIDATE'
                $lines=@(Get-Content -LiteralPath $observed.stdout -Encoding utf8)
                $state=$lines[-1]|ConvertFrom-Json
                Require-TaskData ($state.release -ceq $Tag -and $state.commit -ceq $Commit -and $state.sourceSha256 -ceq $SourceSha256 -and $state.requestSha256 -ceq $requestSha -and $state.taskThreadId -ceq $task) 'Original task-data observation binding differs.'
                if($state.terminal -eq $true){break}
            }else{$lastObservationFailure=$observed.diagnostic}
            Start-Sleep -Seconds 5
        }
        if($null -eq $state -or $state.terminal -ne $true -or $state.status -cne 'COMPLETE'){
            $failureDiagnostic=if($null -ne $lastObservationFailure){$lastObservationFailure}else{@{errorType='RemoteProcessError';reasonCode='ORIGINAL_OPERATION_NOT_CONFIRMED_COMPLETE';phase='status'}}
        }
        Require-TaskData ($null -ne $state -and $state.terminal -eq $true -and $state.status -ceq 'COMPLETE') 'Original task-data operation is not confirmed terminal; observe it, never replay apply.'
    }else{
        if($applyExit -ne 0){$failureDiagnostic=$applied.diagnostic}
        Require-TaskData ($applyExit -eq 0) 'Task-data apply failed or is unknown; do not replay it.'
    }
}catch{
    $failure=$_
    if($null -eq $failureDiagnostic){$failureDiagnostic=Get-TaskDataControllerDiagnostic $_ $currentPhase $currentStep}
}finally{
    foreach($evidence in @(@('plan.json','artifacts/derived-mysql-plan.json'),@('receipt.json','artifacts/derived-mysql-receipt.json'))){
        try{
            if($evidence[0] -ceq 'plan.json' -and $null -eq $plan){$plan=Copy-TaskDataEvidence $evidence[0] $evidence[1]}
            elseif($evidence[0] -ceq 'receipt.json' -and $attempted){$receipt=Copy-TaskDataEvidence $evidence[0] $evidence[1]}
            if(($evidence[0] -ceq 'plan.json' -and $null -eq $plan) -or ($evidence[0] -ceq 'receipt.json' -and $attempted -and $null -eq $receipt)){
                $secondaryFailures.Add(@{errorType='ControllerError';reasonCode='EVIDENCE_UNAVAILABLE';phase='evidence';file=$evidence[0]})
            }
        }catch{
            $secondaryFailures.Add(@{errorType='ControllerError';reasonCode='EVIDENCE_COLLECTION_FAILED';phase='evidence';file=$evidence[0]})
        }
    }
    $jarEvidenceComplete=-not $finished
    if($finished -and $attempted){
        try{
            & scp.exe @SshOptions -P $PortText "${Destination}:$directory/jar-journal.jsonl" artifacts/derived-mysql-jar-journal.jsonl
            Require-TaskData ($LASTEXITCODE -eq 0 -and (Get-Item -LiteralPath artifacts/derived-mysql-jar-journal.jsonl).Length -le 2MB) 'Original binary retirement journal is required.'
            $events=@(Get-Content -LiteralPath artifacts/derived-mysql-jar-journal.jsonl -Encoding utf8|ForEach-Object{$_|ConvertFrom-Json})
            $count=$expectedNewJarCount
            Require-TaskData ($events.Count -eq (2*$count+2) -and $events[0].phase -ceq 'STARTED' -and $events[0].planSha256 -ceq $plan.planSha256 -and
                $events[0].requestSha256 -ceq $requestSha -and $events[-1].phase -ceq 'FINISHED' -and $events[-1].deletedFiles -eq $count -and
                @($receipt.jarRetirements).Count -eq $count) 'The binary retirement journal is incomplete.'
            for($index=0;$index -lt $count;$index++){
                Require-TaskData ($events[2*$index+1].phase -ceq 'DELETE_STARTED' -and $events[2*$index+2].phase -ceq 'DELETE_FINISHED' -and
                    $events[2*$index+1].path -ceq $plan.jarTargets[$index].path -and $events[2*$index+2].path -ceq $plan.jarTargets[$index].path -and
                    $receipt.jarRetirements[$index].path -ceq $plan.jarTargets[$index].path) 'The binary deletion paths differ from the exact plan.'
            }
            if($expectedNewJarCount -eq 0){
                Require-TaskData (@($plan.completedBinaryRetirements).Count -eq 1 -and @($receipt.completedBinaryRetirements).Count -eq 1 -and
                    $plan.completedBinaryRetirements[0].completedAttempt -ceq 'ci-385-74a0f42e52f3' -and
                    ($plan.completedBinaryRetirements|ConvertTo-Json -Depth 8 -Compress) -ceq ($receipt.completedBinaryRetirements|ConvertTo-Json -Depth 8 -Compress)) 'The original completed binary retirement proof was not preserved.'
            }
            $jarEvidenceComplete=$true
        }catch{$secondaryFailures.Add(@{errorType='ControllerError';reasonCode='BINARY_RETIREMENT_EVIDENCE_INCOMPLETE';phase='evidence';file='jar-journal.jsonl'})}
    }
    $ok=$null -eq $failure -and $secondaryFailures.Count -eq 0 -and $null -ne $plan -and $null -ne $receipt -and $receipt.status -ceq 'COMPLETE' -and $receipt.planSha256 -ceq $plan.planSha256 -and @($receipt.removed).Count -eq $numbers.Count
    $ok=$ok -and $jarEvidenceComplete
    if(-not $ok -and $null -eq $failureDiagnostic){$failureDiagnostic=@{errorType='ControllerError';reasonCode='ORIGINAL_COMPLETION_EVIDENCE_REQUIRED';phase='evidence'}}
    @{schemaVersion=1;kind='doorhandle-current-task-failed-mysql-data-controller';status=$(if($ok){'COMPLETE'}else{'FAILED_OR_UNKNOWN'});batch=$batch;release=$Tag;commit=$Commit;sourceSha256=$SourceSha256;requestSha256=$requestSha;taskThreadId=$task;authorizationSha256=$authorizationSha;selectedBuilds=$numbers;targetCount=$numbers.Count;applyAttempted=$attempted;sourceSqlAndReportsRetained=$true;existingBusinessDatabaseUntouched=$true;testsExecuted=$false;planCollected=($null -ne $plan);receiptCollected=($null -ne $receipt);failure=$failureDiagnostic;secondaryFailures=@($secondaryFailures.ToArray());remoteCalls=@($remoteCalls.ToArray())}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath artifacts/derived-mysql-controller.json -Encoding utf8
}
if(-not $ok){throw 'Authorized task-data retirement has not completed with original evidence.'}
