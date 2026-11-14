param(
 [Parameter(Mandatory=$true)][string[]]$SshOptions,
 [Parameter(Mandatory=$true)][string]$Destination,
 [Parameter(Mandatory=$true)][string]$PortText,
 [Parameter(Mandatory=$true)][string]$RemoteRoot,
 [Parameter(Mandatory=$true)][string]$Tag,
 [Parameter(Mandatory=$true)][string]$Commit,
 [Parameter(Mandatory=$true)][string]$SourceSha256
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if($env:ACTION -cne 'reclaim-build-outputs' -or $env:NATIVE_RETENTION_POLICY -cne 'SourcePytest16' -or
   $env:DOORHANDLE_CI_SCOPE -cne 'source' -or $env:CI_ECS_VERIFIED -cne 'false' -or
   $env:PRODUCTION_RELEASE_ENABLED -ceq 'true' -or $RemoteRoot -cne '/home/ecs-user/doorhandle-ci' -or
   $env:DOORHANDLE_ECS_INSTANCE_ID -cne 'i-2zeieuov2aum486jm1ek' -or
   $env:DOORHANDLE_ECS_MACHINE_ID -cne '1ebe8f77e3104ab6a49a9386e38abd20' -or
   $Tag -cnotmatch '^ci-[1-9][0-9]*-[a-f0-9]{12}$' -or $Commit -cnotmatch '^[a-f0-9]{40}$' -or
   -not $Tag.EndsWith('-'+$Commit.Substring(0,12)) -or $SourceSha256 -cnotmatch '^[a-f0-9]{64}$' -or
   $PortText -cnotmatch '^[0-9]{1,5}$' -or $Destination -cnotmatch '^[a-z_][a-z0-9_-]*@[A-Za-z0-9.-]+$' -or
   -not [string]::IsNullOrEmpty($env:FAILED_NATIVE_BUILD_NUMBER) -or -not [string]::IsNullOrEmpty($env:FAILED_MYSQL_DATA_BUILDS)) {
 throw 'Exact source pytest retirement requires fixed source-only maintenance on the original ECS.'
}
$authorization=$env:DOORHANDLE_SOURCE_PYTEST16_AUTHORIZATION_FILE
$expected='D:/AI/lunwen1/DoorHandleCatch/work/jenkins/data-residency-20261107/source-pytest16-retention-authorization-20261114.json'
if(-not $authorization -or [IO.Path]::GetFullPath($authorization) -ine [IO.Path]::GetFullPath($expected) -or
   -not (Test-Path -LiteralPath $authorization -PathType Leaf)) {throw 'The original exact user authorization is required.'}
$auth=Get-Content -LiteralPath $authorization -Raw -Encoding utf8 | ConvertFrom-Json
$numbers=@(100,102,103,104,105,107,109,110,114,120,122,150,178,180,215,217)
if($auth.kind -cne 'doorhandle-exact-source-pytest-temporary-retirement-authorization' -or
   $auth.source -cne 'USER_EXPLICIT_MESSAGE' -or $auth.job -cne 'doorhandle-java' -or $auth.branch -cne 'java-cloud' -or
   ($auth.exactBuilds -join ',') -cne ($numbers -join ',') -or $auth.allowArbitraryPath -ne $false -or
   $auth.allowFutureBuilds -ne $false -or $auth.allowRootTargetMutations -ne $false -or
   $auth.allowOwnerWriteForOwnedTargetDirectories -ne $true -or $auth.authorizationEndsWhenExactTargetsConsumed -ne $true) {
 throw 'User authorization differs from the closed sixteen roots.'
}
$authSha=(Get-FileHash -LiteralPath $authorization -Algorithm SHA256).Hash.ToLowerInvariant()
$remote="$RemoteRoot/inbox/$Tag";$helper="$remote/retire-source-pytest.py";$directory="$remote/source-pytest-retirement"
$binding="--tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --authorization-sha256 '$authSha'"
$local='artifacts/source-pytest16';if(Test-Path -LiteralPath $local){throw 'Fresh retirement evidence directory required.'}
New-Item -ItemType Directory -Path $local | Out-Null
$failure=$null;$plan=$null;$receipt=$null;$issued=$false;$helperSha=$null
function Invoke-ExactSsh([string]$Command){
 $lines=@(& ssh.exe @SshOptions -p $PortText $Destination $Command)
 if($LASTEXITCODE -ne 0){throw 'Source pytest control transport did not complete.'}
 return $lines
}
function Copy-ExactEvidence([string]$Name){
 & scp.exe @SshOptions -P $PortText "${Destination}:$directory/$Name" "$local/$Name"
 if($LASTEXITCODE -ne 0){return $null}
 if((Get-Item -LiteralPath "$local/$Name").Length -gt 33554432){throw 'Retirement control exceeds its bounded size.'}
 $value=Get-Content -LiteralPath "$local/$Name" -Raw|ConvertFrom-Json
 if($value.batch -cne 'source-pytest16-20261114' -or $value.release -cne $Tag -or $value.commit -cne $Commit -or
    $value.sourceSha256 -cne $SourceSha256 -or $value.authorizationSha256 -cne $authSha -or
    $value.identity.instanceId -cne $env:DOORHANDLE_ECS_INSTANCE_ID -or $value.identity.machineId -cne $env:DOORHANDLE_ECS_MACHINE_ID -or
    $value.identity.executionLocation -cne 'ECS' -or $value.sourceSqlAndReportsRetained -ne $true -or
    $value.businessDatabaseUntouched -ne $true){throw 'Retirement originals belong to another source or preservation scope.'}
 return $value
}
try {
 $package=Get-Content artifacts/release.json -Raw|ConvertFrom-Json
 if($package.schema -ne 1 -or $package.action -cne 'reclaim-build-outputs' -or $package.kind -cne 'doorhandle-maintenance-source' -or $package.maintenanceOnly -ne $true -or $package.testsExecuted -ne $false -or $package.applicationBuilt -ne $false -or
    $package.commit -cne $Commit -or $package.release -cne $Tag -or $package.sourceSha256 -cne $SourceSha256 -or
    (Get-FileHash artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant() -cne $SourceSha256) {throw 'Pinned maintenance source package required.'}
 # No business/fixture stage or generic cleanup is invoked by this policy.
 $null=Invoke-ExactSsh "test `"`$(id -u)`" = 1000 && test `"`$(cat /etc/machine-id)`" = '1ebe8f77e3104ab6a49a9386e38abd20' && test ! -e '$remote' && test ! -L '$remote' && mkdir -m 700 '$remote'"
 & scp.exe @SshOptions -P $PortText artifacts/source.tar.gz "${Destination}:$remote/cleanup-source.tar.gz"
 if($LASTEXITCODE -ne 0){throw 'Maintenance source transfer failed.'}
 foreach($name in @('retire-source-pytest.py','cleanup-ecs-builds.py','verify-remote.py')){
  $inputFile=Get-PinnedSourceFile ('script/jenkins/'+$name)
  if($name -ceq 'retire-source-pytest.py'){$helperSha=(Get-FileHash -LiteralPath $inputFile -Algorithm SHA256).Hash.ToLowerInvariant()}
  & scp.exe @SshOptions -P $PortText $inputFile "${Destination}:$remote/$name"
  if($LASTEXITCODE -ne 0){throw 'Fixed retirement helper transfer failed.'}
 }
 & scp.exe @SshOptions -P $PortText $authorization "${Destination}:$remote/source-pytest16-authorization.json"
 if($LASTEXITCODE -ne 0){throw 'Exact authorization transfer failed.'}
 $null=Invoke-ExactSsh "chmod 600 '$remote/cleanup-source.tar.gz' '$helper' '$remote/cleanup-ecs-builds.py' '$remote/verify-remote.py' '$remote/source-pytest16-authorization.json'"
 $guard="test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$helperSha' && python3 -I -B '$helper'"
 & ssh.exe @SshOptions -p $PortText $Destination "$guard plan $binding"
 $planExit=$LASTEXITCODE
 if($planExit -eq 255){
  $original=$null
  for($i=0;$i -lt 360;$i++){
   $lines=@(& ssh.exe @SshOptions -p $PortText $Destination "$guard status $binding")
   if($LASTEXITCODE -eq 0){$original=($lines|Select-Object -Last 1)|ConvertFrom-Json;if($original.planTerminal -eq $true){break}}
   Start-Sleep -Seconds 5
  }
  if($null -eq $original -or $original.planTerminal -ne $true -or $original.status -cne 'PLANNED'){throw 'Original planning has not completed successfully; do not replay it.'}
 } elseif($planExit -ne 0){throw 'Exact pytest planning refused; no apply issued.'}
 $plan=Copy-ExactEvidence 'plan.json'
 if($null -eq $plan -or $plan.status -cne 'PLANNED' -or @($plan.targets).Count -ne 16){throw 'Complete closed plan required.'}
 $planSha=(Get-FileHash "$local/plan.json" -Algorithm SHA256).Hash.ToLowerInvariant()
 $issued=$true
 & ssh.exe @SshOptions -p $PortText $Destination "$guard apply $binding --plan-sha256 '$planSha'"
 $applyExit=$LASTEXITCODE
 if($applyExit -eq 255){
  $original=$null
  for($i=0;$i -lt 360;$i++){
   $lines=@(& ssh.exe @SshOptions -p $PortText $Destination "$guard status $binding")
   if($LASTEXITCODE -eq 0){$original=($lines|Select-Object -Last 1)|ConvertFrom-Json;if($original.terminal -eq $true){break}}
   Start-Sleep -Seconds 5
  }
  if($null -eq $original -or $original.terminal -ne $true -or $original.status -cne 'COMPLETE'){throw 'Original apply is not complete; do not replay deletion.'}
 } elseif($applyExit -ne 0){throw 'Exact pytest retirement failed; preserve original partial evidence.'}
 $receipt=Copy-ExactEvidence 'receipt.json'
 if($null -eq $receipt -or $receipt.status -cne 'COMPLETE' -or $receipt.planSha256 -cne $planSha -or @($receipt.settled).Count -ne 16){throw 'Complete original retirement receipt required.'}
} catch {$failure=$_} finally {
 try {
  if($null -eq $plan){$plan=Copy-ExactEvidence 'plan.json'}
  if($issued -and $null -eq $receipt){$receipt=Copy-ExactEvidence 'receipt.json'}
  $originalsComplete=$true
  # Fixed filenames only; never copy private auth, environment or target data.
  foreach($number in $numbers){
   foreach($suffix in @('.json','.journal.jsonl')){
    $name='root-'+$number+$suffix
    & scp.exe @SshOptions -P $PortText "${Destination}:$directory/$name" "$local/$name" 2>$null
    if($LASTEXITCODE -ne 0){
     $plannedRow=if($null -ne $plan){@($plan.targets|Where-Object {$_.release -cmatch ('^ci-'+$number+'-')})}else{@()}
     if($plannedRow.Count -eq 1 -and $plannedRow[0].status -ceq 'PLANNED'){$originalsComplete=$false}
    } elseif((Get-Item -LiteralPath "$local/$name").Length -gt 33554432){throw 'Root retirement original exceeds its bound.'}
   }
  }
 } catch {$failure=$_}
 if($null -ne $plan -and $null -ne $receipt){
  foreach($row in $plan.targets){
   if($row.status -cne 'PLANNED'){continue}
   $name='root-'+($row.release.Split('-')[1])+'.json'
   if(-not (Test-Path -LiteralPath "$local/$name") -or
      (Get-FileHash "$local/$name" -Algorithm SHA256).Hash.ToLowerInvariant() -cne $row.sha256){$originalsComplete=$false}
   $done=@($receipt.settled|Where-Object release -CEQ $row.release)
   if($done.Count -eq 1 -and $done[0].status -ceq 'REMOVED'){
    $name=$done[0].journal
    if($name -cne ('root-'+($row.release.Split('-')[1])+'.journal.jsonl') -or
       -not (Test-Path -LiteralPath "$local/$name") -or
       (Get-FileHash "$local/$name" -Algorithm SHA256).Hash.ToLowerInvariant() -cne $done[0].journalSha256){$originalsComplete=$false}
   }
  }
 }
 $ok=$null -eq $failure -and $originalsComplete -and $null -ne $receipt -and $receipt.status -ceq 'COMPLETE'
 @{status=$(if($ok){'COMPLETE'}else{'FAILED_OR_UNKNOWN'});batch='source-pytest16-20261114';release=$Tag;commit=$Commit;
   sourceSha256=$SourceSha256;authorizationSha256=$authSha;applyIssued=$issued;planCollected=($null -ne $plan);
   receiptCollected=($null -ne $receipt);sourceSqlAndReportsRetained=$true;businessDatabaseUntouched=$true;
   ecsLifecycle='EXTERNAL_TO_JENKINS';testsExecuted=$false}|ConvertTo-Json|Set-Content "$local/controller.json" -Encoding utf8
}
if(-not $ok){throw 'Exact sixteen-root retirement did not complete with original evidence.'}