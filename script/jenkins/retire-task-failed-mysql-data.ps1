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
$uploads=@();$originalCustody=@()
$names=@{buildXml='build.xml';release='release.json';localBuild='local-build.json';fixtureCleanupPublic='fixture-cleanup.json'}
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
$binding="--batch 'current-task-failed-verify-mysql-v1' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --failed-builds '$FailedBuildNumbers' --request-sha256 '$requestSha'"
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
    Require-TaskData ($value.batch -ceq 'current-task-failed-verify-mysql-v1' -and $value.release -ceq $Tag -and $value.commit -ceq $Commit -and $value.sourceSha256 -ceq $SourceSha256 -and $value.requestSha256 -ceq $requestSha -and $value.taskThreadId -ceq $task -and $value.identity.instanceId -ceq $identity.instanceId -and $value.identity.machineId -ceq $identity.machineId -and $value.sourceSqlAndReportsRetained -eq $true) 'Task data evidence differs from this exact authorized source and host.'
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
    $ok=$null -eq $failure -and $secondaryFailures.Count -eq 0 -and $null -ne $plan -and $null -ne $receipt -and $receipt.status -ceq 'COMPLETE' -and $receipt.planSha256 -ceq $plan.planSha256 -and @($receipt.removed).Count -eq $numbers.Count
    if(-not $ok -and $null -eq $failureDiagnostic){$failureDiagnostic=@{errorType='ControllerError';reasonCode='ORIGINAL_COMPLETION_EVIDENCE_REQUIRED';phase='evidence'}}
    @{schemaVersion=1;kind='doorhandle-current-task-failed-mysql-data-controller';status=$(if($ok){'COMPLETE'}else{'FAILED_OR_UNKNOWN'});batch='current-task-failed-verify-mysql-v1';release=$Tag;commit=$Commit;sourceSha256=$SourceSha256;requestSha256=$requestSha;taskThreadId=$task;authorizationSha256=$authorizationSha;selectedBuilds=$numbers;targetCount=$numbers.Count;applyAttempted=$attempted;sourceSqlAndReportsRetained=$true;existingBusinessDatabaseUntouched=$true;testsExecuted=$false;planCollected=($null -ne $plan);receiptCollected=($null -ne $receipt);failure=$failureDiagnostic;secondaryFailures=@($secondaryFailures.ToArray());remoteCalls=@($remoteCalls.ToArray())}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath artifacts/derived-mysql-controller.json -Encoding utf8
}
if(-not $ok){throw 'Authorized task-data retirement has not completed with original evidence.'}
