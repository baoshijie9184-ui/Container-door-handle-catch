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
$task='01a1a46b-d37a-7fb2-8638-afe345c73531'
function Require-TaskData([bool]$Value,[string]$Message) {if(-not $Value){throw $Message}}
Require-TaskData ($env:ACTION -ceq 'reclaim-build-outputs' -and $env:NATIVE_RETENTION_POLICY -ceq 'FailedNative' -and
    $env:DOORHANDLE_CI_SCOPE -ceq 'source' -and $env:CI_ECS_VERIFIED -ceq 'false' -and $env:PRODUCTION_RELEASE_ENABLED -cne 'true' -and
    $env:DOORHANDLE_FAILED_MYSQL_DATA_TASK_ID -ceq $task -and
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
function Read-TaskDataAuthorization {
    $item=Get-Item -LiteralPath $authorizationPath
    Require-TaskData (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -and $item.Length -gt 0 -and $item.Length -le 65536) 'The original task authorization must be a small regular private record.'
    $authorization=Get-Content -LiteralPath $authorizationPath -Raw -Encoding utf8|ConvertFrom-Json
    $fields=@($authorization.PSObject.Properties.Name)
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
$uploads=@()
$names=@{buildXml='build.xml';release='release.json';localBuild='local-build.json';fixtureCleanupPublic='fixture-cleanup.json'}
foreach($number in $numbers){
    # This new entry returns before upload/capture/retirement. The original APIs are unchanged.
    $local=& (Join-Path $PSScriptRoot 'retire-failed-native-jar-duplicates.ps1') -Mode Maintenance -CanonicalBatch FailedNative -CollectDataControls -FailedNativeBuildNumber $number -SshOptions $SshOptions -Destination $Destination -PortText $PortText -RemoteRoot $RemoteRoot -Tag $Tag -Commit $Commit -SourceSha256 $SourceSha256 | ConvertFrom-Json -AsHashtable
    $row=$local.rows[0]
    Require-TaskData ($row.release -cmatch '\Aci-[1-9][0-9]*-[a-f0-9]{12}\z' -and $row.release.Split('-')[1] -ceq $number -and $row.commit -cmatch '\A[a-f0-9]{40}\z' -and $row.release.EndsWith('-'+$row.commit.Substring(0,12))) 'The original failed Jenkins build does not match its canonical tag.'
    $controls=@{}
    foreach($role in $names.Keys){$file=$row.files[$role];Require-TaskData ($file.file -ceq $names[$role]) 'Unknown original task control file.';$controls[$role]=@{bytes=$file.bytes;sha256=$file.sha256};$uploads+=@{source=$file.source;release=$row.release;file=$file.file;bytes=$file.bytes;sha256=$file.sha256}}
    foreach($pair in @(@('preparation','ecs-tool-preparation.json'),@('transport','ecs-tool-preparation-transport.json'))){
        $files=@($local.builderFiles|Where-Object{$_.release -ceq $row.release -and $_.file -ceq $pair[1]})
        Require-TaskData ($files.Count -eq 1) 'Original verify-only preparation and transport are required; runtime candidates are not eligible.'
        $file=$files[0];$controls[$pair[0]]=@{bytes=$file.bytes;sha256=$file.sha256};$uploads+=@{source=$file.source;release=$row.release;file=$file.file;bytes=$file.bytes;sha256=$file.sha256}
    }
    $request.candidates+=@{release=$row.release;commit=$row.commit;sourceSha256=$row.sourceSha256;controls=$controls}
}
$remote="$RemoteRoot/inbox/$Tag";$directory="$remote/derived-failed-mysql-retirement";$helper="$remote/retire-derived-mysql-data.py"
foreach($name in @('derived-mysql-request.json','derived-mysql-plan.json','derived-mysql-receipt.json','derived-mysql-controller.json')){Require-TaskData (-not(Test-Path -LiteralPath "artifacts/$name")) 'Fresh task-data evidence is required.'}
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
$binding="--batch 'current-task-failed-verify-mysql-v1' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --failed-builds '$FailedBuildNumbers' --request-sha256 '$requestSha'"
$plan=$null;$receipt=$null;$attempted=$false;$failure=$null
function Copy-TaskDataEvidence([string]$Name,[string]$Local){
    & scp.exe @SshOptions -P $PortText "${Destination}:$directory/$Name" $Local
    if($LASTEXITCODE -ne 0){return $null}
    Require-TaskData ((Get-Item -LiteralPath $Local).Length -le 2097152) 'Task data evidence exceeds its bound.'
    $value=Get-Content -LiteralPath $Local -Raw|ConvertFrom-Json
    Require-TaskData ($value.batch -ceq 'current-task-failed-verify-mysql-v1' -and $value.release -ceq $Tag -and $value.commit -ceq $Commit -and $value.sourceSha256 -ceq $SourceSha256 -and $value.requestSha256 -ceq $requestSha -and $value.taskThreadId -ceq $task -and $value.identity.instanceId -ceq $identity.instanceId -and $value.identity.machineId -ceq $identity.machineId -and $value.sourceSqlAndReportsRetained -eq $true) 'Task data evidence differs from this exact authorized source and host.'
    return $value
}
try {
    $privateFiles=@("'$helper'","'$directory/request.json'") + @($uploads|ForEach-Object {"'$remote/failed-mysql-data-controls/$($_.release)/$($_.file)'"})
    & ssh.exe @SshOptions -p $PortText $Destination ("chmod 600 " + ($privateFiles -join ' ') + " && python3 -I -B '$helper' plan $binding")
    Require-TaskData ($LASTEXITCODE -eq 0) 'Task data planning failed; no apply was issued.'
    $plan=Copy-TaskDataEvidence 'plan.json' 'artifacts/derived-mysql-plan.json'
    Require-TaskData ($null -ne $plan -and @($plan.targets).Count -eq $numbers.Count -and $plan.planSha256 -cmatch '\A[a-f0-9]{64}\z') 'The first administrator metadata plan is incomplete.'
    Require-TaskData ((Read-TaskDataAuthorization) -ceq $authorizationSha) 'Task authorization changed after metadata planning; retain all data.'
    $attempted=$true
    & ssh.exe @SshOptions -p $PortText $Destination "python3 -I -B '$helper' apply $binding --plan-sha256 '$($plan.planSha256)'"
    $applyExit=$LASTEXITCODE
    if($applyExit -eq 255){
        $state=$null
        for($i=0;$i -lt 30;$i++){$lines=@(& ssh.exe @SshOptions -p $PortText $Destination "python3 -I -B '$helper' status $binding");if($LASTEXITCODE -eq 0){$state=$lines[-1]|ConvertFrom-Json;Require-TaskData ($state.release -ceq $Tag -and $state.commit -ceq $Commit -and $state.sourceSha256 -ceq $SourceSha256 -and $state.requestSha256 -ceq $requestSha -and $state.taskThreadId -ceq $task) 'Original task-data observation binding differs.';if($state.terminal -eq $true){break}};Start-Sleep -Seconds 5}
        Require-TaskData ($null -ne $state -and $state.terminal -eq $true -and $state.status -ceq 'COMPLETE') 'Original task-data operation is not confirmed terminal; observe it, never replay apply.'
    }else{Require-TaskData ($applyExit -eq 0) 'Task-data apply failed or is unknown; do not replay it.'}
}catch{$failure=$_}finally{
    try{if($null -eq $plan){$plan=Copy-TaskDataEvidence 'plan.json' 'artifacts/derived-mysql-plan.json'};if($attempted){$receipt=Copy-TaskDataEvidence 'receipt.json' 'artifacts/derived-mysql-receipt.json'}}catch{$failure=$_}
    $ok=$null -eq $failure -and $null -ne $plan -and $null -ne $receipt -and $receipt.status -ceq 'COMPLETE' -and $receipt.planSha256 -ceq $plan.planSha256 -and @($receipt.removed).Count -eq $numbers.Count
    @{schemaVersion=1;kind='doorhandle-current-task-failed-mysql-data-controller';status=$(if($ok){'COMPLETE'}else{'FAILED_OR_UNKNOWN'});batch='current-task-failed-verify-mysql-v1';release=$Tag;commit=$Commit;sourceSha256=$SourceSha256;requestSha256=$requestSha;taskThreadId=$task;authorizationSha256=$authorizationSha;selectedBuilds=$numbers;targetCount=$numbers.Count;applyAttempted=$attempted;sourceSqlAndReportsRetained=$true;existingBusinessDatabaseUntouched=$true;testsExecuted=$false;planCollected=($null -ne $plan);receiptCollected=($null -ne $receipt)}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath artifacts/derived-mysql-controller.json -Encoding utf8
}
if(-not $ok){throw 'Authorized task-data retirement has not completed with original evidence.'}
