param(
    [Parameter(Mandatory=$true)][string[]]$SshOptions,
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][string]$PortText,
    [Parameter(Mandatory=$true)][string]$RemoteRoot,
    [Parameter(Mandatory=$true)][string]$Tag,
    [Parameter(Mandatory=$true)][string]$Commit,
    [Parameter(Mandatory=$true)][string]$SourceSha256,
    [Parameter(Mandatory=$true)][string]$PinnedHelper
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$batches=@{
    DerivedMysql221222235238247=@{batch='derived-mysql-221-222-235-238-247-v1';count=5}
    DerivedMysql250253256259264268=@{batch='derived-mysql-250-253-256-259-264-268-v1';count=6}
}
if ($env:ACTION -cne 'reclaim-build-outputs' -or $env:NATIVE_RETENTION_POLICY -cnotin @('DerivedMysql221222235238247','DerivedMysql250253256259264268') -or
    $env:DOORHANDLE_CI_SCOPE -cne 'source' -or $env:CI_ECS_VERIFIED -cne 'false' -or $env:PRODUCTION_RELEASE_ENABLED -ceq 'true' -or
    $RemoteRoot -cne '/home/ecs-user/doorhandle-ci' -or $env:DOORHANDLE_ECS_INSTANCE_ID -cne 'i-2zeieuov2aum486jm1ek' -or
    $env:DOORHANDLE_ECS_MACHINE_ID -cne '1ebe8f77e3104ab6a49a9386e38abd20' -or
    $Tag -cnotmatch '^ci-[0-9]+-[a-f0-9]{12}$' -or $Commit -cnotmatch '^[a-f0-9]{40}$' -or
    -not $Tag.EndsWith($Commit.Substring(0,12)) -or $SourceSha256 -cnotmatch '^[a-f0-9]{64}$' -or
    $PortText -cnotmatch '^[0-9]{1,5}$' -or $Destination -cnotmatch '^[a-z_][a-z0-9_-]*@[A-Za-z0-9.-]+$') {
    throw 'The approved closed derived-MySQL batch requires fixed source-only maintenance on the original ECS.'
}
$selected=$batches[$env:NATIVE_RETENTION_POLICY];$batch=$selected.batch;$targetCount=$selected.count
$remote="$RemoteRoot/inbox/$Tag"
$helper="$remote/retire-derived-mysql-data.py"
$directory="$remote/derived-mysql-retirement"
$binding="--batch '$batch' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256'"
foreach($name in @('derived-mysql-plan.json','derived-mysql-receipt.json','derived-mysql-controller.json')) {
    if(Test-Path -LiteralPath "artifacts/$name") {throw 'Fresh maintenance evidence is required.'}
}
$plan=$null;$receipt=$null;$attempted=$false;$failure=$null
function Copy-DerivedEvidence([string]$Name,[string]$Local){
    & scp.exe @SshOptions -P $PortText "${Destination}:$directory/$Name" $Local
    if($LASTEXITCODE -ne 0){return $null}
    if((Get-Item -LiteralPath $Local).Length -gt 2097152){throw 'Derived retirement evidence exceeds its bound.'}
    $value=Get-Content -LiteralPath $Local -Raw|ConvertFrom-Json
    if($value.batch -cne $batch -or $value.release -cne $Tag -or
       $value.commit -cne $Commit -or $value.sourceSha256 -cne $SourceSha256 -or
       $value.identity.instanceId -cne $env:DOORHANDLE_ECS_INSTANCE_ID -or
       $value.identity.machineId -cne $env:DOORHANDLE_ECS_MACHINE_ID -or
       $value.identity.executionLocation -cne 'ECS' -or $value.sourceSqlAndReportsRetained -ne $true){
        throw 'Derived retirement evidence belongs to another attempt or preservation boundary.'
    }
    return $value
}
try {
    & ssh.exe @SshOptions -p $PortText $Destination "test ! -e '$helper' && test ! -L '$helper'"
    if($LASTEXITCODE -ne 0){throw 'The fixed derived retirement helper path is occupied.'}
    & scp.exe @SshOptions -P $PortText $PinnedHelper "${Destination}:$helper"
    if($LASTEXITCODE -ne 0){throw 'Fixed derived helper upload failed.'}
    & ssh.exe @SshOptions -p $PortText $Destination "chmod 600 '$helper' && python3 -I -B '$helper' plan $binding"
    if($LASTEXITCODE -ne 0){throw 'Closed derived-data planning failed; no apply was issued.'}
    $plan=Copy-DerivedEvidence 'plan.json' 'artifacts/derived-mysql-plan.json'
    if($null -eq $plan -or $plan.planSha256 -cnotmatch '^[a-f0-9]{64}$' -or @($plan.targets).Count -ne $targetCount){throw 'A complete original derived-data plan is required.'}
    $attempted=$true
    & ssh.exe @SshOptions -p $PortText $Destination "python3 -I -B '$helper' apply $binding --plan-sha256 '$($plan.planSha256)'"
    $applyExit=$LASTEXITCODE
    if($applyExit -eq 255){
        $observed=$null
        for($index=0;$index -lt 30;$index++){
            $lines=@(& ssh.exe @SshOptions -p $PortText $Destination "python3 -I -B '$helper' status $binding")
            if($LASTEXITCODE -eq 0){
                $observed=($lines|Select-Object -Last 1)|ConvertFrom-Json
                if($observed.batch -cne $batch -or $observed.release -cne $Tag -or $observed.commit -cne $Commit -or $observed.sourceSha256 -cne $SourceSha256){throw 'Original retirement observation differs.'}
                if($observed.terminal -eq $true){break}
            }
            Start-Sleep -Seconds 5
        }
        if($null -eq $observed -or $observed.terminal -ne $true -or $observed.status -cne 'COMPLETE'){throw 'Original retirement has no confirmed successful terminal; retain resources and do not replay.'}
    } elseif($applyExit -ne 0){throw 'Derived-data apply did not confirm completion; do not rerun an unknown operation.'}
} catch {$failure=$_} finally {
    try {
        if($null -eq $plan){$plan=Copy-DerivedEvidence 'plan.json' 'artifacts/derived-mysql-plan.json'}
        if($attempted){$receipt=Copy-DerivedEvidence 'receipt.json' 'artifacts/derived-mysql-receipt.json'}
    } catch {$failure=$_}
    $ok=$null -eq $failure -and $null -ne $plan -and $null -ne $receipt -and $receipt.status -ceq 'COMPLETE' -and
        $receipt.planSha256 -ceq $plan.planSha256 -and @($receipt.removed).Count -eq $targetCount
    @{status=$(if($ok){'COMPLETE'}else{'FAILED_OR_UNKNOWN'});release=$Tag;commit=$Commit;sourceSha256=$SourceSha256;
      applyAttempted=$attempted;planCollected=($null -ne $plan);receiptCollected=($null -ne $receipt);
      batch=$batch;targetCount=$targetCount;existingBusinessDatabaseUntouched=$true;sourceSqlAndReportsRetained=$true;testsExecuted=$false}|
        ConvertTo-Json|Set-Content -LiteralPath artifacts/derived-mysql-controller.json -Encoding utf8
}
if(-not $ok){throw 'The closed derived-MySQL retirement has not completed with original evidence.'}
