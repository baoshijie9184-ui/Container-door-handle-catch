param(
    [Parameter(Mandatory=$true)][string[]]$SshOptions,
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][string]$PortText,
    [Parameter(Mandatory=$true)][string]$RemoteRoot,
    [Parameter(Mandatory=$true)][string]$Tag
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
function Require-HistoricalCustody([bool]$Value,[string]$Message){if(-not $Value){throw $Message}}
function Assert-HistoricalRegularFile([string]$Path){
    $item=Get-Item -LiteralPath $Path -Force
    Require-HistoricalCustody ($item -is [IO.FileInfo]) 'A regular original custody file is required.'
    $cursor=$item
    while($null -ne $cursor){
        Require-HistoricalCustody (-not($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Custody paths cannot follow links or junctions.'
        $cursor=if($cursor -is [IO.FileInfo]){$cursor.Directory}else{$cursor.Parent}
    }
    return $item
}
function Assert-HistoricalExactPath([string]$Actual,[string]$Expected){
    Require-HistoricalCustody ([IO.Path]::IsPathFullyQualified($Actual) -and
        [string]::Equals($Actual.Replace('\','/'),$Expected.Replace('\','/'),[StringComparison]::OrdinalIgnoreCase)) 'Custody must use its exact original local path.'
}
function Assert-HistoricalDigest([string]$Path,[long]$Bytes,[string]$Sha){
    $item=Assert-HistoricalRegularFile $Path
    Require-HistoricalCustody ($Bytes -ge 0 -and $item.Length -eq $Bytes -and $Sha -cmatch '\A[a-f0-9]{64}\z' -and
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $Sha) 'An original custody file no longer matches its recorded bytes.'
}
Require-HistoricalCustody ($env:ACTION -ceq 'reclaim-build-outputs' -and $env:DOORHANDLE_CI_SCOPE -ceq 'source' -and
    $env:NATIVE_RETENTION_POLICY -ceq 'DerivedMysqlHistorical15' -and
    $env:CI_ECS_VERIFIED -ceq 'false' -and $env:PRODUCTION_RELEASE_ENABLED -cne 'true' -and
    $RemoteRoot -ceq '/home/ecs-user/doorhandle-ci' -and $Tag -cmatch '\Aci-[1-9][0-9]*-[a-f0-9]{12}\z' -and
    $Destination -cmatch '\A[a-z_][a-z0-9_-]*@[A-Za-z0-9.-]+\z' -and $PortText -cmatch '\A[0-9]{1,5}\z' -and
    [int]$PortText -ge 1 -and [int]$PortText -le 65535 -and
    $SshOptions -ccontains 'StrictHostKeyChecking=yes' -and $SshOptions -ccontains 'HostKeyAlias=doorhandle-bj') 'Historical custody staging requires the original source-only maintenance route.'
# These original records live outside the disposable Jenkins checkout.
$project='D:/AI/lunwen1/DoorHandleCatch'
$manifestPath="$project/work/table-switch-20261115/historical-derived-mysql-15-manifest.json"
$authorizationPath="$project/work/table-switch-20261115/cleanup-authorization-20261115.json"
$authorizationSha='07d2830e34d5e685e7a1ee08627d93f7383f2843829c66e844d720ffcbeeb60d'
$item=Assert-HistoricalRegularFile $manifestPath
Require-HistoricalCustody ($item.Length -gt 0 -and $item.Length -le 262144) 'The exact historical manifest must be a small original record.'
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable
$item=Assert-HistoricalRegularFile $authorizationPath
Require-HistoricalCustody ($item.Length -gt 0 -and $item.Length -le 65536) 'The original authorization must be a small record.'
$authorizationBytes=$item.Length
Assert-HistoricalDigest $authorizationPath $authorizationBytes $authorizationSha
$releases=@(
    'ci-154-38293aa306b3','ci-160-9d011d9d5ed8','ci-162-97844cecb2f4','ci-166-a3c084e1cf56','ci-168-a40c779d03a4',
    'ci-173-45465e873d92','ci-187-8e90ba50c691','ci-188-df1e1a54d48e','ci-189-410506ad7c82','ci-195-2c2e65a0daa9',
    'ci-198-7af0903ee840','ci-201-803baf401b5f','ci-204-24f8eb4b02bf','ci-223-fc724a42d8f9','ci-224-e2b445effb49'
)
Require-HistoricalCustody ($manifest.schemaVersion -eq 1 -and $manifest.batch -ceq 'derived-mysql-historical-15-v1' -and
    $manifest.taskId -ceq '01a1de46-3b28-7a21-84e7-4f403268fa01' -and @($manifest.targets).Count -eq 15 -and
    (@($manifest.targets|ForEach-Object{$_.release}|Sort-Object)-join ',') -ceq (@($releases|Sort-Object)-join ',')) 'Only the exact fifteen historical releases may be staged.'
$uploads=[Collections.Generic.List[object]]::new()
foreach($target in $manifest.targets){
    $number=[long]$target.release.Split('-')[1]
    Require-HistoricalCustody ($target.build -eq $number -and $number -lt [long]$Tag.Split('-')[1]) 'The historical build must precede this maintenance build.'
    $folderName=if($number -eq 204){'ci-204-collaboration-raw'}else{"ci-$number-raw-receipts"}
    $folder="$project/work/jenkins/data-residency-20261107/$folderName"
    $custodyName=if($number -eq 204){'sha256-manifest.json'}else{'preservation.json'}
    Assert-HistoricalExactPath $target.custodyDirectory $folder
    Assert-HistoricalExactPath $target.custodyManifest "$folder/$custodyName"
    $item=Assert-HistoricalRegularFile $target.custodyManifest
    Require-HistoricalCustody ($item.Length -gt 0 -and $item.Length -le 4194304) 'The original custody manifest is absent or exceeds its bound.'
    $custody=Get-Content -LiteralPath $target.custodyManifest -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable
    Require-HistoricalCustody ($custody.build -eq $number -and @($custody.files).Count -gt 0 -and
        @($custody.files).Count -le 4096) 'Custody does not describe this historical build.'
    $entries=@{}
    foreach($entry in $custody.files){
        $name=[string]$entry.path
        Require-HistoricalCustody ($name -cmatch '\A[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\z' -and
            @($name.Split('/')|Where-Object{$_ -cin @('.','..')}).Count -eq 0 -and -not $entries.ContainsKey($name)) 'Custody members must be unique contained relative paths.'
        $entries[$name]=$entry
        # These are retained under their existing binary/source contracts, not
        # uploaded or made a new local prerequisite for historical report custody.
        if($name -cin @('application.jar','source.tar.gz')){continue}
        if($entry.ContainsKey('preserved')){Assert-HistoricalExactPath ([string]$entry.preserved) "$folder/$name"}
        Assert-HistoricalDigest "$folder/$name" $entry.bytes $entry.sha256
    }
    Require-HistoricalCustody (@($target.files).Count -eq 2 -and
        (@($target.files|ForEach-Object{$_.name}|Sort-Object)-join ',') -ceq 'build.xml,release.json') 'Only the original terminal XML and release receipt may be uploaded.'
    foreach($file in $target.files){
        $name=$file.name;$entry=$entries[$name]
        $digest=if($null -ne $entry){$entry.sha256}elseif($name -ceq 'build.xml'){$custody.buildXmlSha256}else{$null}
        Require-HistoricalCustody ($digest -ceq $file.sha256 -and $file.bytes -gt 0 -and $file.bytes -le 2097152) 'The exact manifest must match the original custody binding.'
        if($name -ceq 'build.xml' -and $custody.ContainsKey('buildXmlSha256')){
            Require-HistoricalCustody ($custody.buildXmlSha256 -ceq $file.sha256) 'The original terminal XML bindings disagree.'
        }
        if($null -ne $entry){
            Require-HistoricalCustody ($entry.bytes -eq $file.bytes) 'The original custody byte count differs.'
            $origin=if($name -ceq 'build.xml'){"C:/Users/19771/.jenkins/jobs/doorhandle-java/builds/$number/build.xml"}else{"C:/Users/19771/.jenkins/jobs/doorhandle-java/builds/$number/archive/artifacts/release.json"}
            Assert-HistoricalExactPath $entry.original $origin
        }
        Assert-HistoricalDigest "$folder/$name" $file.bytes $file.sha256
        [void]$uploads.Add(@{source="$folder/$name";release=$target.release;name=$name;bytes=$file.bytes;sha256=$file.sha256})
    }
    $release=Get-Content -LiteralPath "$folder/release.json" -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable
    Require-HistoricalCustody ($release.release -ceq $target.release -and $release.commit -cmatch '\A[a-f0-9]{40}\z' -and
        $target.release.EndsWith('-'+$release.commit.Substring(0,12)) -and $release.sourceSha256 -cmatch '\A[a-f0-9]{64}\z') 'The original release context differs from its historical identity.'
    if($custody.ContainsKey('commit')){Require-HistoricalCustody ($custody.commit -ceq $release.commit) 'The preserved source commit differs.'}
    if($custody.ContainsKey('result')){Require-HistoricalCustody ($custody.result -cin @('FAILURE','ABORTED')) 'Only the reviewed failed historical builds are eligible.'}
}
# All local custody is checked before the first remote side effect. The existing
# Python plan independently authenticates the uploaded originals and live owners.
$remote="$RemoteRoot/inbox/$Tag/historical-derived-controls"
$ancestors=@('/home','/home/ecs-user',$RemoteRoot,"$RemoteRoot/inbox","$RemoteRoot/inbox/$Tag")
$checks=@($ancestors|ForEach-Object{"test -d '$_' && test ! -L '$_'"})
$prepare='test "$(id -u)" = 1000 && test "$(cat /etc/machine-id)" = 1ebe8f77e3104ab6a49a9386e38abd20 && '+($checks -join ' && ')+" && umask 077 && test ! -e '$remote' && test ! -L '$remote' && mkdir -m 700 '$remote'"
foreach($release in $releases){$prepare+=" && mkdir -m 700 '$remote/$release'"}
$null=& ssh.exe @SshOptions -p $PortText $Destination $prepare
Require-HistoricalCustody ($LASTEXITCODE -eq 0) 'Fresh private historical staging is required; do not replay an unknown operation.'
[void]$uploads.Add(@{source=$authorizationPath;release=$null;name='authorization.json';bytes=$authorizationBytes;sha256=$authorizationSha})
foreach($upload in $uploads){
    Assert-HistoricalDigest $upload.source $upload.bytes $upload.sha256
    $destinationPath=if($null -eq $upload.release){"$remote/$($upload.name)"}else{"$remote/$($upload.release)/$($upload.name)"}
    $null=& ssh.exe @SshOptions -p $PortText $Destination "test ! -e '$destinationPath' && test ! -L '$destinationPath'"
    Require-HistoricalCustody ($LASTEXITCODE -eq 0) 'An original upload destination already exists.'
    $null=& scp.exe @SshOptions -P $PortText $upload.source "${Destination}:$destinationPath"
    Require-HistoricalCustody ($LASTEXITCODE -eq 0) 'An original historical control upload failed.'
    $null=& ssh.exe @SshOptions -p $PortText $Destination "test -f '$destinationPath' && test ! -L '$destinationPath' && chmod 600 '$destinationPath'"
    Require-HistoricalCustody ($LASTEXITCODE -eq 0) 'The uploaded original must remain a private regular file.'
    Assert-HistoricalDigest $upload.source $upload.bytes $upload.sha256
}
