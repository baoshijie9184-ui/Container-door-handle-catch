param(
    [Parameter(Mandatory = $true)][string[]]$SshOptions,
    [Parameter(Mandatory = $true)][string]$Destination,
    [Parameter(Mandatory = $true)][string]$PortText,
    [Parameter(Mandatory = $true)][string]$RemoteRoot,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$SourceSha256,
    [string]$LegacySnapshot,
    [string]$AdditionalSnapshot
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Require-EvidenceRepair([bool]$Value, [string]$Message) { if (-not $Value) { throw $Message } }
function Assert-EvidenceRepairPath([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        Require-EvidenceRepair (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'CI permission control paths cannot use links or junctions.'
        $item = if ($item -is [IO.FileInfo]) { $item.Directory } else { $item.Parent }
    }
}
function Invoke-EvidenceRepair([string]$Executable, [string[]]$Arguments) {
    $lines = @(& $Executable @Arguments)
    if ($LASTEXITCODE -ne 0) { throw 'Registered CI evidence permission repair failed; data preservation remains blocked.' }
    return $lines
}
Require-EvidenceRepair ($env:CI_ECS_VERIFIED -ceq 'true') 'CI permission repair requires this build actual passing ECS verification.'
Require-EvidenceRepair ($Destination -cmatch '^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}$') 'Invalid admitted SSH destination.'
Require-EvidenceRepair ($PortText -match '^[0-9]{1,5}$' -and [int]$PortText -ge 1 -and [int]$PortText -le 65535) 'Invalid SSH port.'
Require-EvidenceRepair ($RemoteRoot -cmatch '^/(home|srv|opt)/[A-Za-z0-9_./-]+$' -and $RemoteRoot -notmatch '(^|/)[.][.]?(/|$)|//' -and -not $RemoteRoot.EndsWith('/')) 'Invalid ECS CI root.'
Require-EvidenceRepair ($Commit -cmatch '^[a-f0-9]{40}$' -and $SourceSha256 -cmatch '^[a-f0-9]{64}$' -and $Tag -cmatch '^ci-[1-9][0-9]*-[a-f0-9]{12}$' -and $Tag.EndsWith('-' + $Commit.Substring(0,12))) 'Fixed source identity is required.'
$instance = $env:DOORHANDLE_ECS_INSTANCE_ID; $machine = $env:DOORHANDLE_ECS_MACHINE_ID
Require-EvidenceRepair ($instance -cmatch '^i-[a-z0-9]+$' -and $machine -cmatch '^[a-f0-9]{32}$') 'Explicit ECS identity is required.'
$priorTags = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($inputPair in @(@($LegacySnapshot,'legacy-source-snapshot'), @($AdditionalSnapshot,'additional-local-artifacts-snapshot'))) {
    if ([string]::IsNullOrWhiteSpace($inputPair[0])) { continue }
    $pattern = '^' + [regex]::Escape($RemoteRoot) + '/verification/(ci-[1-9][0-9]*-[a-f0-9]{12})/checkout/work/' + [regex]::Escape($inputPair[1]) + '$'
    Require-EvidenceRepair ($inputPair[0] -cmatch $pattern) 'Prior evidence can only be selected through an exact same-root custody snapshot.'
    $prior = $Matches[1]
    Require-EvidenceRepair ([long]($prior.Split('-')[1]) -lt [long]($Tag.Split('-')[1])) 'A prior evidence repair must target a strictly earlier build.'
    [void]$priorTags.Add($prior)
}
Require-EvidenceRepair ($priorTags.Count -gt 0) 'Select an explicit prior ECS custody snapshot.'
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$archive = Join-Path $workspace 'artifacts/source.tar.gz'
$verification = Join-Path $workspace 'artifacts/ecs/evidence/verification-receipt.json'
foreach ($path in @($archive,$verification)) { Assert-EvidenceRepairPath $path }
Require-EvidenceRepair ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256) 'The fixed source archive changed.'
$verificationSha = (Get-FileHash -LiteralPath $verification -Algorithm SHA256).Hash.ToLowerInvariant()
$current = Get-Content -LiteralPath $verification -Raw -Encoding utf8 | ConvertFrom-Json
Require-EvidenceRepair ($current.status -ceq 'PASS' -and $current.verificationExitCode -eq 0 -and $current.release -ceq $Tag -and $current.commit -ceq $Commit -and $current.sourceSha256 -ceq $SourceSha256 -and $current.identity.instanceId -ceq $instance -and $current.identity.machineId -ceq $machine -and $current.identity.executionLocation -ceq 'ECS') 'A matching actual current PASS is required.'
$python = $env:LOCAL_PYTHON_EXE
if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
Require-EvidenceRepair ($python -and [IO.Path]::IsPathFullyQualified($python) -and (Test-Path -LiteralPath $python -PathType Leaf)) 'Use the existing local source-byte reader.'
$reader = @'
import hashlib,json,sys,tarfile
with tarfile.open(sys.argv[1],'r:gz') as archive:
    entries=[row for row in archive if row.name=='script/jenkins/repair-ci-evidence-permissions.py']
    if archive.pax_headers.get('comment')!=sys.argv[2] or len(entries)!=1 or not entries[0].isfile() or not 0<entries[0].size<=1048576: raise ValueError('Fixed CI permission helper missing')
    raw=archive.extractfile(entries[0]).read(1048577)
    if len(raw)!=entries[0].size: raise ValueError('Fixed helper is truncated')
print(json.dumps({'sha256':hashlib.sha256(raw).hexdigest()}))
'@
$binding = (Invoke-EvidenceRepair $python @('-I','-B','-c',$reader,$archive,$Commit) | Select-Object -Last 1) | ConvertFrom-Json
Require-EvidenceRepair ($binding.sha256 -cmatch '^[a-f0-9]{64}$') 'The fixed CI permission helper has no digest.'
Require-EvidenceRepair ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $SourceSha256 -and (Get-FileHash -LiteralPath $verification -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $verificationSha) 'Source or current PASS anchor changed while binding the helper.'
$helper = "$RemoteRoot/verification/$Tag/checkout/script/jenkins/repair-ci-evidence-permissions.py"
$output = "$RemoteRoot/verification/$Tag/checkout/work/prior-evidence-permissions"
$priorFlags = (@($priorTags | Sort-Object) | ForEach-Object { "--prior-tag '$_'" }) -join ' '
$guard = "test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$($binding.sha256)' && "
$command = "${guard}python3 -I -B '$helper' --root '$RemoteRoot' --tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --instance-id '$instance' --machine-id '$machine' --verification-receipt-sha256 '$verificationSha' $priorFlags --output '$output' --apply"
$ssh = (Get-Command ssh.exe -ErrorAction Stop | Select-Object -First 1).Source
$scp = (Get-Command scp.exe -ErrorAction Stop | Select-Object -First 1).Source
$lines = @(Invoke-EvidenceRepair $ssh ($SshOptions + @('-p',$PortText,$Destination,$command)))
Require-EvidenceRepair ($lines.Count -eq 1) 'CI permission repair must return one public summary.'
$result = $lines[0] | ConvertFrom-Json
Require-EvidenceRepair ($result.status -cin @('REPAIRED','NO_ACTION') -and $result.reportSha256 -cmatch '^[a-f0-9]{64}$' -and $result.originalReportBytesChanged -is [bool] -and -not $result.originalReportBytesChanged) 'CI permission repair did not prove unchanged original report bytes.'
$artifact = Join-Path $workspace 'artifacts/prior-evidence-permissions.json'
Require-EvidenceRepair (-not (Test-Path -LiteralPath $artifact)) 'Use a fresh repair evidence destination.'
Invoke-EvidenceRepair $scp ($SshOptions + @('-P',$PortText,"${Destination}:$output/public.json",$artifact)) | Out-Null
Assert-EvidenceRepairPath $artifact
Require-EvidenceRepair ((Get-Item -LiteralPath $artifact).Length -gt 0 -and (Get-Item -LiteralPath $artifact).Length -le 1MB -and (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $result.reportSha256) 'The original CI permission repair summary changed during collection.'
$proof = Get-Content -LiteralPath $artifact -Raw -Encoding utf8 | ConvertFrom-Json -Depth 32
Require-EvidenceRepair ($proof.status -ceq $result.status -and $proof.release -ceq $Tag -and $proof.commit -ceq $Commit -and $proof.sourceSha256 -ceq $SourceSha256 -and $proof.identity.instanceId -ceq $instance -and $proof.identity.machineId -ceq $machine -and $proof.identity.executionLocation -ceq 'ECS' -and $proof.originalReportBytesChanged -is [bool] -and -not $proof.originalReportBytesChanged -and $proof.auditSha256 -cmatch '^[a-f0-9]{64}$') 'The original CI permission repair summary differs from this fixed build.'
$expectedChanges = @($result.changedPaths); $observedChanges = @($proof.changedPaths)
foreach ($path in @($expectedChanges) + @($observedChanges)) {
    Require-EvidenceRepair ($path -is [string] -and $path.Length -gt 0 -and $path.Length -le 2048 -and -not $path.StartsWith('/') -and -not $path.Contains('\') -and -not $path.Contains([char]0) -and -not $path.Contains("`n") -and -not $path.Contains("`r") -and @($path.Split('/') | Where-Object { $_ -in @('','.','..') }).Count -eq 0) 'Repair changes must be exact relative CI paths.'
}
Require-EvidenceRepair ($expectedChanges.Count -eq $observedChanges.Count -and [string]::Join([char]0,$expectedChanges) -ceq [string]::Join([char]0,$observedChanges)) 'The collected repair path list differs from the authenticated helper output.'
Write-Output ([ordered]@{status=$proof.status;changedPaths=$proof.changedPaths;originalReportBytesChanged=$false;reportSha256=$result.reportSha256} | ConvertTo-Json -Compress)
