param([Parameter(Mandatory = $true)][ValidateSet('Preflight', 'Package', 'PackageSourceOnly', 'PackageControls', 'PrepareTools', 'CleanupTools', 'PrepareFixtures', 'CleanupFixtures', 'VerifyEcs', 'VerifyEmbedding', 'RepairPriorEvidence', 'CollectExistingEvidence', 'PreserveLegacy', 'PreserveLocalArtifacts', 'PreserveRemainingArtifacts', 'PreserveColdStores', 'PreserveLocalMySql', 'CleanupLocalMySql', 'PreserveProjectMySql', 'CleanupProjectMySql', 'ReclaimBuildOutputs', 'CleanupGeneratedArtifacts', 'PrepareLegacyCandidate', 'CleanupLegacyCandidate', 'VerifyRuntime', 'CleanupRuntime', 'Publish', 'Rehearse', 'CompactCutover')][string]$Action)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path

if ($Action -ceq 'CollectExistingEvidence') {
    & (Join-Path $PSScriptRoot 'collect-existing-evidence.ps1')
    return
}
if ($env:ACTION -ceq 'collect-existing-evidence') { throw 'Recollection cannot enter any remote, build, test or deployment action.' }

function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Command failed with exit $LASTEXITCODE" }
}
function Require-Value([string]$Name, [string]$Pattern) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value) -or $value -notmatch $Pattern) { throw "Invalid or missing $Name" }
    return $value
}
function Assert-ControlExecutionState($State,$Request) {
    if ($State.release -cne $Request.release -or $State.commit -cne $Request.commit -or
        $State.sourceSha256 -cne $Request.sourceSha256 -or $State.toolManifestSha256 -cne $Request.toolManifestSha256 -or
        $State.identity.instanceId -cne $Request.instanceId -or $State.identity.machineId -cne $Request.machineId -or
        $State.identity.executionLocation -cne 'ECS' -or $State.terminal -ne $true -or
        $State.cleanupConfirmed -isnot [bool] -or $State.status -cnotin @('CONTROL_PREFLIGHT_PASS','FAILED_OR_UNKNOWN','CONTROL_PREFLIGHT_REJECTED')) {
        throw 'The control preflight has no matching original terminal observation; retain its tools.'
    }
    if ($State.status -cne 'CONTROL_PREFLIGHT_REJECTED' -and
        ($State.receipt -cne "$remoteInbox/control-preflight/output/receipt.json" -or $State.receiptSha256 -cnotmatch '^[a-f0-9]{64}$')) {
        throw 'The original control preflight terminal receipt identity is incomplete.'
    }
}
function Wait-ExistingControlPreflight {
    $PSNativeCommandUseErrorActionPreference=$false
    $request=Get-Content -LiteralPath artifacts/control-preflight/execution-request.json -Raw | ConvertFrom-Json
    $package=Get-Content -LiteralPath artifacts/release.json -Raw | ConvertFrom-Json
    $tools=Get-Content -LiteralPath artifacts/ecs-tool-runtime.json -Raw | ConvertFrom-Json
    if ($request.release -cne $tag -or $request.commit -cne $package.commit -or $request.sourceSha256 -cne $package.sourceSha256 -or
        $request.helperSha256 -cnotmatch '^[a-f0-9]{64}$' -or $request.toolManifestSha256 -cne $tools.manifestSha256 -or
        $request.instanceId -cne $env:DOORHANDLE_ECS_INSTANCE_ID -or $request.machineId -cne $env:DOORHANDLE_ECS_MACHINE_ID) {
        throw 'Control preflight observation request differs from this fixed source or ECS.'
    }
    $saved='artifacts/control-preflight/execution-observation.json'
    if (Test-Path -LiteralPath $saved) {
        $state=Get-Content -LiteralPath $saved -Raw | ConvertFrom-Json
        Assert-ControlExecutionState $state $request
        if (-not $state.cleanupConfirmed) { throw 'Original control preflight cleanup is unresolved; retain its tools.' }
        return $state
    }
    $helper="$remoteInbox/control-preflight.py"
    $binding="--root '$remoteRoot' --tag '$tag' --commit '$($request.commit)' --source-sha256 '$($request.sourceSha256)' --instance-id '$($request.instanceId)' --machine-id '$($request.machineId)' --tool-manifest-sha256 '$($request.toolManifestSha256)'"
    $command="test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$($request.helperSha256)' && python3 -I -B '$helper' $binding --observe"
    for ($readback=1; $readback -le 3; $readback++) {
        $lines=@(& ssh.exe @sshOptions -p $portText $destination $command 2>> artifacts/control-preflight/observe.stderr.log)
        $exit=$LASTEXITCODE
        $lines | Add-Content -LiteralPath artifacts/control-preflight/observe.stdout.log -Encoding utf8
        if ($exit -eq 255) { if ($readback -lt 3) { Start-Sleep -Seconds 2 }; continue }
        if ($exit -notin @(0,2) -or $lines.Count -eq 0) { throw 'Original control preflight observation failed; retain its tools.' }
        $state=$lines[-1] | ConvertFrom-Json
        Assert-ControlExecutionState $state $request
        if (($exit -eq 0) -ne ($state.status -ceq 'CONTROL_PREFLIGHT_PASS')) { throw 'Control preflight observation exit and terminal status differ.' }
        $state | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $saved -Encoding utf8
        if (-not $state.cleanupConfirmed) { throw 'Original control preflight cleanup is unresolved; retain its tools.' }
        return $state
    }
    throw 'Cannot reconnect to the original control preflight; do not restart it or clean its tools.'
}
function Wait-ExistingVerification {
    # Read back the same remote attempt after an SSH transport loss. Never run
    # verification again, and never clean its tools while its supervisor is live.
    $request=Get-Content -LiteralPath artifacts/ecs-verification-request.json -Raw | ConvertFrom-Json
    $package=Get-Content -LiteralPath artifacts/release.json -Raw | ConvertFrom-Json
    if ($request.release -cne $tag -or $request.commit -cne $package.commit -or
        $request.sourceSha256 -cne $package.sourceSha256 -or $request.attempt -cnotmatch '^[a-f0-9]{32}$' -or
        $request.helperSha256 -cnotmatch '^[a-f0-9]{64}$' -or $request.scope -cnotin @('source','mysql') -or
        $request.instanceId -cne $env:DOORHANDLE_ECS_INSTANCE_ID -or $request.machineId -cne $env:DOORHANDLE_ECS_MACHINE_ID) {
        throw 'The verification observation request differs from this fixed build.'
    }
    $binding="--root '$remoteRoot' --tag '$tag' --source-sha256 '$($request.sourceSha256)' --commit '$($request.commit)' --instance-id '$($request.instanceId)' --machine-id '$($request.machineId)' --scope '$($request.scope)' --attempt '$($request.attempt)'"
    $observe="test `"`$(sha256sum '$remoteInbox/verify-remote.py' | cut -d ' ' -f 1)`" = '$($request.helperSha256)' && python3 -B '$remoteInbox/verify-remote.py' observe $binding"
    for ($readback=1; $readback -le 3; $readback++) {
        $lines=@(& ssh.exe @sshOptions -p $portText $destination $observe)
        $exit=$LASTEXITCODE
        $lines | Add-Content -LiteralPath artifacts/ecs-verification-observe.stdout.log -Encoding utf8
        if ($exit -eq 255) { if ($readback -lt 3) { Start-Sleep -Seconds 2 }; continue }
        if ($exit -notin @(0,1) -or $lines.Count -eq 0) { throw 'Original verification observation failed; retain its owned resources.' }
        $state=$lines[-1] | ConvertFrom-Json
        if ($state.release -cne $tag -or $state.attempt -cne $request.attempt -or $state.scope -cne $request.scope -or
            $state.terminal -ne $true -or $state.status -cnotin @('PASS','FAILED') -or
            $state.evidenceReady -isnot [bool] -or ($exit -eq 0 -and ($state.status -cne 'PASS' -or -not $state.evidenceReady))) {
            throw 'Original verification has no matching terminal result; retain its owned resources.'
        }
        $state | ConvertTo-Json | Set-Content -LiteralPath artifacts/ecs-verification-observation.json -Encoding utf8
        return $state
    }
    throw 'Cannot reconnect to the original verification; retain its owned resources and inspect that same attempt.'
}
function Wait-ExistingRuntime {
    $PSNativeCommandUseErrorActionPreference=$false
    $request=Get-Content -LiteralPath artifacts/runtime-execution-request.json -Raw | ConvertFrom-Json
    $package=Get-Content -LiteralPath artifacts/release.json -Raw | ConvertFrom-Json
    if ($request.release -cne $tag -or $request.commit -cne $package.commit -or $request.sourceSha256 -cne $package.sourceSha256 -or
        $request.runtime -cne $runtime -or $request.settings -cnotmatch '^/(home|srv|opt)/[A-Za-z0-9_./-]+\.json$' -or
        $request.settings -cmatch '(^|/)\.\.(/|$)' -or $request.helperSha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $request.candidateBuildSha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $request.instanceId -cne $env:DOORHANDLE_ECS_INSTANCE_ID -or $request.machineId -cne $env:DOORHANDLE_ECS_MACHINE_ID) {
        throw 'Runtime observation request differs from this fixed candidate.'
    }
    $helper="$remoteRoot/releases/$tag/script/docker/compact-runtime-acceptance.py"
    $binding="--root '$remoteRoot' --runtime '$runtime' --tag '$tag' --commit '$($request.commit)' --source-sha256 '$($request.sourceSha256)' --instance-id '$($request.instanceId)' --machine-id '$($request.machineId)' --settings '$($request.settings)'"
    $command="test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$($request.helperSha256)' && python3 -B '$helper' observe $binding"
    for ($readback=1; $readback -le 3; $readback++) {
        $lines=@(& ssh.exe @sshOptions -p $portText $destination $command); $exit=$LASTEXITCODE
        $lines | Add-Content -LiteralPath artifacts/runtime-execution-observe.stdout.log -Encoding utf8
        if ($exit -eq 255) { if ($readback -lt 3) { Start-Sleep -Seconds 2 }; continue }
        if ($exit -notin @(0,1) -or $lines.Count -eq 0) { throw 'Original runtime is unresolved; retain its owned resources.' }
        $state=$lines[-1] | ConvertFrom-Json
        if ($state.operation -cne 'runtime-acceptance' -or $state.terminal -ne $true -or
            $state.executionId -cnotmatch '^[a-f0-9]{32}$' -or $state.release -cne $tag -or
            $state.commit -cne $request.commit -or $state.sourceSha256 -cne $request.sourceSha256 -or
            $state.candidateBuildSha256 -cne $request.candidateBuildSha256 -or
            $state.identity.instanceId -cne $request.instanceId -or $state.identity.machineId -cne $request.machineId -or
            $state.status -cnotin @('PASS','FAILED_OR_UNKNOWN') -or ($exit -eq 0 -and $state.status -cne 'PASS')) {
            throw 'Original runtime has no matching terminal result; retain its owned resources.'
        }
        $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath artifacts/runtime-execution-observation.json -Encoding utf8
        return $state
    }
    throw 'Cannot reconnect to the same runtime execution; do not cancel it through post cleanup.'
}
function Assert-ControlPreflight([string]$Commit,[string]$SourceSha) {
    if ($env:ACTION -cne 'verify-runtime' -and -not ($env:ACTION -ceq 'verify' -and $env:DOORHANDLE_CI_SCOPE -ceq 'mysql')) { return }
    if ($env:CI_CONTROL_PREFLIGHT_PASS -cne 'true') { throw 'Native verification requires the ECS control-script preflight first.' }
    $gate=Get-Content -LiteralPath artifacts/control-preflight-gate.json -Raw | ConvertFrom-Json
    $receipt=Get-Content -LiteralPath artifacts/control-preflight/receipt.json -Raw | ConvertFrom-Json
    $actual=(Get-FileHash -LiteralPath artifacts/control-preflight/receipt.json -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($gate.status -cne 'CONTROL_PREFLIGHT_PASS' -or $gate.receiptSha256 -cne $actual -or $gate.release -cne $tag -or $gate.commit -cne $Commit -or $gate.sourceSha256 -cne $SourceSha -or $receipt.status -cne 'CONTROL_PREFLIGHT_PASS' -or $receipt.release -cne $tag -or $receipt.commit -cne $Commit -or $receipt.sourceSha256 -cne $SourceSha -or $receipt.fullProjectVerified -ne $false -or $receipt.containerCleanupConfirmed -ne $true -or $receipt.sourceScratchCleanupConfirmed -ne $true) { throw 'The native control-script preflight lacks matching original evidence and cleanup.' }
}
function Assert-ControlSourcePackage($Package,[string]$Commit,[string]$SourceSha) {
    if ($env:ACTION -cne 'verify-controls') { return }
    if ($Package.kind -cne 'doorhandle-controls-only-source' -or $Package.action -cne 'verify-controls' -or $Package.release -cne $tag -or $Package.commit -cne $Commit -or $Package.sourceSha256 -cne $SourceSha) { throw 'Control verification requires its own full pinned-source package.' }
    $flags=@{controlsOnly=$true;maintenanceOnly=$false;testsExecuted=$false;applicationBuilt=$false;fullProjectVerified=$false}
    foreach ($name in $flags.Keys) {
        if ($Package.$name -isnot [bool] -or $Package.$name -ne $flags[$name]) { throw 'Control-only source metadata cannot authorize maintenance, application build or business verification.' }
    }
    if ((Test-Path -LiteralPath artifacts/application.jar) -or (Test-Path -LiteralPath artifacts/local-build.json)) { throw 'Control verification cannot use an application build artifact.' }
}
function Get-LocalArtifactsProfile {
    $selected = $env:LOCAL_ARTIFACTS_PROFILE
    if ([string]::IsNullOrWhiteSpace($selected)) { $selected = 'additional-local-artifacts-v1' }
    if ($selected -cnotin @('additional-local-artifacts-v1', 'residual-project-originals-v1', 'legacy-partial-transports-v1', 'remaining-business-records-v1')) { throw 'Unsupported fixed artifact profile.' }
    return $selected
}
function Get-PinnedSourceFile([string]$RelativePath) {
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    if ($RelativePath -notmatch '^script/[A-Za-z0-9_./-]+\.(py|sh)$' -or @($RelativePath.Split('/') | Where-Object { $_ -eq '..' }).Count) { throw 'Unsafe fixed-source helper path.' }
    # Git archive can apply checkout conversion too. Extract the actual archive
    # member bytes rather than assuming the Git blob or worktree has its EOLs.
    $archive = Join-Path (Get-Location) 'artifacts/source.tar.gz'
    $package = Get-Content -LiteralPath artifacts/release.json -Raw | ConvertFrom-Json
    if ($package.commit -ne $commit -or $package.sourceSha256 -ne (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()) { throw 'Fixed helper extraction requires the exact packaged source archive.' }
    $python = $env:LOCAL_PYTHON_EXE
    if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
    if (-not $python -or -not [System.IO.Path]::IsPathFullyQualified($python) -or -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Configure the existing local Python for byte-only source packaging.' }
    $sourceReader = @'
import sys,tarfile
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    if archive.pax_headers.get('comment') != sys.argv[2]: raise ValueError('Archive commit differs')
    entry=archive.getmember(sys.argv[3])
    if not entry.isfile() or not 0 < entry.size <= 32*1024**2: raise ValueError('Bounded source member required')
    with archive.extractfile(entry) as stream:
        content=stream.read(32*1024**2+1)
    if len(content) != entry.size: raise ValueError('Source member size differs')
    sys.stdout.buffer.write(content)
'@
    $directory = Join-Path (Join-Path (Get-Location) 'artifacts/pinned-source') ([guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $output = Join-Path $directory ([System.IO.Path]::GetFileName($RelativePath))
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $python
    $info.WorkingDirectory = (Get-Location).Path
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in @('-I', '-B', '-c', $sourceReader, $archive, $commit, $RelativePath)) { $info.ArgumentList.Add($argument) }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $info
    try {
        if (-not $process.Start()) { throw 'Cannot read the pinned Git source.' }
        $errorRead = $process.StandardError.ReadToEndAsync()
        $stream = [System.IO.File]::Open($output, [System.IO.FileMode]::CreateNew)
        try { $process.StandardOutput.BaseStream.CopyTo($stream) } finally { $stream.Dispose() }
        $process.WaitForExit()
        $null = $errorRead.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0 -or (Get-Item -LiteralPath $output).Length -eq 0) { throw 'The fixed Git source helper is missing.' }
    } finally { $process.Dispose() }
    return $output
}
function Get-BuildRegistryAssignment {
    $registry = $env:BUILD_NPM_REGISTRY
    if ([string]::IsNullOrWhiteSpace($registry)) { $registry = 'https://registry.npmjs.org' }
    if ($registry -notin @('https://registry.npmjs.org', 'https://registry.npmmirror.com')) { throw 'Unsupported npm build registry' }
    return "DOORHANDLE_BUILD_NPM_REGISTRY='$registry'"
}

function Send-CandidateBuildToolsArchive {
    param([ValidateSet('buildkit','qdrant','prometheus','alertmanager')][string]$Component='buildkit')
    if ($Component -ceq 'buildkit') {
        if ($env:ACTION -cnotin @('verify-runtime', 'compact-cutover') -or $env:DOORHANDLE_CI_SCOPE -cne 'mysql') { throw 'This action must not prepare candidate build inputs.' }
    } elseif ($env:ACTION -cnotin @('verify','verify-runtime','compact-cutover') -or $env:DOORHANDLE_CI_SCOPE -cnotin @('source','mysql')) { throw 'This action must not prepare middleware image inputs.' }
    $archiveField=if($Component -ceq 'buildkit'){'buildkitArchive'}else{'componentArchive'}
    $cacheFolder=if($Component -ceq 'buildkit'){'buildkit-v0.34.2'}else{$Component}
    $localFolder=if($Component -ceq 'buildkit'){$cacheFolder}else{'middleware/'+$Component}
    $python = $env:LOCAL_PYTHON_EXE
    if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
    if (-not $python -or -not [IO.Path]::IsPathFullyQualified($python) -or -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Configure the existing local Python for public build-input custody.' }
    $cacheRoot = $env:CANDIDATE_BUILD_INPUT_CACHE_ROOT
    if (-not $cacheRoot -or -not [IO.Path]::IsPathFullyQualified($cacheRoot) -or [IO.Path]::GetFullPath($cacheRoot).TrimEnd('\', '/') -ne [IO.Path]::GetFullPath('D:/AI/lunwen1/DoorHandleCatch/work/jenkins/build-deps')) { throw 'Candidate build inputs require the configured global D project cache.' }
    $record = [ordered]@{ schema=1; kind='doorhandle-public-build-input-transport'; release=$tag; commit=$commit; sourceSha256=$sha; status='FAILED'; rawArchiveArchived=$false }
    if($Component -cne 'buildkit'){$record.component=$Component}
    $attempt = [guid]::NewGuid().ToString('N'); $uploadAttempted = $false; $failed = $true
    $helper = Get-PinnedSourceFile 'script/jenkins/transfer-candidate-build-tools.py'
    $helperSha = (Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash.ToLowerInvariant()
    $remoteHelper = "$remoteInbox/transfer-candidate-build-tools.py"
    $transferArguments = $null
    try {
        $archive = if($Component -ceq 'buildkit'){$env:CANDIDATE_BUILD_TOOLS_ARCHIVE}else{$null}
        if ([string]::IsNullOrWhiteSpace($archive)) {
            $fetch = Get-PinnedSourceFile 'script/jenkins/fetch-buildkit-build-input.py'
            $resources = Get-PinnedSourceFile 'script/docker/compact-build-resources.py'
            $fetchOutput = Invoke-Checked $python @('-I', '-B', $fetch, '--component', $Component, '--resources-source', $resources, '--output-dir', (Join-Path $cacheRoot $localFolder))
            $fetched = ($fetchOutput | Select-Object -Last 1) | ConvertFrom-Json
            if ($fetched.status -cne 'PINNED_OCI_BUILD_INPUT_READY' -or -not [IO.Path]::IsPathFullyQualified($fetched.file)) { throw 'Pinned public OCI dependency download did not return its verified cache file.' }
            $archive = $fetched.file; $record.fetch = $fetched
        }
        $localOutput = Invoke-Checked $python @('-I', '-B', $helper, 'local', '--component', $Component, '--archive', $archive, '--local-root', $cacheRoot)
        $local = ($localOutput | Select-Object -Last 1) | ConvertFrom-Json
        if ($local.sha256 -cnotmatch '^[a-f0-9]{64}$' -or $local.fingerprintSha256 -cnotmatch '^[a-f0-9]{64}$' -or $local.bytes -le 0 -or $local.bytes -gt 134217728) { throw 'Local public build input lacks its bounded same-file custody.' }
        if ($record.Contains('fetch') -and ($record.fetch.sha256 -cne $local.sha256 -or $record.fetch.bytes -ne $local.bytes)) { throw 'Fetched public OCI archive changed before transfer admission.' }
        $expected = [ordered]@{ file="$remoteRoot/build-inputs/$cacheFolder/$($local.sha256).tar"; sha256=$local.sha256; bytes=[long]$local.bytes }
        $record.local = $local; $record[$archiveField] = $expected; $record.helperSha256 = $helperSha
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, $helper, "${destination}:$remoteHelper"))
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "test `"`$(sha256sum '$remoteHelper' | cut -d ' ' -f 1)`" = '$helperSha' && chmod 600 '$remoteHelper'"))
        $transferArguments = "--component '$Component' --root '$remoteRoot' --tag '$tag' --commit '$commit' --source-sha256 '$sha' --instance-id '$instance' --machine-id '$machine' --archive-sha256 '$($local.sha256)' --archive-bytes '$($local.bytes)' --attempt '$attempt'"
        $guard = "test `"`$(sha256sum '$remoteHelper' | cut -d ' ' -f 1)`" = '$helperSha' && python3 -I -B '$remoteHelper'"
        $uploadAttempted = $true
        $probeOutput = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "$guard probe $transferArguments"))
        $admitted = ($probeOutput | Select-Object -Last 1) | ConvertFrom-Json
        foreach ($field in @('file', 'sha256', 'bytes')) { if ($admitted.$archiveField.$field -cne $expected.$field) { throw 'Public build-input cache response differs from the declared bytes.' } }
        if (@($admitted.$archiveField.PSObject.Properties).Count -ne 3 -or $admitted.release -cne $tag -or $admitted.commit -cne $commit -or $admitted.sourceSha256 -cne $sha -or $admitted.identity.instanceId -cne $instance -or $admitted.identity.machineId -cne $machine -or $admitted.identity.executionLocation -cne 'ECS') { throw 'Public build-input cache belongs to another source or ECS.' }
        $record.admission = $admitted
        if ($admitted.status -ceq 'UPLOAD_REQUIRED') {
            if ($admitted.stagingFile -cne "$remoteInbox/.$Component-upload-$attempt/archive.tar") { throw 'Public build input upload escaped its unique inbox staging file.' }
            $beforeOutput = Invoke-Checked $python @('-I', '-B', $helper, 'local', '--component', $Component, '--archive', $archive, '--local-root', $cacheRoot)
            $before = ($beforeOutput | Select-Object -Last 1) | ConvertFrom-Json
            if ($before.sha256 -cne $local.sha256 -or $before.bytes -ne $local.bytes -or $before.fingerprintSha256 -cne $local.fingerprintSha256) { throw 'Local public build input changed before SCP.' }
            Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, $local.file, "${destination}:$($admitted.stagingFile)"))
            $afterOutput = Invoke-Checked $python @('-I', '-B', $helper, 'local', '--component', $Component, '--archive', $archive, '--local-root', $cacheRoot)
            $after = ($afterOutput | Select-Object -Last 1) | ConvertFrom-Json
            if ($after.sha256 -cne $local.sha256 -or $after.bytes -ne $local.bytes -or $after.fingerprintSha256 -cne $local.fingerprintSha256) { throw 'Local public build input changed during SCP.' }
            $publishedOutput = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "$guard publish $transferArguments"))
            $published = ($publishedOutput | Select-Object -Last 1) | ConvertFrom-Json
            if ($published.status -cne 'AVAILABLE' -or $published.release -cne $tag -or $published.commit -cne $commit -or $published.sourceSha256 -cne $sha) { throw 'Public build input publication did not complete for this source.' }
            foreach ($field in @('file', 'sha256', 'bytes')) { if ($published.$archiveField.$field -cne $expected.$field) { throw 'Published public build-input binding changed.' } }
            $record.publication = $published
        } elseif ($admitted.status -cne 'REUSED') { throw 'Public build-input cache admission did not return a known state.' }
        $record.status = 'AVAILABLE'; $failed = $false
        return $expected
    } finally {
        $cleanupFailed = $false
        if ($uploadAttempted) {
            try {
                $cleanupOutput = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "$guard cleanup $transferArguments"))
                $cleanup = ($cleanupOutput | Select-Object -Last 1) | ConvertFrom-Json
                if ($cleanup.status -cnotin @('NO_STAGE', 'REMOVED_OWNED_STAGING') -or $cleanup.release -cne $tag -or $cleanup.commit -cne $commit -or $cleanup.sourceSha256 -cne $sha) { throw 'Public build-input staging cleanup is unproved.' }
                $record.cleanup = $cleanup
            } catch { $cleanupFailed = $true; $record.status = 'FAILED'; $record.cleanupStatus = 'FAILED_OR_UNKNOWN' }
        }
        $transportFile=if($Component -ceq 'buildkit'){'artifacts/candidate-build-tools-transport.json'}else{'artifacts/'+$Component+'-image-input-transport.json'}
        $record | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $transportFile -Encoding utf8
        if ($cleanupFailed -and -not $failed) { throw 'Owned public build-input staging cleanup failed; shared cache and unknown files were retained.' }
    }
}

$nativeRetentionPolicy=$env:NATIVE_RETENTION_POLICY
if ([string]::IsNullOrWhiteSpace($nativeRetentionPolicy)) {$nativeRetentionPolicy='FailedNative'}
if ($nativeRetentionPolicy -cnotin @('FailedNative','RetiredCopies194','RetiredCopies203','PublicCaches221224235','DerivedMysql221222235238247','DerivedMysql250253256259264268','DerivedMysql281283','SourcePytest16','SourcePytest307308')) { throw 'Unsupported native retention policy.' }
if ($nativeRetentionPolicy -cne 'FailedNative' -and $env:ACTION -cne 'reclaim-build-outputs') { throw 'An explicit retired-copy policy requires source-only build maintenance.' }
$tag = Require-Value 'RELEASE_TAG' '^ci-[0-9]+-[a-f0-9]{12}$'
$failedNativeBuildNumber=[string]$env:FAILED_NATIVE_BUILD_NUMBER
$failedMysqlDataBuilds=[string]$env:FAILED_MYSQL_DATA_BUILDS
if ($failedMysqlDataBuilds -cne '') {
    if ($env:ACTION -cne 'reclaim-build-outputs' -or $nativeRetentionPolicy -cne 'FailedNative' -or
        $env:DOORHANDLE_FAILED_MYSQL_DATA_TASK_ID -cne '01a1a46b-d37a-7fb2-8638-afe345c73531' -or
        $failedMysqlDataBuilds -cnotmatch '\A[1-9][0-9]{0,8}(,[1-9][0-9]{0,8}){0,15}\z') { throw 'Failed MySQL data retirement requires the current task authorization and explicit maintenance selection.' }
    $dataNumbers=@($failedMysqlDataBuilds.Split(','))
    if (@($dataNumbers | Select-Object -Unique).Count -ne $dataNumbers.Count -or @($dataNumbers | Where-Object {[long]$_ -lt 287 -or [long]$_ -ge [long]$env:BUILD_NUMBER}).Count) { throw 'Only distinct earlier failed verification builds from this task are eligible.' }
}
if ($failedNativeBuildNumber -cne '') {
    if ($failedNativeBuildNumber -cnotmatch '\A[1-9][0-9]{0,8}\z') { throw 'Failed native build number must be a canonical ASCII positive integer with at most nine digits.' }
    if ($env:ACTION -cne 'reclaim-build-outputs' -or $nativeRetentionPolicy -cne 'FailedNative') { throw 'A failed native build selection requires the explicit FailedNative maintenance policy.' }
    $currentBuildNumber=Require-Value 'BUILD_NUMBER' '\A[1-9][0-9]*\z'
    if ($tag -cnotmatch '\Aci-[1-9][0-9]*-[a-f0-9]{12}\z') { throw 'Failed native build selection requires a canonical current release number.' }
    if ([long]$failedNativeBuildNumber -lt 221 -or [long]$failedNativeBuildNumber -ge [long]$currentBuildNumber -or [long]$failedNativeBuildNumber -ge [long]($tag.Split('-')[1])) { throw 'Select one failed native build from 221 up to, but excluding, the current build.' }
}
if ($env:ACTION -ceq 'reclaim-build-outputs') {
    if ($Action -cnotin @('PackageSourceOnly', 'ReclaimBuildOutputs') -or $env:CI_ECS_VERIFIED -cne 'false' -or $env:DOORHANDLE_CI_SCOPE -cne 'source') {
        throw 'Standalone build maintenance only packages pinned source and reclaims proven old outputs without a test PASS.'
    }
    foreach ($name in @('LEGACY_SOURCE_SNAPSHOT', 'LEGACY_SOURCE_ECS_SNAPSHOT', 'LOCAL_ARTIFACTS_SNAPSHOT', 'LOCAL_ARTIFACTS_ECS_SNAPSHOT', 'COLD_STORES_SNAPSHOT', 'COLD_STORES_ECS_SNAPSHOT', 'COLD_HISTORY_SNAPSHOT', 'COLD_HISTORY_ECS_SNAPSHOT', 'LOCAL_MYSQL_SNAPSHOT', 'LOCAL_MYSQL_ECS_SNAPSHOT', 'LOCAL_MYSQL_FIXTURE_SETTINGS', 'PROJECT_MYSQL_SNAPSHOT', 'PROJECT_MYSQL_MANIFEST_SHA256', 'PROJECT_MYSQL_ARCHIVE_SHA256', 'REMAINING_SYSTEM_DATA_SNAPSHOT', 'REMAINING_SYSTEM_DATA_ECS_SNAPSHOT', 'DOORHANDLE_CI_FIXTURE_MANIFEST', 'DOORHANDLE_CI_FIXTURE_SETTINGS', 'CANDIDATE_BUILD_TOOLS_ARCHIVE', 'COMPACT_CUTOVER_SETTINGS', 'COMPATIBLE_BACKEND_IMAGE', 'COMPATIBLE_RUNNER_IMAGE', 'REHEARSAL_MEMORY_EXTRACTION_MODEL')) {
        if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) { throw 'Standalone build maintenance cannot accept business, fixture, model or build-image inputs.' }
    }
    foreach ($name in @('DOORHANDLE_CI_AUTO_COMPACT_FIXTURES', 'PRODUCTION_RELEASE_ENABLED', 'DOORHANDLE_COMPACT_RELEASE_READY', 'DOORHANDLE_COMPACT_REHEARSAL_READY', 'REHEARSAL_KEEP')) {
        if ([Environment]::GetEnvironmentVariable($name) -ceq 'true') { throw 'Standalone build maintenance cannot enable fixtures or application release.' }
    }
} elseif ($Action -ceq 'PackageSourceOnly') { throw 'Source-only maintenance packaging requires the explicit reclaim-build-outputs action.' }
if ($env:ACTION -ceq 'verify-controls') {
    if ($Action -cnotin @('PackageControls','PrepareTools','Preflight','CleanupTools','CleanupGeneratedArtifacts') -or $env:CI_ECS_VERIFIED -cne 'false' -or $env:DOORHANDLE_CI_SCOPE -cne 'source') { throw 'Control verification only packages fixed source, prepares tools, runs the control preflight and cleans its tools.' }
    foreach ($name in @('LEGACY_SOURCE_SNAPSHOT','LEGACY_SOURCE_ECS_SNAPSHOT','LOCAL_ARTIFACTS_SNAPSHOT','LOCAL_ARTIFACTS_ECS_SNAPSHOT','COLD_STORES_SNAPSHOT','COLD_STORES_ECS_SNAPSHOT','COLD_HISTORY_SNAPSHOT','COLD_HISTORY_ECS_SNAPSHOT','LOCAL_MYSQL_SNAPSHOT','LOCAL_MYSQL_ECS_SNAPSHOT','LOCAL_MYSQL_FIXTURE_SETTINGS','PROJECT_MYSQL_SNAPSHOT','PROJECT_MYSQL_MANIFEST_SHA256','PROJECT_MYSQL_ARCHIVE_SHA256','REMAINING_SYSTEM_DATA_SNAPSHOT','REMAINING_SYSTEM_DATA_ECS_SNAPSHOT','DOORHANDLE_CI_FIXTURE_MANIFEST','DOORHANDLE_CI_FIXTURE_SETTINGS','CANDIDATE_BUILD_TOOLS_ARCHIVE','COMPACT_CUTOVER_SETTINGS','COMPATIBLE_BACKEND_IMAGE','COMPATIBLE_RUNNER_IMAGE','REHEARSAL_MEMORY_EXTRACTION_MODEL')) {
        if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) { throw 'Control verification cannot accept business, fixture, model or release inputs.' }
    }
    foreach ($name in @('DOORHANDLE_CI_AUTO_COMPACT_FIXTURES','PRODUCTION_RELEASE_ENABLED','DOORHANDLE_COMPACT_RELEASE_READY','DOORHANDLE_COMPACT_REHEARSAL_READY','REHEARSAL_KEEP')) {
        if ([Environment]::GetEnvironmentVariable($name) -ceq 'true') { throw 'Control verification cannot enable fixtures, application release or rehearsal.' }
    }
} elseif ($Action -ceq 'PackageControls') { throw 'Control-only source packaging requires the explicit verify-controls action.' }
if ($env:CANDIDATE_BUILD_TOOLS_ARCHIVE -and ($env:ACTION -cnotin @('verify-runtime', 'compact-cutover') -or $env:DOORHANDLE_CI_SCOPE -cne 'mysql')) {
    throw 'Candidate build input is only accepted by runtime verification or compact cutover.'
}
$projectSqlInputs=@('PROJECT_MYSQL_SNAPSHOT','PROJECT_MYSQL_MANIFEST_SHA256','PROJECT_MYSQL_ARCHIVE_SHA256')
$projectSqlSelected=@($projectSqlInputs | Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) })
if($projectSqlSelected.Count) {
    if($projectSqlSelected.Count -ne 3 -or $env:ACTION -cnotin @('verify','verify-runtime') -or
        $env:DOORHANDLE_CI_SCOPE -cne 'mysql' -or $env:PRODUCTION_RELEASE_ENABLED -ceq 'true' -or
        [string]::IsNullOrWhiteSpace($env:LOCAL_MYSQL_FIXTURE_SETTINGS) -or
        $env:PROJECT_MYSQL_MANIFEST_SHA256 -cnotmatch '^[a-f0-9]{64}$' -or $env:PROJECT_MYSQL_ARCHIVE_SHA256 -cnotmatch '^[a-f0-9]{64}$') {
        throw 'Project SQL custody requires all three sealed inputs, shared ECS image settings and archive-only complete MySQL verification.'
    }
}
if ($Action -eq 'Publish') {
    if ($env:PRODUCTION_RELEASE_ENABLED -ne 'true' -or $env:DOORHANDLE_COMPACT_RELEASE_READY -ne 'true') {
        throw 'Production publish/rollback is disabled until compact schema acceptance and release configuration are complete.'
    }
    if ($env:ACTION -notin @('verify-deploy', 'rollback')) { throw 'Publish requires verify-deploy or rollback.' }
}
if ($Action -eq 'Rehearse' -and $env:DOORHANDLE_COMPACT_REHEARSAL_READY -ne 'true') {
    throw 'The legacy rehearsal is disabled until its compact schema adapter is accepted.'
}
if ($Action -eq 'CompactCutover') {
    if ($env:ACTION -ne 'compact-cutover' -or $env:PRODUCTION_RELEASE_ENABLED -ne 'true' -or $env:DOORHANDLE_COMPACT_RELEASE_READY -ne 'true' -or $env:DOORHANDLE_CI_SCOPE -ne 'mysql' -or $env:CI_ECS_VERIFIED -ne 'true') {
        throw 'First compact cutover requires the accepted machine release gate and this build passing MySQL ECS verification.'
    }
    if ((-not $env:LOCAL_MYSQL_SNAPSHOT -and -not $env:LOCAL_MYSQL_ECS_SNAPSHOT) -or -not $env:LOCAL_MYSQL_FIXTURE_SETTINGS) {
        throw 'First compact cutover cannot omit the approved legacy MySQL recovery and source-inclusion audit.'
    }
    $legacyFiles = @('artifacts/local-mysql-source-classification.json', 'artifacts/local-mysql-source-classification-ci.json', 'artifacts/release.json')
    foreach ($legacyFile in $legacyFiles) {
        $legacyItem = Get-Item -LiteralPath $legacyFile -Force -ErrorAction Stop
        if ($legacyItem.PSIsContainer -or ($legacyItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $legacyItem.Length -le 0 -or $legacyItem.Length -gt 1MB) {
            throw 'First compact cutover requires bounded original classification controls from this build.'
        }
    }
    $legacyReport = Get-Content -LiteralPath $legacyFiles[0] -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 32
    $legacyBinding = Get-Content -LiteralPath $legacyFiles[1] -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 32
    $legacyRelease = Get-Content -LiteralPath $legacyFiles[2] -Raw -Encoding UTF8 | ConvertFrom-Json
    $legacyCommit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    if ($legacyBinding.kind -cne 'doorhandle-local-mysql-source-classification-ci' -or $legacyBinding.status -cne 'CLASSIFIED' -or
        $legacyRelease.commit -cne $legacyCommit -or $legacyBinding.commit -cne $legacyCommit -or
        $legacyRelease.release -cne $env:RELEASE_TAG -or
        $legacyBinding.release -cne $legacyRelease.release -or $legacyBinding.sourceSha256 -cne $legacyRelease.sourceSha256 -or
        $legacyReport.context.commit -cne $legacyCommit -or $legacyReport.context.release -cne $legacyRelease.release -or
        $legacyReport.context.sourceSha256 -cne $legacyRelease.sourceSha256 -or
        $legacyBinding.reportSha256 -cne (Get-FileHash -LiteralPath $legacyFiles[0] -Algorithm SHA256).Hash.ToLowerInvariant() -or
        $legacyBinding.identity.instanceId -cne $env:DOORHANDLE_ECS_INSTANCE_ID -or
        $legacyBinding.identity.machineId -cne $env:DOORHANDLE_ECS_MACHINE_ID -or
        $legacyReport.context.identity.instanceId -cne $env:DOORHANDLE_ECS_INSTANCE_ID -or
        $legacyReport.context.identity.machineId -cne $env:DOORHANDLE_ECS_MACHINE_ID -or
        ($legacyReport.perKeyReconciliation | ConvertTo-Json -Depth 32 -Compress) -cne
            ($legacyBinding.perKeyReconciliation | ConvertTo-Json -Depth 32 -Compress)) {
        throw 'Legacy MySQL audit differs from this fixed build, original report or ECS identity.'
    }
    foreach ($legacyControl in @($legacyReport, $legacyBinding)) {
        $legacyKeyProof = $legacyControl.perKeyReconciliation
        foreach ($legacyProofFlag in @('cutoverBlocked', 'legacyRowsPresentInSource', 'wholeMigrationAndRuntimeAcceptanceStillRequired', 'requiredBeforeCutover')) {
            if ($legacyKeyProof.$legacyProofFlag -isnot [bool]) { throw 'Legacy source-inclusion proof flags must be exact booleans.' }
        }
        if ($legacyKeyProof.scope -cne 'EXACT_TYPED_PRIMARY_KEYS_V1' -or $legacyKeyProof.gateScope -cne 'PER_KEY_SOURCE_INCLUSION_ONLY' -or
            $legacyKeyProof.status -cne 'RECONCILED' -or $legacyKeyProof.cutoverBlocked -ne $false -or
            $legacyKeyProof.legacyRowsPresentInSource -ne $true -or $legacyKeyProof.wholeMigrationAndRuntimeAcceptanceStillRequired -ne $true -or
            $legacyKeyProof.requiredBeforeCutover -ne $true) {
            throw 'Unresolved, conflicting or absent legacy MySQL rows block first production cutover.'
        }
        foreach ($legacyClaim in @('coverageVerified', 'targetDataCompared', 'productionMerged', 'retirementAllowed')) {
            if ($legacyControl.$legacyClaim -isnot [bool] -or $legacyControl.$legacyClaim -ne $false) {
                throw 'A source-inclusion audit cannot authorize migration completion or deletion of original data.'
            }
        }
    }
}
if ($Action -eq 'VerifyRuntime' -and ($env:ACTION -ne 'verify-runtime' -or $env:DOORHANDLE_CI_SCOPE -ne 'mysql' -or $env:CI_ECS_VERIFIED -ne 'true')) {
    throw 'Runtime acceptance requires this build passing the complete MySQL ECS verification.'
}
if ($Action -in @('VerifyRuntime', 'CompactCutover') -and $env:CI_LEGACY_CANDIDATE_PREPARED -ne 'true') {
    throw 'Runtime acceptance requires this fixed build preserved native data candidate.'
}
New-Item -ItemType Directory -Force -Path artifacts | Out-Null
if ($Action -ceq 'PackageSourceOnly') {
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $actualCommit = ((Invoke-Checked 'git.exe' @('rev-parse', 'HEAD')) | Select-Object -Last 1).Trim()
    if ($actualCommit -cne $commit -or -not $tag.EndsWith('-' + $commit.Substring(0, 12))) { throw 'Maintenance metadata must match this exact checked out commit and release tag.' }
    foreach ($file in @('artifacts/source.tar.gz', 'artifacts/release.json', 'artifacts/application.jar', 'artifacts/local-build.json')) {
        if (Test-Path -LiteralPath $file) { throw 'Maintenance packaging requires a fresh artifact directory without application build output.' }
    }
    Invoke-Checked 'git.exe' @('diff', '--quiet', 'HEAD', '--')
    $maintenancePaths = @('script/jenkins/cleanup-ecs-builds.py', 'script/jenkins/verify-remote.py', 'script/jenkins/retire-failed-native-jar-duplicates.py', 'script/docker/compact-build-resources.py')
    if ($nativeRetentionPolicy -cin @('DerivedMysql221222235238247','DerivedMysql250253256259264268','DerivedMysql281283')) {
        $maintenancePaths += 'script/jenkins/retire-derived-mysql-data.py'
    } elseif ($failedMysqlDataBuilds -cne '') {
        $maintenancePaths += 'script/jenkins/retire-derived-mysql-data.py'
    }
    if ($nativeRetentionPolicy -cin @('SourcePytest16','SourcePytest307308')) { $maintenancePaths += 'script/jenkins/retire-source-pytest.py' }
    $archiveArguments = @('-c', 'core.autocrlf=false', 'archive', '--format=tar.gz', '--output=artifacts/source.tar.gz', $commit) + $maintenancePaths
    Invoke-Checked 'git.exe' $archiveArguments
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    $record = [ordered]@{ schema = 1; kind = 'doorhandle-maintenance-source'; action = 'reclaim-build-outputs';
        release = $tag; commit = $commit; sourceSha256 = $sha; sourceBytes = (Get-Item -LiteralPath artifacts/source.tar.gz).Length;
        maintenanceOnly = $true; testsExecuted = $false; applicationBuilt = $false }
    $stream = [IO.File]::Open((Join-Path (Get-Location) 'artifacts/release.json'), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($record | ConvertTo-Json)); $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
    return
}
if ($Action -ceq 'PackageControls') {
    $commit=Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $actualCommit=((Invoke-Checked 'git.exe' @('rev-parse','HEAD'))|Select-Object -Last 1).Trim()
    if ($actualCommit -cne $commit -or -not $tag.EndsWith('-'+$commit.Substring(0,12))) { throw 'Control packaging must match the exact checked out commit and release tag.' }
    foreach ($file in @('artifacts/source.tar.gz','artifacts/release.json','artifacts/application.jar','artifacts/local-build.json')) {
        if (Test-Path -LiteralPath $file) { throw 'Control packaging requires fresh source metadata without application build output.' }
    }
    Invoke-Checked 'git.exe' @('diff','--quiet','HEAD','--')
    Invoke-Checked 'git.exe' @('-c','core.autocrlf=false','archive','--format=tar.gz','--output=artifacts/source.tar.gz',$commit)
    $sha=(Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    $record=[ordered]@{schema=1;kind='doorhandle-controls-only-source';action='verify-controls';release=$tag;commit=$commit;
        sourceSha256=$sha;sourceBytes=(Get-Item -LiteralPath artifacts/source.tar.gz).Length;
        controlsOnly=$true;maintenanceOnly=$false;testsExecuted=$false;applicationBuilt=$false;fullProjectVerified=$false}
    $stream=[IO.File]::Open((Join-Path (Get-Location) 'artifacts/release.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {$bytes=[Text.UTF8Encoding]::new($false).GetBytes(($record|ConvertTo-Json));$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)} finally {$stream.Dispose()}
    return
}
if ($Action -eq 'Package') {
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $actualCommit = ((Invoke-Checked 'git.exe' @('rev-parse', 'HEAD')) | Select-Object -Last 1).Trim()
    if ($actualCommit -ne $commit -or -not $tag.EndsWith('-' + $commit.Substring(0, 12))) {
        throw 'Package metadata must match the exact checked out commit and release tag.'
    }
    Invoke-Checked 'git.exe' @('diff', '--quiet', 'HEAD', '--')
    Invoke-Checked 'git.exe' @('-c', 'core.autocrlf=false', 'archive', '--format=tar.gz', '--output=artifacts/source.tar.gz', 'HEAD')
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    $build = Get-Content -LiteralPath artifacts/local-build.json -Raw | ConvertFrom-Json
    $jarSha = (Get-FileHash -LiteralPath artifacts/application.jar -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($build.status -ne 'PASS' -or $build.commit -ne $commit -or $build.release -ne $tag -or $build.testsExecuted -ne $false -or $build.applicationJarSha256 -ne $jarSha) {
        throw 'The application jar is not the successful local build of this pinned SCM commit.'
    }
    @{ release = $tag; commit = $commit; sourceSha256 = $sha; applicationJarSha256 = $jarSha;
       localBuildReceiptSha256 = (Get-FileHash -LiteralPath artifacts/local-build.json -Algorithm SHA256).Hash.ToLowerInvariant() } |
        ConvertTo-Json | Set-Content -LiteralPath artifacts/release.json -Encoding UTF8
    return
}

$targetHost = Require-Value 'DEPLOY_HOST' '^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$'
$portText = Require-Value 'DEPLOY_PORT' '^[0-9]{1,5}$'
if ([int]$portText -lt 1 -or [int]$portText -gt 65535) { throw 'Invalid SSH port' }
$remoteRoot = Require-Value 'REMOTE_ROOT' '^/(home|srv|opt)/[A-Za-z0-9_./-]+$'
$runtime = Require-Value 'REMOTE_RUNTIME' '^/(home|srv|opt)/[A-Za-z0-9_./-]+$'
foreach ($path in @($remoteRoot, $runtime)) { if ($path -match '(^|/)\.\.(/|$)' -or $path.EndsWith('/')) { throw 'Unsafe remote path' } }
$user = Require-Value 'DEPLOY_USER' '^[a-z_][a-z0-9_-]{0,31}$'
foreach ($name in @('DEPLOY_KEY', 'DEPLOY_KNOWN_HOSTS')) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if (-not $value -or -not (Test-Path -LiteralPath $value -PathType Leaf)) { throw "Missing Jenkins credential file: $name" }
}
# Jenkins temporary credentials inherit the workspace ACL on Windows. OpenSSH
# rejects keys readable by other local accounts, so restrict this temporary file
# to the identity executing this build before attempting authentication.
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$keyFile = Get-Item -LiteralPath $env:DEPLOY_KEY -Force
if ($keyFile.PSIsContainer -or ($keyFile.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { throw 'Jenkins SSH credential must be a regular file.' }
$sections = [System.Security.AccessControl.AccessControlSections]::Access -bor [System.Security.AccessControl.AccessControlSections]::Owner
$keyBefore = [System.IO.FileSystemAclExtensions]::GetAccessControl($keyFile, $sections)
if ($keyBefore.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $identity.Value) { throw 'Jenkins SSH credential is not owned by this build identity.' }
$keyAcl = [System.Security.AccessControl.FileSecurity]::new()
$keyAcl.SetAccessRuleProtection($true, $false)
$keyAcl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new($identity, 'FullControl', 'Allow'))
# Persist only Access; never request audit/SACL privilege from the local agent.
[System.IO.FileSystemAclExtensions]::SetAccessControl($keyFile, $keyAcl)
$keyObserved = [System.IO.FileSystemAclExtensions]::GetAccessControl($keyFile, $sections)
$keyRules = @($keyObserved.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
if (-not $keyObserved.AreAccessRulesProtected -or $keyRules.Count -ne 1 -or $keyRules[0].IdentityReference.Value -ne $identity.Value -or $keyRules[0].AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or $keyRules[0].FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl) {
    throw 'Jenkins SSH credential owner-only access could not be verified.'
}
$sshOptions = @('-i', $env:DEPLOY_KEY, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlias=doorhandle-bj', '-o', "UserKnownHostsFile=$env:DEPLOY_KNOWN_HOSTS", '-o', 'ConnectTimeout=12', '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3')
if ($env:SSH_TRANSPORT -eq 'tls') {
    foreach ($name in @('OPENSSL_EXE', 'SSH_TLS_CA_FILE')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if (-not $value -or -not (Test-Path -LiteralPath $value -PathType Leaf)) { throw "Missing TLS transport file: $name" }
        if ($value.Contains('"') -or $value.Contains("`n") -or $value.Contains("`r")) { throw "Invalid TLS path: $name" }
    }
    $openssl = (Resolve-Path -LiteralPath $env:OPENSSL_EXE).Path.Replace('\', '/')
    $tlsCa = (Resolve-Path -LiteralPath $env:SSH_TLS_CA_FILE).Path.Replace('\', '/')
    $tlsProxy = 'ProxyCommand="{0}" s_client -quiet -verify_quiet -connect %h:%p -servername doorhandle-ssh.local -CAfile "{1}" -verify_return_error -verify_hostname doorhandle-ssh.local' -f $openssl, $tlsCa
    $sshOptions += @('-o', $tlsProxy)
} elseif ($env:SSH_TRANSPORT -ne 'direct') { throw 'SSH_TRANSPORT must be tls or direct' }
$destination = "$user@$targetHost"
if ($env:GENERATED_RETENTION_MANIFEST -and $env:GENERATED_ARTIFACTS_ONLY -cne 'true') { throw 'A generated retirement manifest requires generated-only maintenance.' }
if ($env:GENERATED_ARTIFACTS_ONLY -ceq 'true' -and ($env:ACTION -cne 'reclaim-build-outputs' -or -not $env:GENERATED_RETENTION_MANIFEST)) { throw 'Generated-only maintenance requires its explicit action and approved manifest.' }
if ($Action -ceq 'CleanupGeneratedArtifacts') {
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    & ./script/jenkins/reclaim-build-outputs.ps1 -Mode Terminal -GeneratedArtifacts -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha
    return
}
if ($Action -ceq 'ReclaimBuildOutputs' -and $env:ACTION -ceq 'reclaim-build-outputs') {
    # Admission and fresh exclusive remote directories belong to the maintenance
    # controller. Do not execute the generic mkdir or a test preflight first.
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($env:GENERATED_ARTIFACTS_ONLY -ceq 'true') {
        if ($nativeRetentionPolicy -cne 'FailedNative' -or $failedMysqlDataBuilds -cne '' -or $failedNativeBuildNumber -cne '') { throw 'Generated-only maintenance cannot invoke unrelated retirement policies.' }
        & ./script/jenkins/reclaim-build-outputs.ps1 -Mode Maintenance -GeneratedArtifacts -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha
        return
    }
    if ($nativeRetentionPolicy -cin @('SourcePytest16','SourcePytest307308')) {
        & ./script/jenkins/retire-source-pytest.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha
        return
    }
    & ./script/jenkins/reclaim-build-outputs.ps1 -Mode Maintenance -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha
    if ($nativeRetentionPolicy -cin @('DerivedMysql221222235238247','DerivedMysql250253256259264268','DerivedMysql281283')) {
        $derivedHelper = Get-PinnedSourceFile 'script/jenkins/retire-derived-mysql-data.py'
        & ./script/jenkins/retire-derived-mysql-data.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha -PinnedHelper $derivedHelper
    } elseif ($nativeRetentionPolicy -ceq 'PublicCaches221224235') {
        & ./script/jenkins/retire-failed-native-jar-duplicates.ps1 -Mode Maintenance -CanonicalBatch PublicCaches -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha
    } elseif ($nativeRetentionPolicy -ceq 'RetiredCopies194') {
        & ./script/jenkins/retire-failed-native-jar-duplicates.ps1 -Mode Maintenance -CanonicalBatch RetiredCopies -RetiredCopyBatch retired-187-188-189 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha
    } elseif ($nativeRetentionPolicy -ceq 'RetiredCopies203') {
        & ./script/jenkins/retire-failed-native-jar-duplicates.ps1 -Mode Maintenance -CanonicalBatch RetiredCopies -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha
    } else {
        if ($failedMysqlDataBuilds -ceq '' -or $failedNativeBuildNumber -cne '') {
            & ./script/jenkins/retire-failed-native-jar-duplicates.ps1 -Mode Maintenance -CanonicalBatch FailedNative -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha -FailedNativeBuildNumber $failedNativeBuildNumber
        }
        if ($failedMysqlDataBuilds -cne '') {
            $derivedHelper = Get-PinnedSourceFile 'script/jenkins/retire-derived-mysql-data.py'
            & ./script/jenkins/retire-derived-mysql-data.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha -PinnedHelper $derivedHelper -FailedBuildNumbers $failedMysqlDataBuilds
        }
    }
    return
}
if ($Action -eq 'Preflight') {
    if ($env:ACTION -cin @('verify','verify-runtime','verify-controls')) {
        $expectedScope=if ($env:ACTION -ceq 'verify-controls') {'source'} else {'mysql'}
        if ($env:CI_TOOLS_PREPARED -cne 'true' -or $env:DOORHANDLE_CI_SCOPE -cne $expectedScope) { throw 'Control preflight requires this fixed build prepared ECS tools and its explicit verification scope.' }
        $commit=Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
        $instance=Require-Value 'DOORHANDLE_ECS_INSTANCE_ID' '^i-[a-z0-9]+$'
        $machine=Require-Value 'DOORHANDLE_ECS_MACHINE_ID' '^[a-f0-9]{32}$'
        $sha=(Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
        $package=Get-Content -LiteralPath artifacts/release.json -Raw | ConvertFrom-Json
        Assert-ControlSourcePackage $package $commit $sha
        $tools=Get-Content -LiteralPath artifacts/ecs-tool-runtime.json -Raw | ConvertFrom-Json
        $remoteInbox="$remoteRoot/inbox/$tag"
        if ($package.release -cne $tag -or $package.commit -cne $commit -or $package.sourceSha256 -cne $sha -or $tools.status -cne 'PREPARED' -or $tools.release -cne $tag -or $tools.manifest -cne "$remoteInbox/tool-runtime/manifest.json" -or $tools.manifestSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Control preflight source or tool registration differs from this fixed build.' }
        if (Test-Path -LiteralPath artifacts/control-preflight) { throw 'Use a fresh build; control-preflight evidence already exists.' }
        New-Item -ItemType Directory -Path artifacts/control-preflight | Out-Null
        foreach ($relative in @('script/jenkins/control-preflight.py','script/jenkins/verify-remote.py')) {
            $inputFile=Get-PinnedSourceFile $relative
            $name=if ($relative -ceq 'script/jenkins/verify-remote.py') {'control-verify-remote.py'} else {[IO.Path]::GetFileName($relative)}
            Invoke-Checked 'scp.exe' ($sshOptions+@('-P',$portText,$inputFile,"${destination}:$remoteInbox/$name"))
        }
        Invoke-Checked 'ssh.exe' ($sshOptions+@('-p',$portText,$destination,"chmod 600 '$remoteInbox/control-preflight.py' '$remoteInbox/control-verify-remote.py'"))
        $helper="$remoteInbox/control-preflight.py"
        $fixedHelper=Get-PinnedSourceFile 'script/jenkins/control-preflight.py'
        $helperSha=(Get-FileHash -LiteralPath $fixedHelper -Algorithm SHA256).Hash.ToLowerInvariant()
        $command="test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$helperSha' && python3 -I -B '$helper' --root '$remoteRoot' --tag '$tag' --commit '$commit' --source-sha256 '$sha' --instance-id '$instance' --machine-id '$machine' --tool-manifest-sha256 '$($tools.manifestSha256)'"
        $controlRequest=@{release=$tag;commit=$commit;sourceSha256=$sha;helperSha256=$helperSha;toolManifestSha256=$tools.manifestSha256;instanceId=$instance;machineId=$machine}
        $controlRequest | ConvertTo-Json | Set-Content -LiteralPath artifacts/control-preflight/execution-request.json -Encoding utf8
        $PSNativeCommandUseErrorActionPreference=$false
        $controlExit=$null; $originalControlExit=$null; $collected=$false
        try {
            $lines=@(& ssh.exe @sshOptions -p $portText $destination $command 2> artifacts/control-preflight/transport.stderr.log)
            $controlExit=$LASTEXITCODE
            $originalControlExit=$controlExit
            $lines | Set-Content -LiteralPath artifacts/control-preflight/transport.stdout.log -Encoding utf8
            $remoteResult=$null
            try { $remoteResult=($lines|Select-Object -Last 1)|ConvertFrom-Json } catch { $remoteResult=$null }
            if ($controlExit -eq 255) {
                Write-Host 'Control preflight SSH disconnected; observing the same original execution before collection or cleanup.'
                $remoteResult=Wait-ExistingControlPreflight
                $controlExit=if ($remoteResult.status -ceq 'CONTROL_PREFLIGHT_PASS') {0} else {2}
            } elseif ($controlExit -in @(0,2) -and $null -ne $remoteResult) {
                Assert-ControlExecutionState $remoteResult $controlRequest
                $remoteResult | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath artifacts/control-preflight/execution-observation.json -Encoding utf8
            } else { throw 'Control preflight has no authenticated terminal result; retain its tools.' }
            if ($remoteResult.status -ceq 'CONTROL_PREFLIGHT_REJECTED') { throw 'Control preflight rejected before complete evidence; native preparation is blocked.' }
            $remoteOutput="$remoteInbox/control-preflight/output"
            Invoke-Checked 'scp.exe' ($sshOptions+@('-P',$portText,"${destination}:$remoteOutput/receipt.json",'artifacts/control-preflight/receipt.json'))
            $file=Get-Item -LiteralPath artifacts/control-preflight/receipt.json
            if ($file.Length -le 0 -or $file.Length -gt 2MB -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Control receipt is missing, oversized or redirected.' }
            $receipt=Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json -Depth 20
            if ($null -ne $remoteResult -and $remoteResult.receiptSha256 -cmatch '^[a-f0-9]{64}$' -and (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne $remoteResult.receiptSha256) { throw 'Original control receipt changed during collection.' }
            if ($receipt.kind -cne 'doorhandle-control-preflight' -or $receipt.release -cne $tag -or $receipt.commit -cne $commit -or $receipt.sourceSha256 -cne $sha -or $receipt.identity.instanceId -cne $instance -or $receipt.identity.machineId -cne $machine -or $receipt.toolManifestSha256 -cne $tools.manifestSha256) { throw 'Control receipt belongs to another source, build, tool image or ECS.' }
            foreach ($entry in $receipt.reports.PSObject.Properties) {
                $name=$entry.Name; $binding=$entry.Value
                $maximum=if ($name -cin @('python.xml','control-scratch-recovery.json')) {2MB} elseif ($name -ceq 'pytest.log') {8MB} else {throw 'Control report escaped its fixed catalog.'}
                if ($binding.file -cne $name -or $binding.bytes -lt 0 -or $binding.bytes -gt $maximum -or $binding.sha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Control report lacks bounded original byte identity.' }
                $local="artifacts/control-preflight/$name"
                Invoke-Checked 'scp.exe' ($sshOptions+@('-P',$portText,"${destination}:$remoteOutput/$name",$local))
                if ((Get-Item -LiteralPath $local).Length -ne $binding.bytes -or (Get-FileHash -LiteralPath $local -Algorithm SHA256).Hash.ToLowerInvariant() -cne $binding.sha256) { throw 'Control report changed during collection.' }
            }
            $collected=$true
        } finally {
            @{status=$(if($collected -and $controlExit -eq 0){'COLLECTED'}else{'FAILED_OR_UNKNOWN'});release=$tag;commit=$commit;sourceSha256=$sha;originalExitCode=$originalControlExit;exitCode=$controlExit;transportRecovered=($originalControlExit -eq 255 -and $collected);receiptCollected=$collected;fullProjectVerified=$false} | ConvertTo-Json | Set-Content -LiteralPath artifacts/control-preflight/transport.json -Encoding utf8
        }
        $expected=@('test_source_pytest_retirement','test_source_pytest307308_retirement','test_jenkins_resource_budget','test_jenkins_fixture_admission','test_jenkins_fixture_cgroup_probe','test_derived_mysql_retirement','test_jenkins_ecs_build_cleanup','test_generated_artifact_lifecycle','test_failed_native_jar_duplicates','test_historical_builder_retirement','test_historical_mysql_fixture_retirement','test_public_buildkit_layer_retirement','test_generated_public_image_archive_retirement','test_historical_python_build_cache_retirement','test_local_artifact_custody','test_compose_container_selection','test_local_fixed_originals_retirement','test_fixed_originals_attestation','test_local_mysql_custody','test_local_mysql_source_classification','test_project_mysql_custody','test_jenkins_suite_evidence','test_jenkins_evidence_recollection','test_jenkins_maven_dependency_cache','test_compact_schema_source','test_control_preflight','test_middleware_fixture','test_observability_fixture','test_semantic_mysql_fixture')
        if ($controlExit -ne 0 -or $null -eq $remoteResult -or $remoteResult.status -cne 'CONTROL_PREFLIGHT_PASS' -or $remoteResult.receipt -cne "$remoteOutput/receipt.json" -or $remoteResult.receiptSha256 -cnotmatch '^[a-f0-9]{64}$' -or $receipt.status -cne 'CONTROL_PREFLIGHT_PASS' -or $receipt.fullProjectVerified -ne $false -or $receipt.businessRuntimeStarted -ne $false -or $receipt.containerCleanupConfirmed -ne $true -or $receipt.sourceScratchCleanupConfirmed -ne $true -or (@($receipt.selectedModules|Sort-Object)-join ',') -cne (@($expected|Sort-Object)-join ',') -or (@($receipt.modules.PSObject.Properties.Name|Sort-Object)-join ',') -cne (@($expected|Sort-Object)-join ',') -or -not (Test-Path -LiteralPath artifacts/control-preflight/python.xml) -or -not (Test-Path -LiteralPath artifacts/control-preflight/pytest.log)) { throw 'ECS control-script preflight did not pass with complete reports and owned cleanup; native preparation is blocked.' }
        foreach ($module in $expected) { $counts=$receipt.modules.$module; if ($counts.passed -lt 1 -or $counts.failed -ne 0 -or $counts.skipped -ne 0) { throw 'Control preflight omitted or failed a required module.' } }
        @{status='CONTROL_PREFLIGHT_PASS';release=$tag;commit=$commit;sourceSha256=$sha;receiptSha256=(Get-FileHash -LiteralPath artifacts/control-preflight/receipt.json -Algorithm SHA256).Hash.ToLowerInvariant();fullProjectVerified=$false} | ConvertTo-Json | Set-Content -LiteralPath artifacts/control-preflight-gate.json -Encoding utf8
        return
    }
    Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "test -r '$runtime/deploy/cloud.env' && docker info --format '{{.ServerVersion}}' && docker compose version --short"))
    return
}

$remoteInbox = "$remoteRoot/inbox/$tag"
Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "umask 077; mkdir -p '$remoteInbox'"))
if ($Action -eq 'VerifyEmbedding') {
    if ($env:ACTION -ne 'verify-embedding' -or $env:CI_TOOLS_PREPARED -ne 'true' -or $env:DOORHANDLE_CI_SCOPE -ne 'source') { throw 'Embedding component verification requires its explicit source-only action and fixed tools.' }
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $instance = Require-Value 'DOORHANDLE_ECS_INSTANCE_ID' '^i-[a-z0-9]+$'
    $machine = Require-Value 'DOORHANDLE_ECS_MACHINE_ID' '^[a-f0-9]{32}$'
    $null = Require-Value 'SILICONFLOW_EMBEDDING_API_KEY' '^sk-[A-Za-z0-9_-]{20,}$'
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    $registration = Get-Content -LiteralPath artifacts/ecs-tool-runtime.json -Raw | ConvertFrom-Json
    $helper = Get-PinnedSourceFile 'script/jenkins/verify-free-embedding.py'
    $helperSha = (Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash.ToLowerInvariant()
    foreach ($item in @(@($helper, 'verify-free-embedding.py'), @((Get-PinnedSourceFile 'script/jenkins/verify-remote.py'), 'verify-remote.py'))) {
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, $item[0], "${destination}:$remoteInbox/$($item[1])"))
    }
    $remoteKey = "$remoteInbox/embedding.key"
    $reports = "$remoteInbox/embedding-verification/reports"
    $runFailed = $false
    try {
        # Transfer the credential on SSH stdin. It is never a command argument,
        # a local workspace file, a public receipt, or a Jenkins artifact.
        $info = [System.Diagnostics.ProcessStartInfo]::new()
        $info.FileName = (Get-Command ssh.exe -CommandType Application | Select-Object -First 1).Source
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        foreach ($argument in ($sshOptions + @('-p', $portText, $destination, "umask 077; set -C; cat > '$remoteKey'"))) { $info.ArgumentList.Add($argument) }
        $process = [System.Diagnostics.Process]::new(); $process.StartInfo = $info
        try {
            if (-not $process.Start()) { throw 'Cannot transfer the private embedding credential.' }
            $errorRead = $process.StandardError.ReadToEndAsync()
            $outputRead = $process.StandardOutput.ReadToEndAsync()
            $process.StandardInput.Write($env:SILICONFLOW_EMBEDDING_API_KEY)
            $process.StandardInput.Close()
            if (-not $process.WaitForExit(30000)) { $process.Kill(); throw 'Embedding secret transfer timed out.' }
            $null = $errorRead.GetAwaiter().GetResult(); $null = $outputRead.GetAwaiter().GetResult()
            if ($process.ExitCode -ne 0) { throw 'Embedding secret transfer failed.' }
        } finally { $process.Dispose() }
        $arguments = "--root '$remoteRoot' --runtime '$runtime' --tag '$tag' --commit '$commit' --source-sha256 '$sha' --instance-id '$instance' --machine-id '$machine' --key '$remoteKey' --tool-manifest-sha256 '$($registration.manifestSha256)'"
        try {
            Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "test `"`$(sha256sum '$remoteInbox/verify-free-embedding.py' | cut -d ' ' -f 1)`" = '$helperSha' && python3 -B '$remoteInbox/verify-free-embedding.py' verify $arguments"))
        } catch { $runFailed = $true }
        New-Item -ItemType Directory -Path artifacts/embedding -Force | Out-Null
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$reports/receipt.json", 'artifacts/embedding/receipt.json'))
        $proof = Get-Content -LiteralPath artifacts/embedding/receipt.json -Raw | ConvertFrom-Json
        if ($proof.kind -ne 'doorhandle-free-embedding-verification' -or $proof.release -ne $tag -or $proof.commit -ne $commit -or $proof.sourceSha256 -ne $sha -or $proof.identity.instanceId -ne $instance -or $proof.identity.machineId -ne $machine -or $proof.identity.executionLocation -ne 'ECS' -or $proof.originalRuntimeChanged -ne $false -or $proof.productionReleaseAllowed -ne $false) { throw 'Embedding evidence belongs to another component, source or ECS.' }
        foreach ($entry in $proof.reportFiles) {
            if ($entry.path -notin @('python.xml', 'verification.log', 'live-result.json', 'recovery-result.json') -or $entry.sha256 -notmatch '^[a-f0-9]{64}$' -or $entry.bytes -lt 1 -or $entry.bytes -gt 33554432) { throw 'Embedding report escaped its public evidence catalog.' }
            $target = 'artifacts/embedding/' + $entry.path
            Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$reports/$($entry.path)", $target))
            if ((Get-Item -LiteralPath $target).Length -ne $entry.bytes -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw 'Original embedding evidence changed during collection.' }
        }
        if ($runFailed -or $proof.status -ne 'PASS' -or $proof.ownedCleanup -ne 'STOPPED' -or $proof.componentTests -lt 86 -or $proof.live.model -cne 'BAAI/bge-m3' -or $proof.live.providerRequests -ne 3 -or $proof.live.dimensions -ne 1024 -or $proof.live.paidFallbacks -ne 0 -or $proof.recovery.status -ne 'PASS' -or $proof.recovery.providerRequests -ne 0) { throw 'Free embedding component acceptance did not pass with its complete original evidence.' }
        if ($proof.nextReleaseEnvironment.status -ne 'PREPARED_FOR_NEXT_RELEASE' -or $proof.nextReleaseEnvironment.originalBackupRetained -ne $true -or $proof.nextReleaseEnvironment.liveActivationPerformed -ne $false) { throw 'Next release embedding configuration was not privately prepared and backed up.' }
    } finally {
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "rm -f -- '$remoteKey'; test ! -e '$remoteKey'"))
    }
    return
}
if ($Action -eq 'RepairPriorEvidence') {
    if ($env:CI_ECS_VERIFIED -ne 'true') { throw 'Prior evidence permission repair requires this fixed commit ECS verification first.' }
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    # Only the original profile has registered historical permission repairs.
    $additionalForRepair = ''
    if ((Get-LocalArtifactsProfile) -ceq 'additional-local-artifacts-v1') { $additionalForRepair = $env:LOCAL_ARTIFACTS_ECS_SNAPSHOT }
    & ./script/jenkins/repair-ci-evidence-permissions.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha -LegacySnapshot $env:LEGACY_SOURCE_ECS_SNAPSHOT -AdditionalSnapshot $additionalForRepair
    return
}
if ($Action -eq 'PreserveLegacy') {
    if ($env:CI_ECS_VERIFIED -ne 'true') { throw 'Original source preservation requires this fixed commit ECS source verification first.' }
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    & ./script/jenkins/preserve-legacy-input.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha -SnapshotDirectory $env:LEGACY_SOURCE_SNAPSHOT -EcsSnapshotDirectory $env:LEGACY_SOURCE_ECS_SNAPSHOT
    return
}
if ($Action -eq 'CleanupLocalMySql') {
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    & ./script/jenkins/preserve-local-mysql.ps1 -Mode Cleanup -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha
    return
}
if ($Action -in @('PreserveProjectMySql','CleanupProjectMySql')) {
    if($env:CI_ECS_VERIFIED -cne 'true' -or $projectSqlSelected.Count -ne 3) { throw 'Project SQL recovery requires this fixed build complete ECS verification and sealed inputs.' }
    $commit=Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $sha=(Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    $mode=if($Action -ceq 'CleanupProjectMySql'){'Cleanup'}else{'Preserve'}
    & ./script/jenkins/preserve-project-mysql.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha -SnapshotDirectory $env:PROJECT_MYSQL_SNAPSHOT -ManifestSha256 $env:PROJECT_MYSQL_MANIFEST_SHA256 -ArchiveSha256 $env:PROJECT_MYSQL_ARCHIVE_SHA256 -FixtureSettings $env:LOCAL_MYSQL_FIXTURE_SETTINGS -Mode $mode
    return
}
if ($Action -in @('PreserveLocalArtifacts', 'PreserveRemainingArtifacts', 'PreserveColdStores', 'PreserveLocalMySql', 'ReclaimBuildOutputs')) {
    if ($env:CI_ECS_VERIFIED -ne 'true') { throw 'Original data retention and build reclamation require this fixed commit ECS verification first.' }
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Action -eq 'PreserveLocalArtifacts') {
        $artifactProfile = Get-LocalArtifactsProfile
        $profileOptions = @{}
        if ($artifactProfile -cne 'additional-local-artifacts-v1') { $profileOptions['Profile'] = $artifactProfile }
        & ./script/jenkins/preserve-local-artifacts.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha -SnapshotDirectory $env:LOCAL_ARTIFACTS_SNAPSHOT -EcsSnapshotDirectory $env:LOCAL_ARTIFACTS_ECS_SNAPSHOT @profileOptions
    } elseif ($Action -eq 'PreserveRemainingArtifacts') {
        & ./script/jenkins/preserve-local-artifacts.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha -SnapshotDirectory $env:REMAINING_SYSTEM_DATA_SNAPSHOT -EcsSnapshotDirectory $env:REMAINING_SYSTEM_DATA_ECS_SNAPSHOT -Profile 'remaining-system-data-v1'
    } elseif ($Action -eq 'PreserveColdStores') {
        & ./script/jenkins/preserve-cold-stores.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha -SnapshotDirectory $env:COLD_STORES_SNAPSHOT -EcsSnapshotDirectory $env:COLD_STORES_ECS_SNAPSHOT -Profile $env:COLD_STORES_PROFILE
    } elseif ($Action -eq 'PreserveLocalMySql') {
        & ./script/jenkins/preserve-local-mysql.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha -SnapshotDirectory $env:LOCAL_MYSQL_SNAPSHOT -EcsSnapshotDirectory $env:LOCAL_MYSQL_ECS_SNAPSHOT -FixtureSettings $env:LOCAL_MYSQL_FIXTURE_SETTINGS
    } else {
        & ./script/jenkins/reclaim-build-outputs.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha
        if ($env:DOORHANDLE_CI_SCOPE -ceq 'source') {
            & ./script/jenkins/retire-failed-native-jar-duplicates.ps1 -Mode Verified -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha
        }
    }
    return
}
if ($Action -in @('PrepareLegacyCandidate', 'CleanupLegacyCandidate')) {
    if ($env:CI_ECS_VERIFIED -ne 'true' -or $env:DOORHANDLE_CI_SCOPE -ne 'mysql' -or $env:ACTION -notin @('verify-runtime', 'compact-cutover')) {
        throw 'Native data candidate preparation requires the complete fixed-source MySQL verification.'
    }
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $instance = Require-Value 'DOORHANDLE_ECS_INSTANCE_ID' '^i-[a-z0-9]+$'
    $machine = Require-Value 'DOORHANDLE_ECS_MACHINE_ID' '^[a-f0-9]{32}$'
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    $pinnedHelper = Get-PinnedSourceFile 'script/jenkins/prepare-legacy-candidate.py'
    $helperSha = (Get-FileHash -LiteralPath $pinnedHelper -Algorithm SHA256).Hash.ToLowerInvariant()
    $helper = "$remoteRoot/verification/$tag/checkout/script/jenkins/prepare-legacy-candidate.py"
    $helperGuard = "test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$helperSha' && "
    $arguments = "--root '$remoteRoot' --tag '$tag' --commit '$commit' --source-sha256 '$sha' --instance-id '$instance' --machine-id '$machine'"
    if ($Action -eq 'PrepareLegacyCandidate') {
        $settingsName = if ($env:DOORHANDLE_CI_FIXTURE_SETTINGS) { 'DOORHANDLE_CI_FIXTURE_SETTINGS' } else { 'COMPACT_CUTOVER_SETTINGS' }
        $settings = Require-Value $settingsName '^/(home|srv|opt)/[A-Za-z0-9_./-]+\.json$'
        if ($settings -match '(^|/)\.\.(/|$)') { throw 'Unsafe private ECS candidate settings path.' }
        $preservation = Get-Content -LiteralPath artifacts/legacy-source-preservation.json -Raw | ConvertFrom-Json
        if ($preservation.status -ne 'RESTORED_VERIFIED' -or $preservation.release -ne $tag -or $preservation.commit -ne $commit -or $preservation.sourceSha256 -ne $sha -or $preservation.identity.instanceId -ne $instance -or $preservation.identity.machineId -ne $machine) {
            throw 'Native data candidate requires this exact build byte-preserved and independently recovered legacy inputs.'
        }
        if ($preservation.profile -cne 'legacy-stores-with-windows-mcp-and-kafka-v1' -or $preservation.kafkaFiles -ne 309 -or $preservation.kafkaBytes -ne 1184990233 -or $preservation.archiveEncoding -cne 'TAR_GZIP' -or $preservation.legacyKafkaReplay -cne 'NOT_PERFORMED') {
            throw 'Complete runtime acceptance requires the full old Kafka log archive without replaying it.'
        }
        $output = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "${helperGuard}python3 -B '$helper' run $arguments --dimension 1024 --runtime '$runtime' --settings '$settings'"))
        $prepared = ($output | Select-Object -Last 1) | ConvertFrom-Json
        if ($prepared.status -ne 'PREPARED' -or $prepared.release -ne $tag -or $prepared.commit -ne $commit -or $prepared.sourceSha256 -ne $sha -or $prepared.identity.instanceId -ne $instance -or $prepared.identity.machineId -ne $machine -or $prepared.identity.executionLocation -ne 'ECS' -or $prepared.descriptorSha256 -notmatch '^[a-f0-9]{64}$' -or $prepared.ragManifestSha256 -notmatch '^[a-f0-9]{64}$' -or $prepared.publicSummarySha256 -notmatch '^[a-f0-9]{64}$' -or $prepared.legacyRagRecords -ne 83 -or $prepared.modelCallsPerformed -ne $true -or $prepared.paidModelCalls -ne 0 -or $prepared.llmCalls -ne 0 -or $prepared.legacyMem0MergedRecords -ne 30 -or $prepared.embeddingProfile -cne 'siliconflow-bge-m3-v1' -or $prepared.candidateSemanticVerified -ne $false -or $prepared.productionDataMaterialized -ne $false -or $prepared.productionPromotionAllowed -ne $false) {
            throw 'Native data candidate does not prove fixed-source preservation without paid calls or promotion.'
        }
        # This public summary contains only counts, hashes and status. Private
        # source text, per-record inventories and candidate paths stay on ECS.
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/verification/$tag/checkout/work/legacy-candidate/public-summary.json", 'artifacts/legacy-candidate.json'))
        $summaryFile = Get-Item -LiteralPath artifacts/legacy-candidate.json
        if ($summaryFile.Length -le 0 -or $summaryFile.Length -gt 262144 -or (Get-FileHash -LiteralPath $summaryFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $prepared.publicSummarySha256) { throw 'Native candidate public evidence changed during collection.' }
        $summary = Get-Content -LiteralPath $summaryFile.FullName -Raw | ConvertFrom-Json
        foreach ($key in @('status', 'release', 'commit', 'sourceSha256', 'descriptorSha256', 'ragManifestSha256', 'legacyRagRecords', 'modelCallsPerformed', 'paidModelCalls', 'llmCalls', 'legacyMem0MergedRecords', 'embeddingProfile', 'candidateSemanticVerified', 'productionDataMaterialized', 'productionPromotionAllowed')) {
            if ($summary.$key -cne $prepared.$key) { throw 'Native candidate public evidence differs from its actual execution response.' }
        }
        if ($summary.identity.instanceId -ne $instance -or $summary.identity.machineId -ne $machine -or $summary.identity.executionLocation -ne 'ECS') { throw 'Native data candidate public evidence belongs to another execution host.' }
    } else {
        $output = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "${helperGuard}python3 -B '$helper' cleanup $arguments"))
        $cleanup = ($output | Select-Object -Last 1) | ConvertFrom-Json
        if ($cleanup.status -notin @('STOPPED', 'NO_RESOURCES') -or $cleanup.release -ne $tag -or $cleanup.sourceVolumesPreserved -ne $true) { throw 'Native candidate owned helper cleanup is incomplete.' }
        $cleanup | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath artifacts/legacy-candidate-cleanup.json -Encoding utf8
        if ($cleanup.hasPublicSummary -eq $true) {
            if ($cleanup.publicSummarySha256 -notmatch '^[a-f0-9]{64}$') { throw 'Native data candidate outcome lacks an actual evidence digest.' }
            Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/verification/$tag/checkout/work/legacy-candidate/public-summary.json", 'artifacts/legacy-candidate-outcome.json'))
            $file = Get-Item -LiteralPath artifacts/legacy-candidate-outcome.json
            if ($file.Length -le 0 -or $file.Length -gt 262144 -or (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $cleanup.publicSummarySha256) { throw 'Native candidate final outcome changed during collection.' }
            $outcome = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
            if ($outcome.status -notin @('PREPARED', 'FAILED') -or $outcome.release -ne $tag -or $outcome.commit -ne $commit -or $outcome.sourceSha256 -ne $sha -or $outcome.identity.instanceId -ne $instance -or $outcome.identity.machineId -ne $machine -or $outcome.paidModelCalls -ne 0 -or $outcome.llmCalls -ne 0 -or $outcome.productionPromotionAllowed -ne $false) { throw 'Native candidate final outcome belongs to another build or data policy.' }
        }
    }
    return
}
if ($Action -in @('PrepareTools', 'CleanupTools')) {
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $instance = Require-Value 'DOORHANDLE_ECS_INSTANCE_ID' '^i-[a-z0-9]+$'
    $machine = Require-Value 'DOORHANDLE_ECS_MACHINE_ID' '^[a-f0-9]{32}$'
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    $package = Get-Content -LiteralPath artifacts/release.json -Raw | ConvertFrom-Json
    Assert-ControlSourcePackage $package $commit $sha
    if ($package.release -ne $tag -or $package.commit -ne $commit -or $package.sourceSha256 -ne $sha) { throw 'Tool preparation requires this build pinned source package.' }
    $executor = "$remoteInbox/ecs-tool-runtime.py"
    if ($Action -eq 'PrepareTools') {
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "test ! -e '$remoteInbox/source.tar.gz' && mkdir '$remoteInbox/.tools-upload'"))
        foreach ($item in @(@('artifacts/source.tar.gz','source.tar.gz'), @('script/jenkins/prepare-ecs-tools.py','prepare-ecs-tools.py'), @('script/jenkins/ecs-tool-runtime.py','ecs-tool-runtime.py'))) {
            $inputFile = if ($item[0].StartsWith('script/')) { Get-PinnedSourceFile $item[0] } else { $item[0] }
            Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, $inputFile, "${destination}:$remoteInbox/$($item[1])"))
        }
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "chmod 600 '$remoteInbox/source.tar.gz' '$remoteInbox/prepare-ecs-tools.py' '$executor'"))
        $arguments = "--root '$remoteRoot' --tag '$tag' --commit '$commit' --source-sha256 '$sha' --instance-id '$instance' --machine-id '$machine'"
        $prepareArguments = $arguments
        if ($env:ACTION -cin @('verify','verify-runtime','compact-cutover') -and $env:DOORHANDLE_CI_SCOPE -cin @('source','mysql')) {
            foreach($component in @('qdrant','prometheus','alertmanager')) {
                $null=Send-CandidateBuildToolsArchive -Component $component
            }
        }
        $buildkitBinding = $null
        if ($env:ACTION -in @('verify-runtime', 'compact-cutover')) {
            $buildkitBinding = Send-CandidateBuildToolsArchive
            $prepareArguments += " --prepare-candidate-builder --buildkit-archive '$($buildkitBinding.file)' --buildkit-archive-sha256 '$($buildkitBinding.sha256)' --buildkit-archive-bytes '$($buildkitBinding.bytes)'"
        }
        $prepareCommand = "python3 -B '$remoteInbox/prepare-ecs-tools.py' $prepareArguments"
        $prepareTransport = [ordered]@{
            schema=1; kind='doorhandle-ecs-tool-preparation-transport'; release=$tag; commit=$commit; sourceSha256=$sha
            instanceId=$instance; machineId=$machine; prepareCandidateBuilder=($env:ACTION -in @('verify-runtime', 'compact-cutover'))
            originalExitCode=$null; finalExitCode=$null; readbacks=@(); readbackAttempts=0
            maximumReadbacks=3; recoveryWindowSeconds=180; readbackIntervalSeconds=60; recoveryElapsedSeconds=0
            transportRecovered=$false; status='FAILED'; failureReason=$null
        }
        if ($null -ne $buildkitBinding) { $prepareTransport.buildkitArchive = $buildkitBinding }
        $prepareFirstOut = 'artifacts/ecs-tool-preparation-first.stdout.log'
        $prepareFirstErr = 'artifacts/ecs-tool-preparation-first.stderr.log'
        $prepareRecoveryTimer = $null
        try {
            $prepareSshArguments = $sshOptions + @('-p', $portText, $destination, $prepareCommand)
            & 'ssh.exe' @prepareSshArguments 1> $prepareFirstOut 2> $prepareFirstErr
            $prepareExit = $LASTEXITCODE
            $prepareTransport.originalExitCode = $prepareExit
            $prepareTransport.finalExitCode = $prepareExit
            $prepareOutput = $prepareFirstOut
            $prepareRecovered = $false
            if ($prepareExit -eq 255) {
                Write-Host 'ECS preparation SSH disconnected; retaining its output and reading only the same attempt evidence.'
                $prepareRecoveryTimer = [Diagnostics.Stopwatch]::StartNew()
                for ($prepareReadback = 1; $prepareReadback -le 3; $prepareReadback++) {
                    if ($prepareReadback -gt 1) {
                        $prepareWait = [Math]::Min(60, [Math]::Max(0, 180 - $prepareRecoveryTimer.Elapsed.TotalSeconds))
                        if ($prepareWait -gt 0) { Start-Sleep -Seconds $prepareWait }
                    }
                    if ($prepareRecoveryTimer.Elapsed.TotalSeconds -ge 180) { $prepareTransport.failureReason = 'DEADLINE_EXCEEDED'; break }
                    $prepareReadOut = "artifacts/ecs-tool-preparation-readback-$prepareReadback.stdout.log"
                    $prepareReadErr = "artifacts/ecs-tool-preparation-readback-$prepareReadback.stderr.log"
                    $prepareReadArguments = $sshOptions + @('-p', $portText, $destination, "$prepareCommand --read-prepared")
                    $prepareReadProcess = [Diagnostics.Process]::new()
                    $prepareReadProcess.StartInfo = [Diagnostics.ProcessStartInfo]::new('ssh.exe')
                    $prepareReadProcess.StartInfo.UseShellExecute = $false
                    $prepareReadProcess.StartInfo.CreateNoWindow = $true
                    $prepareReadProcess.StartInfo.RedirectStandardOutput = $true
                    $prepareReadProcess.StartInfo.RedirectStandardError = $true
                    foreach ($prepareReadArgument in $prepareReadArguments) { $prepareReadProcess.StartInfo.ArgumentList.Add([string]$prepareReadArgument) }
                    $prepareReadOutStream = [IO.File]::Create((Join-Path (Get-Location).Path $prepareReadOut))
                    $prepareReadErrStream = [IO.File]::Create((Join-Path (Get-Location).Path $prepareReadErr))
                    $prepareReadStarted = $false; $prepareReadDeadline = $false; $prepareReadExit = $null
                    try {
                        $prepareReadStarted = $prepareReadProcess.Start()
                        if (-not $prepareReadStarted) { throw 'Could not start the local preparation evidence reader.' }
                        $prepareReadCopies = [Threading.Tasks.Task[]]@(
                            $prepareReadProcess.StandardOutput.BaseStream.CopyToAsync($prepareReadOutStream),
                            $prepareReadProcess.StandardError.BaseStream.CopyToAsync($prepareReadErrStream)
                        )
                        $prepareReadRemaining = [int][Math]::Max(0, [Math]::Floor((180 - $prepareRecoveryTimer.Elapsed.TotalSeconds) * 1000))
                        if ($prepareReadRemaining -le 0 -or -not $prepareReadProcess.WaitForExit($prepareReadRemaining)) {
                            $prepareReadDeadline = $true
                        } else {
                            $prepareReadExit = $prepareReadProcess.ExitCode
                            $prepareReadRemaining = [int][Math]::Max(0, [Math]::Floor((180 - $prepareRecoveryTimer.Elapsed.TotalSeconds) * 1000))
                            if ($prepareReadRemaining -le 0 -or -not [Threading.Tasks.Task]::WaitAll($prepareReadCopies, $prepareReadRemaining)) { $prepareReadDeadline = $true }
                        }
                        if ($prepareRecoveryTimer.Elapsed.TotalSeconds -ge 180) { $prepareReadDeadline = $true }
                    } finally {
                        if ($prepareReadStarted) {
                            if (-not $prepareReadProcess.HasExited) {
                                try { $prepareReadProcess.Kill($true) } catch [InvalidOperationException] { if (-not $prepareReadProcess.HasExited) { throw } }
                                $null = $prepareReadProcess.WaitForExit(1000)
                            }
                            if ($prepareReadProcess.HasExited) { $prepareReadExit = $prepareReadProcess.ExitCode }
                            $prepareReadProcess.StandardOutput.Dispose(); $prepareReadProcess.StandardError.Dispose()
                        }
                        $prepareReadOutStream.Dispose(); $prepareReadErrStream.Dispose(); $prepareReadProcess.Dispose()
                    }
                    $prepareTransport.finalExitCode = $prepareReadExit
                    $prepareTransport.readbackAttempts = $prepareReadback
                    $prepareReadOutSha = (Get-FileHash -LiteralPath $prepareReadOut -Algorithm SHA256).Hash.ToLowerInvariant()
                    $prepareReadErrSha = (Get-FileHash -LiteralPath $prepareReadErr -Algorithm SHA256).Hash.ToLowerInvariant()
                    $prepareReadDeadline = $prepareReadDeadline -or $prepareRecoveryTimer.Elapsed.TotalSeconds -ge 180
                    $prepareReadOutcome = if ($prepareReadDeadline) { 'DEADLINE_EXCEEDED' } else { switch ($prepareReadExit) { 0 { 'VALIDATED' }; 75 { 'PENDING' }; 255 { 'DISCONNECTED' }; default { 'FAILED' } } }
                    $prepareTransport.readbacks += [ordered]@{
                        attempt=$prepareReadback; exitCode=$prepareReadExit; outcome=$prepareReadOutcome; deadlineExceeded=$prepareReadDeadline
                        elapsedSeconds=[Math]::Round($prepareRecoveryTimer.Elapsed.TotalSeconds, 3)
                        stdoutFile=$prepareReadOut; stdoutSha256=$prepareReadOutSha
                        stderrFile=$prepareReadErr; stderrSha256=$prepareReadErrSha
                    }
                    if ($prepareReadDeadline -or $prepareRecoveryTimer.Elapsed.TotalSeconds -ge 180) {
                        $prepareTransport.failureReason = 'DEADLINE_EXCEEDED'
                        throw 'The preparation evidence readback exceeded its 180-second recovery window; the original SSH exit was 255.'
                    }
                    if ($prepareReadExit -eq 0) { $prepareOutput = $prepareReadOut; $prepareRecovered = $true; break }
                    if ($prepareReadExit -notin @(75, 255)) { throw "ECS preparation evidence readback failed with exit $prepareReadExit; the original SSH exit was 255." }
                }
                if (-not $prepareRecovered) { throw 'ECS preparation evidence was not verified within three readbacks and the 180-second recovery window; the original SSH exit was 255.' }
            } elseif ($prepareExit -ne 0) {
                throw "ssh.exe failed with exit $prepareExit"
            }
            $result = Get-Content -LiteralPath $prepareOutput -Encoding utf8
            $prepared = ($result | Select-Object -Last 1) | ConvertFrom-Json
            if ($prepared.status -ne 'PREPARED' -or $prepared.release -ne $tag -or $prepared.commit -ne $commit -or $prepared.sourceSha256 -ne $sha) { throw 'ECS tool image preparation did not return matching source evidence.' }
            foreach ($image in @($prepared.mavenImageId, $prepared.nodeImageId, $prepared.pythonImageId)) {
                if ($image -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Prepared ECS tools require immutable image IDs.' }
            }
            if ($env:ACTION -in @('verify-runtime', 'compact-cutover')) {
                $builder = $prepared.PSObject.Properties['candidateBuilderTools']
                if (-not $builder -or $builder.Value.status -ne 'PREPARED' -or $builder.Value.file -ne "$remoteInbox/candidate-build-tools/tools.json" -or $builder.Value.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Candidate BuildKit was not automatically prepared for this fixed attempt.' }
                $archiveBinding = $prepared.PSObject.Properties['buildkitArchive']
                if (-not $archiveBinding -or @($archiveBinding.Value.PSObject.Properties).Count -ne 3) { throw 'Prepared candidate tools omitted their exact public OCI input binding.' }
                foreach ($field in @('file', 'sha256', 'bytes')) { if ($archiveBinding.Value.$field -cne $buildkitBinding.$field) { throw 'Prepared candidate tools used another public OCI input.' } }
            }
            $prepareTransport.transportRecovered = $prepareRecovered
            $prepareTransport.status = 'PREPARED'
        } finally {
            if ($null -ne $prepareRecoveryTimer) { $prepareTransport.recoveryElapsedSeconds = [Math]::Round($prepareRecoveryTimer.Elapsed.TotalSeconds, 3) }
            foreach ($prepareStream in @(@('stdout', $prepareFirstOut), @('stderr', $prepareFirstErr))) {
                if (Test-Path -LiteralPath $prepareStream[1] -PathType Leaf) {
                    $prepareTransport[$prepareStream[0] + 'File'] = $prepareStream[1]
                    $prepareTransport[$prepareStream[0] + 'Sha256'] = (Get-FileHash -LiteralPath $prepareStream[1] -Algorithm SHA256).Hash.ToLowerInvariant()
                }
            }
            $prepareTransport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath artifacts/ecs-tool-preparation-transport.json -Encoding utf8
        }
        $prepared | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath artifacts/ecs-tool-preparation.json -Encoding utf8
        $result = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "python3 -B '$executor' prepare $arguments --maven-image '$($prepared.mavenImageId)' --node-image '$($prepared.nodeImageId)' --python-image '$($prepared.pythonImageId)'"))
        $registered = ($result | Select-Object -Last 1) | ConvertFrom-Json
        if ($registered.status -ne 'PREPARED' -or $registered.release -ne $tag -or $registered.manifest -ne "$remoteInbox/tool-runtime/manifest.json" -or $registered.manifestSha256 -notmatch '^[a-f0-9]{64}$') { throw 'ECS tool registration differs from the fixed build inbox.' }
        $registered | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath artifacts/ecs-tool-runtime.json -Encoding utf8
    } else {
        if (Test-Path -LiteralPath artifacts/control-preflight/execution-request.json) { $null=Wait-ExistingControlPreflight }
        if (Test-Path -LiteralPath artifacts/runtime-execution-request.json) { $null=Wait-ExistingRuntime }
        if (Test-Path -LiteralPath artifacts/ecs-verification-request.json) { $null=Wait-ExistingVerification }
        $result = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "python3 -B '$executor' cleanup --manifest '$remoteInbox/tool-runtime/manifest.json'"))
        $stopped = ($result | Select-Object -Last 1) | ConvertFrom-Json
        if ($stopped.status -ne 'STOPPED' -or $stopped.release -ne $tag -or @($stopped.remaining).Count -ne 0) { throw 'Owned tool containers did not stop.' }
        $stopped | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath artifacts/ecs-tool-cleanup.json -Encoding utf8
    }
    return
}
if ($Action -in @('PrepareFixtures', 'CleanupFixtures')) {
    if ($env:DOORHANDLE_CI_SCOPE -ne 'mysql' -or $env:DOORHANDLE_CI_AUTO_COMPACT_FIXTURES -ne 'true') { throw 'Automatic compact fixtures require explicit MySQL verification scope.' }
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $instance = Require-Value 'DOORHANDLE_ECS_INSTANCE_ID' '^i-[a-z0-9]+$'
    $machine = Require-Value 'DOORHANDLE_ECS_MACHINE_ID' '^[a-f0-9]{32}$'
    $settings = Require-Value 'DOORHANDLE_CI_FIXTURE_SETTINGS' '^/(home|srv|opt)/[A-Za-z0-9_./-]+\.json$'
    if ($settings -match '(^|/)\.\.(/|$)') { throw 'Unsafe private fixture settings path.' }
    $package = Get-Content -LiteralPath artifacts/release.json -Raw | ConvertFrom-Json
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($package.release -ne $tag -or $package.commit -ne $commit -or $package.sourceSha256 -ne $sha) { throw 'Fixture preparation requires this build pinned source package.' }
    $helper = "$remoteInbox/prepare-compact-fixtures.py"
    $arguments = "--root '$remoteRoot' --tag '$tag' --commit '$commit' --source-sha256 '$sha' --instance-id '$instance' --machine-id '$machine' --settings '$settings'"
    if ($Action -eq 'PrepareFixtures') {
        Assert-ControlPreflight $commit $sha
        $jarSha = (Get-FileHash -LiteralPath artifacts/application.jar -Algorithm SHA256).Hash.ToLowerInvariant()
        $jarBytes = (Get-Item -LiteralPath artifacts/application.jar).Length
        if ($package.applicationJarSha256 -ne $jarSha) { throw 'Fixture migration jar differs from the fixed commit build.' }
        @{ schema=1; kind='doorhandle-compact-fixture-artifacts'; release=$tag; commit=$commit;
           sourceSha256=$sha; applicationJarSha256=$jarSha; applicationJarBytes=$jarBytes } |
            ConvertTo-Json | Set-Content -LiteralPath artifacts/fixture-build-artifacts.json -Encoding utf8
        if ($env:CI_TOOLS_PREPARED -ne 'true') { throw 'Prepare fixed ECS tools before automatic fixtures.' }
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "test -f '$remoteInbox/source.tar.gz' && mkdir '$remoteInbox/.fixture-upload' && test `"`$(sha256sum '$remoteInbox/source.tar.gz' | cut -d ' ' -f 1)`" = '$sha'"))
        foreach ($item in @(@('artifacts/application.jar','application.jar'),
                            @('artifacts/fixture-build-artifacts.json','build-artifacts.json'), @('script/jenkins/prepare-compact-fixtures.py','prepare-compact-fixtures.py'))) {
            $inputFile = if ($item[0].StartsWith('script/')) { Get-PinnedSourceFile $item[0] } else { $item[0] }
            Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, $inputFile, "${destination}:$remoteInbox/$($item[1])"))
        }
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "chmod 600 '$remoteInbox/source.tar.gz' '$remoteInbox/application.jar' '$remoteInbox/build-artifacts.json' '$helper'"))
        $result = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "python3 -B '$helper' prepare $arguments"))
        $safe = ($result | Select-Object -Last 1) | ConvertFrom-Json
        $manifest = "$remoteRoot/verification/$tag/checkout/work/compact-fixtures/manifest.json"
        if ($safe.status -ne 'PREPARED' -or $safe.commit -ne $commit -or $safe.release -ne $tag -or $safe.manifest -ne $manifest) { throw 'Fixture preparation receipt differs from this pinned source and staging directory.' }
        $safe | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath artifacts/fixture-preparation.json -Encoding utf8
    } else {
        if (Test-Path -LiteralPath artifacts/runtime-execution-request.json) { $null=Wait-ExistingRuntime }
        $result = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "python3 -B '$helper' cleanup $arguments"))
        $safe = ($result | Select-Object -Last 1) | ConvertFrom-Json
        if ($safe.status -ne 'STOPPED' -or $safe.commit -ne $commit -or $safe.release -ne $tag) { throw 'Owned test resources did not stop with a matching cleanup receipt.' }
        $safe | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath artifacts/fixture-cleanup.json -Encoding utf8
    }
    return
}
if ($Action -eq 'VerifyEcs') {
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $instance = Require-Value 'DOORHANDLE_ECS_INSTANCE_ID' '^i-[a-z0-9]+$'
    $machine = Require-Value 'DOORHANDLE_ECS_MACHINE_ID' '^[a-f0-9]{32}$'
    $scope = $env:DOORHANDLE_CI_SCOPE
    if ([string]::IsNullOrWhiteSpace($scope)) { $scope = 'source' }
    if ($scope -notin @('source', 'mysql')) { throw 'DOORHANDLE_CI_SCOPE must be source or mysql.' }
    $fixture = $env:DOORHANDLE_CI_FIXTURE_MANIFEST
    if ($scope -eq 'mysql') {
        if ([string]::IsNullOrWhiteSpace($fixture) -or $fixture -notmatch '^/(home|srv|opt)/[A-Za-z0-9_./-]+\.json$' -or $fixture -match '(^|/)\.\.(/|$)') {
            throw 'MySQL verification requires an explicit private ECS fixture manifest path.'
        }
    } elseif (-not [string]::IsNullOrWhiteSpace($fixture)) { throw 'A fixture manifest requires the mysql verification scope.' }
    $python = $env:LOCAL_PYTHON_EXE
    if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
    if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Configure the existing LOCAL_PYTHON_EXE (or PYTHON_EXE) for evidence validation.' }
    $package = Get-Content -LiteralPath artifacts/release.json -Raw | ConvertFrom-Json
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($package.release -ne $tag -or $package.commit -ne $commit -or $package.sourceSha256 -ne $sha) { throw 'The immutable source package metadata differs.' }
    Assert-ControlPreflight $commit $sha
    if (Test-Path -LiteralPath artifacts/ecs) { throw 'Use a fresh build artifacts directory; existing ECS evidence is retained.' }
    New-Item -ItemType Directory -Path artifacts/ecs | Out-Null
    $attempt = [guid]::NewGuid().ToString('N')
    # Claim the upload once before SCP; a retry with an unknown result must use a new build.
    if ($env:CI_FIXTURES_PREPARED -eq 'true' -or $env:CI_TOOLS_PREPARED -eq 'true') {
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "test -f '$remoteInbox/source.tar.gz' && mkdir '$remoteInbox/.verification-upload' && test `"`$(sha256sum '$remoteInbox/source.tar.gz' | cut -d ' ' -f 1)`" = '$sha'"))
    } else {
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "test ! -e '$remoteInbox/source.tar.gz' && mkdir '$remoteInbox/.verification-upload'"))
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'artifacts/source.tar.gz', "${destination}:$remoteInbox/source.tar.gz"))
    }
    $verifyHelper = Get-PinnedSourceFile 'script/jenkins/verify-remote.py'
    $verifyHelperSha = (Get-FileHash -LiteralPath $verifyHelper -Algorithm SHA256).Hash.ToLowerInvariant()
    Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "test ! -e '$remoteInbox/verify-remote.py' && test ! -L '$remoteInbox/verify-remote.py'"))
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, $verifyHelper, "${destination}:$remoteInbox/verify-remote.py"))
    $sealVerifier = @'
import hashlib,json,os,stat,sys
from pathlib import Path
path=Path(sys.argv[1]); expected=sys.argv[2]
def need(value):
    if not value: raise ValueError('Fixed verification helper admission failed')
need(path.is_absolute() and path.resolve(strict=True)==path)
for parent in path.parents:
    need(not parent.is_symlink())
with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
    before=os.fstat(stream.fileno())
    need(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and before.st_nlink==1)
    need(0<before.st_size<=1024**2)
    need(hashlib.sha256(stream.read(1024**2+1)).hexdigest()==expected)
    after=os.fstat(stream.fileno())
    need((before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns))
    os.fchmod(stream.fileno(),0o600)
    sealed=os.fstat(stream.fileno()); linked=path.lstat()
    need(stat.S_IMODE(sealed.st_mode)==0o600 and sealed.st_ino==linked.st_ino and sealed.st_dev==linked.st_dev)
print(json.dumps({'status':'SEALED','file':'verify-remote.py','sha256':expected,'mode':'0600','uid':os.getuid()}))
'@
    $sealArguments = $sshOptions + @('-p', $portText, $destination, "python3 -B - '$remoteInbox/verify-remote.py' '$verifyHelperSha'")
    $sealResult = $sealVerifier | & 'ssh.exe' @sealArguments
    if ($LASTEXITCODE -ne 0) { throw 'The fixed verification helper could not be admitted with private permissions.' }
    $sealedVerifier = ($sealResult | Select-Object -Last 1) | ConvertFrom-Json
    if ($sealedVerifier.status -ne 'SEALED' -or $sealedVerifier.sha256 -ne $verifyHelperSha -or $sealedVerifier.mode -ne '0600') { throw 'The admitted verification helper differs from the pinned source.' }
    $sealedVerifier | ConvertTo-Json | Set-Content -LiteralPath artifacts/ecs-verifier-admission.json -Encoding utf8
    $manifestFlag = if ($scope -eq 'mysql') { " --fixture-manifest '$fixture'" } else { '' }
    @{ release=$tag;commit=$commit;sourceSha256=$sha;attempt=$attempt;scope=$scope;
       instanceId=$instance;machineId=$machine;helperSha256=$verifyHelperSha } |
        ConvertTo-Json | Set-Content -LiteralPath artifacts/ecs-verification-request.json -Encoding utf8
    $remoteCommand = "python3 -B '$remoteInbox/verify-remote.py' --root '$remoteRoot' --tag '$tag' --source-sha256 '$sha' --commit '$commit' --instance-id '$instance' --machine-id '$machine' --scope '$scope' --attempt '$attempt'$manifestFlag"
    $verifyExit = 1
    try {
        $verifyArguments = $sshOptions + @('-p', $portText, $destination, $remoteCommand)
        & 'ssh.exe' @verifyArguments
        $verifyExit = $LASTEXITCODE
    } catch {
        if ($LASTEXITCODE) { $verifyExit = $LASTEXITCODE }
    }
    if ($verifyExit -eq 255) {
        $observed=Wait-ExistingVerification
        $verifyExit=if ($observed.status -ceq 'PASS' -and $observed.evidenceReady) { 0 } else { 1 }
    }
    $collected = $false
    try {
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteInbox/verification-evidence.tar.gz", 'artifacts/ecs/verification-evidence.tar.gz'))
        Invoke-Checked $python @('-B', 'script/jenkins/verify-remote.py', 'collect',
            '--archive', 'artifacts/ecs/verification-evidence.tar.gz', '--output', 'artifacts/ecs/evidence',
            '--tag', $tag, '--source-sha256', $sha, '--commit', $commit, '--instance-id', $instance,
            '--machine-id', $machine, '--scope', $scope, '--attempt', $attempt)
        $collected = $true
    } catch {
        Write-Host 'ECS evidence is unavailable, incomplete or failed validation; retained remote evidence is not removed.'
    }
    if ($verifyExit -ne 0) { throw "ECS verification failed (exit $verifyExit); any collected evidence is retained." }
    if (-not $collected) { throw 'ECS verification cannot pass without this exact attempt evidence.' }
    $verified = Get-Content -LiteralPath artifacts/ecs/evidence/verification-receipt.json -Raw | ConvertFrom-Json
    if ($verified.status -ne 'PASS' -or $verified.verificationExitCode -ne 0 -or $verified.attempt -ne $attempt -or $verified.commit -ne $commit -or $verified.sourceSha256 -ne $sha -or $verified.identity.instanceId -ne $instance -or $verified.identity.machineId -ne $machine) {
        throw 'Collected ECS verification receipt is not a passing result for this source and admitted host.'
    }
    Write-Host 'ECS verification passed; source, execution identity and bounded evidence were validated. ECS lifecycle remains external.'
    return
}
if ($Action -in @('CompactCutover', 'VerifyRuntime', 'CleanupRuntime')) {
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $instance = Require-Value 'DOORHANDLE_ECS_INSTANCE_ID' '^i-[a-z0-9]+$'
    $machine = Require-Value 'DOORHANDLE_ECS_MACHINE_ID' '^[a-f0-9]{32}$'
    $settingsName = if ($env:DOORHANDLE_CI_FIXTURE_SETTINGS) { 'DOORHANDLE_CI_FIXTURE_SETTINGS' } else { 'COMPACT_CUTOVER_SETTINGS' }
    $settings = Require-Value $settingsName '^/(home|srv|opt)/[A-Za-z0-9_./-]+\.json$'
    if ($settings -match '(^|/)\.\.(/|$)') { throw 'Unsafe private ECS cutover settings path' }
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    $package = Get-Content -LiteralPath artifacts/release.json -Raw | ConvertFrom-Json
    $runtimeHelper = "$remoteRoot/releases/$tag/script/docker/compact-runtime-acceptance.py"
    $runtimeArguments = "--root '$remoteRoot' --runtime '$runtime' --tag '$tag' --commit '$commit' --source-sha256 '$sha' --instance-id '$instance' --machine-id '$machine' --settings '$settings'"
    function Receive-OwnedBuildResources([string]$RemoteDirectory, [string]$LocalDirectory) {
        & ssh.exe @sshOptions -p $portText $destination "test -f '$RemoteDirectory/resource-summary.json'"
        if ($LASTEXITCODE -eq 1) { return $null }
        if ($LASTEXITCODE -ne 0) { throw 'Could not determine whether owned image resource evidence exists.' }
        New-Item -ItemType Directory -Force -Path $LocalDirectory | Out-Null
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$RemoteDirectory/resource-summary.json", "$LocalDirectory/resource-summary.json"))
        $file = Get-Item -LiteralPath "$LocalDirectory/resource-summary.json"
        if ($file.Length -le 0 -or $file.Length -gt 2097152) { throw 'Owned image resource summary exceeds its bound.' }
        $summary = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
        if ($summary.release -ne $tag -or $summary.commit -ne $commit -or $summary.sourceSha256 -ne $sha -or $summary.identity.instanceId -ne $instance -or $summary.identity.machineId -ne $machine -or $summary.probeFile -ne 'resource-probes.jsonl' -or $summary.probeSha256 -notmatch '^[a-f0-9]{64}$' -or @($summary.phases).Count -gt 512) { throw 'Owned image resource evidence differs from this fixed build.' }
        $catalog = @(@{ file='resource-probes.jsonl'; sha256=$summary.probeSha256 }) + @($summary.phases)
        foreach ($entry in $catalog) {
            if ($entry.file -notmatch '^(resource-probes\.jsonl|phase-[0-9]{2,3}\.json)$' -or $entry.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Owned image resource file escaped its directory.' }
        }
        $measurementCatalog = @()
        if ($summary.PSObject.Properties['inputMeasurements']) { $measurementCatalog = @($summary.inputMeasurements) }
        if ($measurementCatalog.Count -gt 4) { throw 'Owned image input measurement catalogue exceeds its bound.' }
        $measurementNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
        foreach ($entry in $measurementCatalog) {
            if (@($entry.PSObject.Properties).Count -ne 3 -or $entry.file -cnotmatch '^base[0-3]-measurement\.json$' -or $entry.sha256 -cnotmatch '^[a-f0-9]{64}$' -or -not ($entry.bytes -is [int] -or $entry.bytes -is [long]) -or $entry.bytes -le 0 -or $entry.bytes -gt 1048576 -or -not $measurementNames.Add($entry.file)) { throw 'Owned image input measurement escaped its exact byte/name catalogue.' }
            $catalog += $entry
        }
        foreach ($entry in $catalog) {
            if ($entry.file -notmatch '^(resource-probes\.jsonl|phase-[0-9]{2,3}\.json|base[0-3]-measurement\.json)$' -or $entry.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Owned image resource file escaped its directory.' }
            $localFile = "$LocalDirectory/$($entry.file)"
            Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$RemoteDirectory/$($entry.file)", $localFile))
            if ((Get-Item -LiteralPath $localFile).Length -gt 67108864 -or (Get-FileHash -LiteralPath $localFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw 'Owned image raw evidence changed during collection.' }
            if ($measurementNames.Contains($entry.file)) {
                if ((Get-Item -LiteralPath $localFile).Length -ne $entry.bytes) { throw 'Owned image input measurement length changed during collection.' }
                $measurement = Get-Content -LiteralPath $localFile -Raw | ConvertFrom-Json
                if ($measurement.version -ne 1 -or $measurement.kind -cne 'doorhandle-complete-image-input-measurement' -or $measurement.release -cne $tag -or $measurement.commit -cne $commit -or $measurement.sourceSha256 -cne $sha -or $measurement.ownerToken -cne $summary.ownerToken -or $measurement.identity.instanceId -cne $instance -or $measurement.identity.machineId -cne $machine -or $measurement.identity.executionLocation -cne 'ECS') { throw 'Owned image input measurement belongs to another build or execution owner.' }
            }
        }
        return $summary
    }
    function Receive-RuntimeResource([string]$Name, [string]$Digest) {
        $names = @('resource-summary.json', 'resource-probes.jsonl',
            'resource-phase-1-runtime-start.json', 'resource-phase-2-runtime-backup.json', 'resource-phase-3-runtime-restore.json', 'resource-phase-4-runtime-browser.json')
        if ($Name -notin $names -or $Digest -notmatch '^[a-f0-9]{64}$') { throw 'Unexpected runtime resource evidence reference.' }
        New-Item -ItemType Directory -Force -Path artifacts/runtime-resources | Out-Null
        $localFile = "artifacts/runtime-resources/$Name"
        $remoteFile = "$remoteRoot/verification/$tag/checkout/work/runtime-acceptance/$Name"
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteFile", $localFile))
        $file = Get-Item -LiteralPath $localFile
        $maximum = if ($Name -eq 'resource-probes.jsonl') { 67108864 } else { 262144 }
        if ($file.Length -le 0 -or $file.Length -gt $maximum -or (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Digest) { throw 'Runtime resource evidence is missing, oversized or changed during collection.' }
        if ($Name -eq 'resource-probes.jsonl') { return }
        return Get-Content -LiteralPath $localFile -Raw | ConvertFrom-Json
    }
    function Receive-RuntimeBrowserFile([string]$RemoteFile, [string]$LocalFile, [string]$Digest, [long]$Maximum, [long]$ExpectedBytes = 0) {
        if ($Digest -cnotmatch '^[a-f0-9]{64}$') { throw 'Browser artifact lacks its original digest.' }
        $probe = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination,
            "test -f '$RemoteFile' && test ! -L '$RemoteFile' && test `"`$(readlink -f -- '$RemoteFile')`" = '$RemoteFile' && stat -c '%s %h %u %g' -- '$RemoteFile'"))
        $metadata = [string](@($probe) | Select-Object -Last 1)
        if ($metadata -cnotmatch '^([1-9][0-9]*) 1 1000 1000$') { throw 'Browser artifact is linked, absent or not owned by UID/GID 1000.' }
        $length = [long]$Matches[1]
        if ($length -gt $Maximum -or ($ExpectedBytes -gt 0 -and $length -ne $ExpectedBytes)) { throw 'Browser artifact exceeds its cataloged size bound.' }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LocalFile) | Out-Null
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$RemoteFile", $LocalFile))
        $file = Get-Item -LiteralPath $LocalFile
        if (($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or $file.Length -ne $length -or
                (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Digest) { throw 'Original browser bytes changed during collection.' }
    }
    function Receive-RuntimeObservability($Proof) {
        New-Item -ItemType Directory -Force -Path artifacts/runtime-observability | Out-Null
        # This collector consumes a new VerifyRuntime/CompactCutover execution,
        # not historical evidence. Legacy compatibility belongs to the byte validator.
        if (-not $Proof.loadScope.PSObject.Properties['observabilityRequired'] -or
            $Proof.loadScope.observabilityRequired -isnot [bool] -or
            $Proof.loadScope.observabilityRequired -ne $true -or $Proof.observability.status -cne 'PASS') { throw 'Required candidate monitoring did not pass.' }
        $phases = @('after-start','after-restart','after-volume-restore','after-business')
        if (@($Proof.observability.readbacks.PSObject.Properties).Count -ne $phases.Count) { throw 'Candidate monitoring phase evidence is incomplete.' }
        foreach ($phase in $phases) {
            $reference = $Proof.observability.readbacks.$phase
            $name = "observability-$phase.json"
            if ($reference.file -cne "checkout/work/runtime-acceptance/$name") { throw 'Monitoring evidence escaped its owned directory.' }
            Receive-RuntimeBrowserFile "$remoteRoot/verification/$tag/$($reference.file)" "artifacts/runtime-observability/$name" $reference.sha256 262144
        }
        foreach ($component in @('prometheus','alertmanager')) {
            $reference = $Proof.observability.images.$component
            $expected = "checkout/work/observability-fixture/$component-image/image.json"
            if ($reference.file -cne $expected -or $reference.resourceSummarySha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Monitoring image proof differs from this source acceptance.' }
            Receive-RuntimeBrowserFile "$remoteRoot/verification/$tag/$expected" "artifacts/runtime-observability/$component-image/image.json" $reference.sha256 262144
            $summary = Receive-OwnedBuildResources "$remoteRoot/verification/$tag/checkout/work/observability-fixture/$component-image" "artifacts/runtime-observability/$component-image"
            if (-not $summary -or $summary.status -cne 'PASS' -or (Get-FileHash -LiteralPath "artifacts/runtime-observability/$component-image/resource-summary.json" -Algorithm SHA256).Hash.ToLowerInvariant() -cne $reference.resourceSummarySha256) { throw 'Monitoring image resource evidence changed.' }
        }
    }
    function Receive-RuntimeCollaboration($CleanupEvidence, [string]$CleanupFile, [string]$ProofFile = '') {
        $references = [ordered]@{}
        foreach ($entry in @($CleanupEvidence.stableIdentityEvidence.PSObject.Properties)) {
            if ($entry.Name -cnotin @('preflight','admission','authorization') -or $entry.Value.status -cnotin @('PREFLIGHT_ONLY','PASS','BLOCKED')) { throw 'Unexpected stable identity public receipt.' }
            $references["stable-identity-$($entry.Name).json"] = $entry.Value
        }
        foreach ($entry in @($CleanupEvidence.collaborationHttpEvidence.PSObject.Properties)) {
            if ($entry.Name -cnotin @('claim','personnel')) { throw 'Unexpected collaboration HTTP public receipt.' }
            $references["collaboration-http-$($entry.Name).json"] = $entry.Value
        }
        if ($references.Count -gt 5) { throw 'Collaboration public receipt count exceeded five.' }
        $directory = Join-Path (Get-Location) ('work/runtime-collaboration-transfer-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $directory | Out-Null
        foreach ($name in $references.Keys) {
            $reference = $references[$name]
            if ($reference.file -cne "checkout/work/runtime-acceptance/$name" -or $reference.sha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Collaboration evidence escaped its fixed public path.' }
            Receive-RuntimeBrowserFile "$remoteRoot/verification/$tag/$($reference.file)" "$directory/$name" $reference.sha256 262144
        }
        $python = $env:LOCAL_PYTHON_EXE
        if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
        if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Existing local Python is required for receipt byte validation.' }
        $arguments = @('-I','-B','script/jenkins/validate-runtime-collaboration.py','--directory',(Resolve-Path $directory).Path,'--cleanup',(Resolve-Path $CleanupFile).Path)
        $output = Invoke-Checked $python $arguments
        $verdict = ($output | Select-Object -Last 1) | ConvertFrom-Json
        if ($verdict.status -cne 'PRESERVED' -or $verdict.files -ne $references.Count) { throw 'Original public collaboration bytes were not preserved.' }
        $archive = 'artifacts/runtime-collaboration'
        New-Item -ItemType Directory -Force -Path $archive | Out-Null
        foreach ($name in $references.Keys) { Move-Item -LiteralPath "$directory/$name" -Destination "$archive/$name" -Force }
        if ($ProofFile) {
            $arguments = @('-I','-B','script/jenkins/validate-runtime-collaboration.py','--directory',(Resolve-Path $archive).Path,'--cleanup',(Resolve-Path $CleanupFile).Path,
                '--proof',(Resolve-Path $ProofFile).Path,'--browser-report',(Resolve-Path 'artifacts/runtime-browser/browser-evidence/browser-evidence.json').Path)
            $output = Invoke-Checked $python $arguments
            $verdict = ($output | Select-Object -Last 1) | ConvertFrom-Json
            if ($verdict.status -cne 'VERIFIED' -or $verdict.files -ne 5) { throw 'Actual stable identity and HTTP collaboration evidence is incomplete.' }
        }
    }
    function Receive-RuntimeBrowser($CleanupEvidence, [string]$CleanupFile, [string]$ProofFile = '') {
        $reference = $CleanupEvidence.browserEvidence
        if (-not $reference -or $reference.file -cne 'checkout/work/runtime-acceptance/browser-manifest.json' -or $reference.sha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Runtime cleanup lacks its fixed original browser manifest.' }
        # No unvalidated transfer bytes enter the archived artifacts tree.
        $directory = Join-Path (Get-Location) ('work/runtime-browser-transfer-' + [guid]::NewGuid().ToString('N'))
        $stagedFiles = [System.Collections.Generic.List[string]]::new()
        $manifestFile = "$directory/browser-manifest.json"
        $stagedFiles.Add($manifestFile)
        try {
        Receive-RuntimeBrowserFile "$remoteRoot/verification/$tag/$($reference.file)" $manifestFile $reference.sha256 262144
        $manifest = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
        if ($manifest.status -cne 'EVIDENCE_PRESERVED' -or $manifest.kind -cne 'doorhandle-compact-runtime-acceptance' -or
                $manifest.release -cne $tag -or $manifest.commit -cne $commit -or $manifest.sourceSha256 -cne $sha -or
                $manifest.identity.instanceId -cne $instance -or $manifest.identity.machineId -cne $machine -or
                $manifest.project -cne $CleanupEvidence.project -or $manifest.candidateBuildSha256 -cne $CleanupEvidence.candidateBuildSha256 -or
                $manifest.acceptanceProfileSha256 -cne $CleanupEvidence.acceptanceProfileSha256) { throw 'Browser manifest belongs to another fixed runtime.' }
        $files = @($manifest.files); $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        if ($files.Count -gt 128) { throw 'Browser artifact count exceeds 128.' }
        [long]$total = 0
        foreach ($entry in $files) {
            if ($entry.path -cnotmatch '^checkout/work/runtime-acceptance/browser-evidence/(browser-evidence\.json|screenshots/[A-Za-z0-9][A-Za-z0-9_-]{0,95}\.png)$' -or
                    -not $seen.Add([string]$entry.path) -or $entry.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
                    $entry.bytes -isnot [ValueType] -or $entry.bytes -is [bool] -or [long]$entry.bytes -ne $entry.bytes -or
                    $entry.bytes -le 0 -or $entry.bytes -gt 33554432) { throw 'Browser catalog contains an unsafe, duplicate or oversized public artifact.' }
            $total += [long]$entry.bytes
        }
        if ($total -gt 134217728) { throw 'Browser originals exceed 128 MiB.' }
        foreach ($entry in $files) {
            $relative = $entry.path.Substring('checkout/work/runtime-acceptance/'.Length)
            $stagedFiles.Add("$directory/$relative")
            Receive-RuntimeBrowserFile "$remoteRoot/verification/$tag/$($entry.path)" "$directory/$relative" $entry.sha256 33554432 ([long]$entry.bytes)
        }
        New-Item -ItemType Directory -Force -Path "$directory/browser-evidence" | Out-Null
        $python = $env:LOCAL_PYTHON_EXE
        if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
        if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Configure existing local Python for byte-only browser evidence validation.' }
        $arguments = @('-I', '-B', 'script/jenkins/validate-runtime-browser.py', '--directory', (Resolve-Path $directory).Path,
            '--cleanup', (Resolve-Path $CleanupFile).Path)
        $output = Invoke-Checked $python $arguments
        $verdict = ($output | Select-Object -Last 1) | ConvertFrom-Json
        if ($verdict.status -cne 'PRESERVED' -or $verdict.browserManifestSha256 -cne $reference.sha256) { throw 'Original browser public artifact validation did not pass.' }
        $archive = 'artifacts/runtime-browser'
        New-Item -ItemType Directory -Force -Path "$archive/browser-evidence" | Out-Null
        foreach ($staged in $stagedFiles) {
            $relative = $staged.Substring($directory.Length + 1)
            $target = "$archive/$relative"
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Move-Item -LiteralPath $staged -Destination $target -Force
        }
        # Keep valid FAIL originals; semantic PASS validation happens only after
        # public type/owner/hash validation has promoted the original bytes.
        $arguments = @('-I', '-B', 'script/jenkins/validate-runtime-browser.py', '--directory', (Resolve-Path $archive).Path,
            '--cleanup', (Resolve-Path $CleanupFile).Path)
        if ($ProofFile) { $arguments += @('--proof', (Resolve-Path $ProofFile).Path) }
        $output = Invoke-Checked $python $arguments
        $verdict = ($output | Select-Object -Last 1) | ConvertFrom-Json
        if ($verdict.status -cne $(if ($ProofFile) { 'VERIFIED' } else { 'PRESERVED' }) -or $verdict.browserManifestSha256 -cne $reference.sha256) { throw 'Original browser execution byte validation did not pass.' }
        $verdict | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$archive/validated.json" -Encoding utf8
        } finally {
            foreach ($staged in $stagedFiles) { if (Test-Path -LiteralPath $staged -PathType Leaf) { Remove-Item -LiteralPath $staged -Force } }
        }
    }
    if ($Action -eq 'CleanupRuntime') {
        if (Test-Path -LiteralPath artifacts/runtime-execution-request.json) { $null=Wait-ExistingRuntime }
        foreach ($name in @('model', 'mcp', 'browser')) {
            $null = Receive-OwnedBuildResources "$remoteRoot/verification/$tag/checkout/work/runtime-acceptance/controlled-build-$name" "artifacts/fixture-build-resources/$name"
        }
        # Preserve the real exit code, but collect bounded public failure and
        # cleanup reports before reporting an incomplete cleanup to Jenkins.
        $PSNativeCommandUseErrorActionPreference = $false
        $cleanupArguments = $sshOptions + @('-p', $portText, $destination, "python3 -B '$runtimeHelper' cleanup $runtimeArguments")
        $output = & 'ssh.exe' @cleanupArguments
        $cleanupExit = $LASTEXITCODE
        $cleanup = ($output | Select-Object -Last 1) | ConvertFrom-Json
        if ($cleanup.release -ne $tag) { throw 'Runtime cleanup response belongs to another build.' }
        $cleanup | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath artifacts/runtime-cleanup.json -Encoding utf8
        function Receive-RuntimeJson([string]$RemoteFile, [string]$LocalFile, [string]$Digest) {
            if ($Digest -notmatch '^[a-f0-9]{64}$') { throw 'Runtime report lacks its actual digest.' }
            Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$RemoteFile", $LocalFile))
            $file = Get-Item -LiteralPath $LocalFile
            if ($file.Length -le 0 -or $file.Length -gt 262144 -or (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Digest) { throw 'Runtime report is missing, oversized or changed during collection.' }
            $value = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
            if ($value.release -ne $tag -or $value.commit -ne $commit -or $value.sourceSha256 -ne $sha -or $value.identity.instanceId -ne $instance -or $value.identity.machineId -ne $machine) { throw 'Runtime report belongs to another source or execution host.' }
            return $value
        }
        $cleanupEvidence = $null
        $cleanupDigest = $cleanup.PSObject.Properties['cleanupReceiptSha256']
        if ($cleanupDigest -and $cleanupDigest.Value) {
            $cleanupEvidence = Receive-RuntimeJson "$remoteRoot/verification/$tag/checkout/work/runtime-acceptance/cleanup.json" 'artifacts/runtime-cleanup-evidence.json' $cleanupDigest.Value
        }
        if ($cleanupEvidence) { Receive-RuntimeCollaboration $cleanupEvidence 'artifacts/runtime-cleanup-evidence.json' }
        if ($cleanupEvidence -and $cleanupEvidence.browserEvidence) { Receive-RuntimeBrowser $cleanupEvidence 'artifacts/runtime-cleanup-evidence.json' }
        if ($cleanupEvidence -and $cleanupEvidence.resourceEvidence) {
            $reference = $cleanupEvidence.resourceEvidence
            if ($reference.file -ne 'checkout/work/runtime-acceptance/resource-summary.json') { throw 'Unexpected failed runtime resource evidence location.' }
            $summary = Receive-RuntimeResource 'resource-summary.json' $reference.sha256
            if ($summary.release -ne $tag -or $summary.commit -ne $commit -or $summary.sourceSha256 -ne $sha -or $summary.project -ne $cleanupEvidence.project) { throw 'Failed runtime resource observations belong to another build.' }
            if ($summary.rawProbeSha256) {
                if ($summary.rawProbeFile -ne 'checkout/work/runtime-acceptance/resource-probes.jsonl') { throw 'Unexpected failed runtime probe location.' }
                Receive-RuntimeResource 'resource-probes.jsonl' $summary.rawProbeSha256
            }
            if (@($summary.phases).Count -gt 4) { throw 'Failed runtime phase evidence exceeds its bound.' }
            foreach ($phase in $summary.phases) {
                $name = [System.IO.Path]::GetFileName($phase.file)
                if ($phase.file -ne "checkout/work/runtime-acceptance/$name") { throw 'Failed runtime phase escaped its owned evidence directory.' }
                $null = Receive-RuntimeResource $name $phase.sha256
            }
        }
        $failureDigest = $cleanup.PSObject.Properties['failureReceiptSha256']
        if ($failureDigest -and $failureDigest.Value) {
            $failure = Receive-RuntimeJson "$remoteRoot/verification/$tag/runtime-failure.json" 'artifacts/runtime-failure.json' $failureDigest.Value
            if ($failure.kind -ne 'doorhandle-compact-runtime-failure' -or $failure.status -ne 'FAILED_OR_UNKNOWN') { throw 'Unexpected runtime failure report.' }
            $completed = @($failure.completedScenarios.PSObject.Properties)
            if ($completed.Count -gt 32) { throw 'Runtime failure scenario catalog exceeds its bound.' }
            New-Item -ItemType Directory -Force -Path artifacts/runtime-scenarios | Out-Null
            foreach ($scenario in $completed) {
                $id = $scenario.Name
                if ($id -notmatch '^[a-z][a-z0-9-]{0,79}$' -or $scenario.Value.file -ne "checkout/work/runtime-acceptance/scenario-$id.json") { throw 'Unexpected completed scenario path in runtime failure evidence.' }
                $evidence = Receive-RuntimeJson "$remoteRoot/verification/$tag/$($scenario.Value.file)" "artifacts/runtime-scenarios/scenario-$id.json" $scenario.Value.sha256
                if ($evidence.status -ne 'PASS' -or $evidence.scenario -ne $id -or $evidence.project -ne $failure.project) { throw 'Completed scenario does not belong to the failed runtime attempt.' }
            }
        }
        if ($cleanupExit -ne 0 -or $cleanup.status -ne 'STOPPED' -or -not $cleanupEvidence -or $cleanupEvidence.status -ne 'STOPPED' -or $cleanupEvidence.unresolved.Count -ne 0 -or $cleanupEvidence.sourceResourcesChanged -ne $false) { throw 'Owned runtime cleanup did not verify the matching stopped resources; collected reports are retained.' }
        return
    }
    $verified = Get-Content -LiteralPath artifacts/ecs/evidence/verification-receipt.json -Raw | ConvertFrom-Json
    $executed = Get-Content -LiteralPath artifacts/ecs/evidence/reports/receipt.json -Raw | ConvertFrom-Json
    if ($package.release -ne $tag -or $package.commit -ne $commit -or $package.sourceSha256 -ne $sha -or $verified.release -ne $tag -or $verified.commit -ne $commit -or $verified.sourceSha256 -ne $sha -or $verified.scope -ne 'mysql' -or $verified.status -ne 'PASS' -or $verified.fixtureReadinessValidated -ne $true -or $verified.verificationExitCode -ne 0 -or $verified.identity.instanceId -ne $instance -or $verified.identity.machineId -ne $machine) {
        throw 'Cutover cannot use another source, host, scope or failed ECS verification attempt.'
    }
    if ($executed.wholeMigrationRequested -ne $true -or $executed.wholeMigrationTests.passed -le 0 -or $executed.wholeMigrationTests.failed -ne 0 -or $executed.wholeMigrationTests.skipped -ne 0 -or $executed.javaTests.skipped -ne 0) {
        throw 'Whole migration, restoration and MySQL acceptance must actually execute without skipped cases.'
    }
    $jarSha = (Get-FileHash -LiteralPath artifacts/application.jar -Algorithm SHA256).Hash.ToLowerInvariant()
    $jarBytes = (Get-Item -LiteralPath artifacts/application.jar).Length
    if ($package.applicationJarSha256 -ne $jarSha) { throw 'Candidate image must contain the fixed-commit application artifact.' }
    $artifactPlan = [ordered]@{ schema=1; kind='doorhandle-compact-fixture-artifacts'; release=$tag; commit=$commit; sourceSha256=$sha; applicationJarSha256=$jarSha; applicationJarBytes=$jarBytes }
    $reuseFixtureArtifacts = $Action -ceq 'VerifyRuntime' -and $env:CI_FIXTURES_PREPARED -ceq 'true'
    if (Test-Path -LiteralPath artifacts/fixture-build-artifacts.json) {
        $existingPlan = Get-Content -LiteralPath artifacts/fixture-build-artifacts.json -Raw | ConvertFrom-Json
        foreach ($key in $artifactPlan.Keys) { if ($existingPlan.$key -ne $artifactPlan[$key]) { throw 'Candidate and fixture artifact plans differ.' } }
        if ($reuseFixtureArtifacts) {
            if (@($existingPlan.PSObject.Properties).Count -ne $artifactPlan.Count) { throw 'Prepared fixture artifact plan fields differ.' }
            foreach ($key in $artifactPlan.Keys) {
                $validType = if ($artifactPlan[$key] -is [string]) { $existingPlan.$key -is [string] } else { $existingPlan.$key -is [int] -or $existingPlan.$key -is [long] }
                if (-not $validType -or $existingPlan.$key -cne $artifactPlan[$key]) { throw 'Prepared fixture artifact plan values differ.' }
            }
        }
    } else {
        if ($reuseFixtureArtifacts) { throw 'Prepared fixture artifact reuse requires its original local artifact plan.' }
        $artifactPlan | ConvertTo-Json | Set-Content -LiteralPath artifacts/fixture-build-artifacts.json -Encoding utf8
    }
    $transport = [ordered]@{ schema=1; kind='doorhandle-runtime-artifact-transport'; status='FAILED'; release=$tag; commit=$commit; sourceSha256=$sha;
        applicationJarSha256=$jarSha; applicationJarBytes=$jarBytes; reusedPreparedFixture=$reuseFixtureArtifacts; applicationJarTransferredBytes=[long]0 }
    $transport | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath artifacts/runtime-artifact-transport.json -Encoding utf8
    if ($reuseFixtureArtifacts) {
        $expectedPlan = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($artifactPlan | ConvertTo-Json -Compress)))
        $reuseProbe = @'
import base64,contextlib,hashlib,json,os,stat,sys
from pathlib import Path
inbox=Path(sys.argv[1]);expected=json.loads(base64.b64decode(sys.argv[2],validate=True))
if inbox.resolve(strict=True)!=inbox or Path('/etc/machine-id').read_text().strip()!=sys.argv[3]: raise ValueError('FIXED_ARTIFACT_HOST_PATH_REQUIRED')
def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('DUPLICATE_ARTIFACT_PLAN_FIELD')
        result[key]=value
    return result
def identity(value):
    return tuple(getattr(value,key) for key in ('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
@contextlib.contextmanager
def owned(path,maximum):
    if path.resolve(strict=True)!=path: raise ValueError('CANONICAL_ARTIFACT_REQUIRED')
    stream=os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb');info=os.fstat(stream.fileno())
    if not(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and not info.st_mode&0o077 and 0<info.st_size<=maximum):
        stream.close();raise ValueError('PRIVATE_OWNED_SINGLE_LINK_ARTIFACT_REQUIRED')
    try: yield stream,info
    finally: stream.close()
plan_path=inbox/'build-artifacts.json';jar_path=inbox/'application.jar'
with owned(plan_path,65536) as (plan_stream,plan_before),owned(jar_path,512*1024**2) as (jar_stream,jar_before):
    raw=plan_stream.read(65537);plan=json.loads(raw,object_pairs_hook=unique)
    if type(plan) is not dict or plan!=expected or any(type(plan[key]) is not type(expected[key]) for key in expected): raise ValueError('PREPARED_ARTIFACT_PLAN_DIFFERS')
    if jar_before.st_size!=expected['applicationJarBytes']: raise ValueError('PREPARED_JAR_SIZE_DIFFERS')
    digest=hashlib.sha256();remaining=jar_before.st_size
    while remaining:
        block=jar_stream.read(min(remaining,1024*1024))
        if not block: raise ValueError('PREPARED_JAR_TRUNCATED')
        digest.update(block);remaining-=len(block)
    if jar_stream.read(1): raise ValueError('PREPARED_JAR_GREW')
    if digest.hexdigest()!=expected['applicationJarSha256']: raise ValueError('PREPARED_JAR_SHA_DIFFERS')
    for path,stream,before in ((plan_path,plan_stream,plan_before),(jar_path,jar_stream,jar_before)):
        if identity(before)!=identity(os.fstat(stream.fileno())) or identity(before)!=identity(path.lstat()): raise ValueError('PREPARED_ARTIFACT_CHANGED_DURING_READ')
print(json.dumps({'status':'REUSED_VERIFIED','release':expected['release'],'commit':expected['commit'],'sourceSha256':expected['sourceSha256'],
    'applicationJarSha256':digest.hexdigest(),'applicationJarBytes':jar_before.st_size,'artifactPlanSha256':hashlib.sha256(raw).hexdigest(),
    'identity':{'instanceId':sys.argv[4],'machineId':sys.argv[3],'executionLocation':'ECS'}},sort_keys=True))
'@
        $reuseArguments = $sshOptions + @('-p', $portText, $destination, "python3 -I -B - '$remoteInbox' '$expectedPlan' '$machine' '$instance'")
        $reuseOutput = $reuseProbe | & 'ssh.exe' @reuseArguments
        if ($LASTEXITCODE -ne 0) { throw 'Prepared fixture artifact reuse failed; existing ECS files were not overwritten.' }
        $reused = ($reuseOutput | Select-Object -Last 1) | ConvertFrom-Json
        foreach ($key in @('release','commit','sourceSha256','applicationJarSha256','applicationJarBytes')) { if ($reused.$key -cne $artifactPlan[$key]) { throw 'Prepared fixture artifact reuse response differs.' } }
        if ($reused.status -cne 'REUSED_VERIFIED' -or $reused.artifactPlanSha256 -notmatch '^[a-f0-9]{64}$' -or $reused.identity.instanceId -cne $instance -or $reused.identity.machineId -cne $machine -or $reused.identity.executionLocation -cne 'ECS') { throw 'Prepared fixture artifact reuse lacks this build and host evidence.' }
        $transport.status='REUSED_VERIFIED';$transport['artifactPlanSha256']=$reused.artifactPlanSha256
    } else {
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'artifacts/application.jar', "${destination}:$remoteInbox/application.jar"))
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'artifacts/fixture-build-artifacts.json', "${destination}:$remoteInbox/build-artifacts.json"))
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "chmod 600 '$remoteInbox/application.jar' '$remoteInbox/build-artifacts.json'"))
        $transport.status='UPLOADED';$transport.applicationJarTransferredBytes=[long]$jarBytes
    }
    $transport | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath artifacts/runtime-artifact-transport.json -Encoding utf8
    foreach ($file in @('memory-compat.py', 'model-secrets.py', 'assignment-compat.py', 'mcp-compat.py', 'mcp-runtime.py', 'compact-schema-guard.py', 'compact-cutover.py')) {
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, (Get-PinnedSourceFile "script/docker/$file"), "${destination}:$remoteInbox/$file"))
    }
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, (Get-PinnedSourceFile 'script/jenkins/deploy-remote.sh'), "${destination}:$remoteInbox/deploy-remote.sh"))
    $buildRegistry = Get-BuildRegistryAssignment
    function Receive-CandidateResources {
        return Receive-OwnedBuildResources "$remoteRoot/releases/$tag/work/candidate-build-resources" 'artifacts/candidate-build-resources'
    }
    $candidateResources = $null
    try {
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "$buildRegistry bash '$remoteInbox/deploy-remote.sh' build-only '$remoteRoot' '$runtime' '$tag' '$sha' '$settings' '$instance' '$machine' '$commit'"))
    } finally { $candidateResources = Receive-CandidateResources }
    if (-not $candidateResources -or $candidateResources.status -ne 'PASS') { throw 'Candidate image construction lacks passing controlled resource evidence.' }
    $resourceValidator = Get-PinnedSourceFile 'script/docker/compact-build-resources.py'
    $resourcePython = $env:LOCAL_PYTHON_EXE
    if (-not $resourcePython) { $resourcePython = $env:PYTHON_EXE }
    Invoke-Checked $resourcePython @('-I', '-B', $resourceValidator, 'validate', '--directory', 'artifacts/candidate-build-resources', '--tag', $tag, '--commit', $commit, '--source-sha256', $sha, '--instance-id', $instance, '--machine-id', $machine)
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/releases/$tag/candidate-build.json", 'artifacts/compact-candidate-build.json'))
    $buildReceipt = Get-Content -LiteralPath artifacts/compact-candidate-build.json -Raw | ConvertFrom-Json
    if ($buildReceipt.kind -ne 'doorhandle-compact-candidate-build' -or $buildReceipt.status -ne 'BUILT' -or $buildReceipt.commit -ne $commit -or $buildReceipt.sourceSha256 -ne $sha -or $buildReceipt.release -ne $tag -or $buildReceipt.ecs.instanceId -ne $instance -or $buildReceipt.ecs.machineId -ne $machine) {
        throw 'Candidate image/artifact build receipt differs from this fixed Jenkins source.'
    }
    if ($buildReceipt.applicationJarSha256 -ne $jarSha -or $buildReceipt.applicationJarBytes -ne $jarBytes) { throw 'The built image does not contain this pipeline application jar.' }
    if ($buildReceipt.buildResourceEvidence.file -ne 'work/candidate-build-resources/resource-summary.json' -or $buildReceipt.buildResourceEvidence.sha256 -ne (Get-FileHash -LiteralPath 'artifacts/candidate-build-resources/resource-summary.json' -Algorithm SHA256).Hash.ToLowerInvariant()) { throw 'Candidate build resource receipt was not bound to the actual collected bytes.' }
    if ($candidateResources.applicationJar.sha256 -ne $jarSha -or $candidateResources.applicationJar.bytes -ne $jarBytes) { throw 'Candidate resource journal contains another Jenkins jar.' }
    foreach ($service in @('backend', 'nginx', 'mem0', 'detection-worker')) {
        if ($candidateResources.build.images.$service.imageId -ne $buildReceipt.images.$service) { throw 'Candidate measured image differs from the admitted build receipt.' }
    }
    $fixtureResources = @{}
    $runtimeSource=Get-PinnedSourceFile 'script/docker/compact-runtime-acceptance.py'
    @{release=$tag;commit=$commit;sourceSha256=$sha;runtime=$runtime;settings=$settings;
        instanceId=$instance;machineId=$machine;
        helperSha256=(Get-FileHash -LiteralPath $runtimeSource -Algorithm SHA256).Hash.ToLowerInvariant();
        candidateBuildSha256=(Get-FileHash -LiteralPath artifacts/compact-candidate-build.json -Algorithm SHA256).Hash.ToLowerInvariant()} |
        ConvertTo-Json | Set-Content -LiteralPath artifacts/runtime-execution-request.json -Encoding utf8
    try {
        $PSNativeCommandUseErrorActionPreference=$false
        $result=@(& ssh.exe @sshOptions -p $portText $destination "python3 -B '$runtimeHelper' run $runtimeArguments")
        $runtimeExit=$LASTEXITCODE
        if ($runtimeExit -eq 255) {
            $observed=Wait-ExistingRuntime
            $result=@($observed | ConvertTo-Json -Depth 8 -Compress)
            $runtimeExit=if ($observed.status -ceq 'PASS') {0} else {1}
        }
        if ($runtimeExit -ne 0) { throw 'The original runtime did not pass; preserve its actual terminal evidence.' }
    } finally {
        foreach ($name in @('model', 'mcp', 'browser')) {
            $fixtureResources[$name] = Receive-OwnedBuildResources "$remoteRoot/verification/$tag/checkout/work/runtime-acceptance/controlled-build-$name" "artifacts/fixture-build-resources/$name"
        }
    }
    $runtimeResult = ($result | Select-Object -Last 1) | ConvertFrom-Json
    if ($runtimeResult.status -ne 'PASS' -or $runtimeResult.release -ne $tag -or $runtimeResult.runtimeScenarios -lt 9 -or $runtimeResult.ownedCleanup -ne 'STOPPED' -or $runtimeResult.runtimeReceiptSha256 -notmatch '^[a-f0-9]{64}$') { throw 'Complete application runtime acceptance did not pass and clean up its owned resources.' }
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/verification/$tag/runtime-acceptance.json", 'artifacts/runtime-acceptance.json'))
    if ((Get-FileHash -LiteralPath artifacts/runtime-acceptance.json -Algorithm SHA256).Hash.ToLowerInvariant() -ne $runtimeResult.runtimeReceiptSha256) { throw 'The actual runtime acceptance receipt changed during collection.' }
    $runtimeProof = Get-Content -LiteralPath artifacts/runtime-acceptance.json -Raw | ConvertFrom-Json
    foreach ($name in @('model', 'mcp', 'browser')) {
        $reference = $runtimeProof.fixtureBuildResources.$name
        $file = "artifacts/fixture-build-resources/$name/resource-summary.json"
        if (-not $fixtureResources[$name] -or $fixtureResources[$name].status -ne 'PASS' -or $reference.file -ne "checkout/work/runtime-acceptance/controlled-build-$name/resource-summary.json" -or $reference.sha256 -ne (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()) { throw 'Runtime fixture image build lacks matching controlled resource evidence.' }
        Invoke-Checked $resourcePython @('-I', '-B', $resourceValidator, 'validate', '--directory', "artifacts/fixture-build-resources/$name", '--fixture', $name, '--tag', $tag, '--commit', $commit, '--source-sha256', $sha, '--instance-id', $instance, '--machine-id', $machine)
    }
    $candidateSha = (Get-FileHash -LiteralPath artifacts/compact-candidate-build.json -Algorithm SHA256).Hash.ToLowerInvariant()
    $wholeProof = Get-Content -LiteralPath artifacts/ecs/evidence/reports/migration.json -Raw | ConvertFrom-Json
    if ($runtimeProof.status -ne 'PASS' -or $runtimeProof.commit -ne $commit -or $runtimeProof.release -ne $tag -or $runtimeProof.sourceSha256 -ne $sha -or $runtimeProof.candidateBuildSha256 -ne $candidateSha -or $runtimeProof.acceptanceProfileSha256 -ne $verified.acceptanceProfileSha256 -or $runtimeProof.migrationReceiptSha256 -ne $wholeProof.migrationReceiptSha256 -or $runtimeProof.initialTargetSnapshotSha256 -ne $wholeProof.targetSnapshotSha256 -or $runtimeProof.identity.instanceId -ne $instance -or $runtimeProof.identity.machineId -ne $machine -or $runtimeProof.paidModelCalls -ne 0) { throw 'Application acceptance proof belongs to another build, dataset, image or execution host.' }
    $nativeCandidate = Get-Content -LiteralPath artifacts/legacy-candidate.json -Raw | ConvertFrom-Json
    $native = $runtimeProof.legacyData
    if ($native.verificationSubject -cne 'INDEPENDENT_REAL_BGE_CANDIDATE' -or $native.appRuntimeValidationMode -cne 'ISOLATED_MOCK_QDRANT_RUNTIME' -or $native.vectorBackend -cne 'qdrant') { throw 'Legacy candidate verification and isolated mock application evidence must remain distinct.' }
    if ($native.legacyKafkaFiles -ne 309 -or $native.legacyKafkaBytes -ne 1184990233 -or $native.legacyKafkaReplay -cne 'NOT_PERFORMED') { throw 'Runtime acceptance lacks the original Kafka archive preservation boundary.' }
    if ($native.candidateSha256 -ne $nativeCandidate.descriptorSha256 -or $native.ragManifestSha256 -ne $nativeCandidate.ragManifestSha256 -or $native.originalLocalMem0Records -ne 32 -or $native.eligibleLocalMem0Records -ne 30 -or $native.activatedLocalMem0Records -ne 30 -or $native.archivedLocalMem0Records -ne 2 -or $native.localMem0SemanticStatus -ne 'VERIFIED_AND_ACTIVATED' -or $native.candidateSemanticVerified -ne $true -or $native.productionDataMaterialized -ne $false -or $native.llmCalls -ne 0 -or $native.productionPromotionAllowed -ne $false) { throw 'Runtime did not retain the admitted legacy data and its explicit semantic activation boundary.' }
    $nativePhases = @('after-start', 'after-restart', 'after-volume-restore')
    if ((@($native.verifications.PSObject.Properties.Name | Sort-Object) -join ',') -cne (@($nativePhases | Sort-Object) -join ',')) { throw 'Native data startup, restart and new-volume recovery evidence is incomplete.' }
    New-Item -ItemType Directory -Path artifacts/runtime-native | Out-Null
    foreach ($phase in $nativePhases) {
        $reference = $native.verifications.$phase
        $name = "native-readback-$phase.json"
        if ($reference.file -ne "checkout/work/runtime-acceptance/$name" -or $reference.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Native runtime evidence escaped the fixed public report catalog.' }
        $localFile = "artifacts/runtime-native/$name"
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/verification/$tag/$($reference.file)", $localFile))
        $file = Get-Item -LiteralPath $localFile
        if ($file.Length -le 0 -or $file.Length -gt 262144 -or (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $reference.sha256) { throw 'Native runtime original evidence changed during collection.' }
        $proof = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
        if ($proof.verificationSubject -cne 'INDEPENDENT_REAL_BGE_CANDIDATE' -or $proof.appRuntimeValidationMode -cne 'ISOLATED_MOCK_QDRANT_RUNTIME' -or $proof.vectorBackend -cne 'qdrant') { throw 'Native readback does not identify the independent real Qdrant candidate.' }
        if ($proof.kind -ne 'doorhandle-legacy-runtime-readback' -or $proof.status -ne 'VERIFIED' -or $proof.phase -ne $phase -or $proof.commit -ne $commit -or $proof.release -ne $tag -or $proof.sourceSha256 -ne $sha -or $proof.candidateBuildSha256 -ne $candidateSha -or $proof.project -ne $runtimeProof.project -or $proof.identity.instanceId -ne $instance -or $proof.identity.machineId -ne $machine -or $proof.descriptorSha256 -ne $nativeCandidate.descriptorSha256 -or $proof.ragManifestSha256 -ne $nativeCandidate.ragManifestSha256 -or $proof.retrievalQueries -lt 83 -or $proof.sourceAndDocumentAndFloat32Verified -ne $true -or $proof.activatedLocalMem0Records -ne 30 -or $proof.localMem0SemanticStatus -ne 'PHASE_SEMANTIC_VERIFIED' -or $proof.candidateSemanticVerified -ne $true -or $proof.productionDataMaterialized -ne $false -or $proof.llmCalls -ne 0 -or $proof.paidModelCalls -ne 0 -or $proof.productionPromotionAllowed -ne $false) { throw 'Native data readback did not verify this exact candidate without semantic activation or paid calls.' }
    }
    $activationReference = $native.semanticActivation
    if ($activationReference.file -cne 'checkout/work/runtime-acceptance/native-semantic-activation.json' -or $activationReference.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Semantic activation original receipt is missing.' }
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/verification/$tag/$($activationReference.file)", 'artifacts/runtime-native/native-semantic-activation.json'))
    if ((Get-FileHash -LiteralPath artifacts/runtime-native/native-semantic-activation.json -Algorithm SHA256).Hash.ToLowerInvariant() -ne $activationReference.sha256) { throw 'Semantic activation receipt changed during collection.' }
    $activation = Get-Content -LiteralPath artifacts/runtime-native/native-semantic-activation.json -Raw | ConvertFrom-Json
    if ($activation.verificationSubject -cne 'INDEPENDENT_REAL_BGE_CANDIDATE' -or $activation.appRuntimeValidationMode -cne 'ISOLATED_MOCK_QDRANT_RUNTIME' -or $activation.vectorBackend -cne 'qdrant') { throw 'Candidate semantic activation cannot be reported as production application activation.' }
    if ($activation.status -cne 'VERIFIED_AND_ACTIVATED' -or $activation.commit -cne $commit -or $activation.release -cne $tag -or $activation.sourceSha256 -cne $sha -or $activation.candidateSha256 -cne $nativeCandidate.descriptorSha256 -or $activation.candidateSemanticVerified -ne $true -or $activation.productionDataMaterialized -ne $false -or $activation.paidModelCalls -ne 0 -or $activation.llmCalls -ne 0) { throw 'Semantic activation is not bound to this candidate or preserved production boundary.' }
    foreach ($phase in $nativePhases) {
        $semanticReference = $activation.verifications.$phase.semantic
        $name = "bge-semantic-$phase.json"
        if ($semanticReference.file -cne "checkout/work/runtime-acceptance/$name" -or $semanticReference.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Actual BGE phase evidence is missing.' }
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/verification/$tag/$($semanticReference.file)", "artifacts/runtime-native/$name"))
        if ((Get-FileHash -LiteralPath "artifacts/runtime-native/$name" -Algorithm SHA256).Hash.ToLowerInvariant() -ne $semanticReference.sha256) { throw 'Actual BGE phase receipt changed during collection.' }
        $semantic = Get-Content -LiteralPath "artifacts/runtime-native/$name" -Raw | ConvertFrom-Json
        $rag = $semantic.ragVerification
        if ($semantic.verificationSubject -cne 'INDEPENDENT_REAL_BGE_CANDIDATE' -or $semantic.appRuntimeValidationMode -cne 'ISOLATED_MOCK_QDRANT_RUNTIME' -or $semantic.vectorBackend -cne 'qdrant' -or $semantic.storageGeneration -cne 'qdrant-bge-m3-v1' -or $rag.status -cne 'VERIFIED' -or $rag.queryProtocol -cne 'SHARED_BRIDGE_SOURCE_TEXT_QUERY_V1' -or $rag.retrievalQueries -lt 83 -or $rag.profile -cne 'siliconflow-bge-m3-v1' -or $rag.collection -cne 'doorhandle_rag_bge_m3_v1' -or $rag.embeddingRequests -le 0 -or $rag.paidModelCalls -ne 0 -or $rag.llmCalls -ne 0) { throw 'Real RAG verification lacks shared BGE bridge, Qdrant target or complete source-query evidence.' }
        if ($semantic.status -cne 'SEMANTIC_BRIDGE_VERIFIED' -or $semantic.phase -cne $phase -or $semantic.candidateSha256 -cne $nativeCandidate.descriptorSha256 -or $semantic.embeddingProfile -cne 'siliconflow-bge-m3-v1' -or $semantic.model -cne 'BAAI/bge-m3' -or $semantic.collection -cne 'doorhandle_memories_bge_m3_v1' -or $semantic.dimensions -ne 1024 -or $semantic.semanticQueries -lt 2 -or $semantic.crossOwnerQueries -ne $semantic.semanticQueries -or $semantic.embeddingRequests -ne (2 * $semantic.semanticQueries) -or $semantic.actualEmbeddingAttempts -ne ($semantic.embeddingRequests + $rag.embeddingRequests) -or $semantic.actualEmbeddingSuccesses -ne ($semantic.embeddingRequests + $rag.embeddingRequests) -or $semantic.nativeReadOnlyVerified -ne $true -or $semantic.nativeBeforeSha256 -cne $semantic.nativeAfterSha256 -or $semantic.independentProcess -ne $true -or $semantic.ownedRestoredCopy -ne $true -or $semantic.helperCleanup.pid -ne 0 -or $semantic.helperCleanup.exitCode -ne 0 -or $semantic.paidModelCalls -ne 0 -or $semantic.llmCalls -ne 0) { throw 'BGE semantic phase lacks real query, owner isolation, independent recovery or cleanup proof.' }
    }
    foreach ($service in @('backend', 'nginx', 'mem0', 'detection-worker')) {
        if ($runtimeProof.images.$service -ne $buildReceipt.images.$service) { throw 'Runtime used a different candidate image.' }
    }
    $scenarios = @($runtimeProof.scenarios.PSObject.Properties)
    $profile = Get-Content -LiteralPath script/jenkins/compact-acceptance.json -Raw | ConvertFrom-Json
    $requiredScenarios = @($profile.runtimeAcceptance.scenarios | ForEach-Object { $_.id } | Sort-Object)
    $actualScenarios = @($scenarios | ForEach-Object { $_.Name } | Sort-Object)
    if ($requiredScenarios.Count -lt 9 -or $requiredScenarios.Count -gt 32 -or ($requiredScenarios -join ',') -cne ($actualScenarios -join ',')) { throw 'Runtime acceptance did not execute the exact fixed-source scenario catalog.' }
    New-Item -ItemType Directory -Path artifacts/runtime-scenarios | Out-Null
    foreach ($scenario in $scenarios) {
        $id = $scenario.Name
        $member = $scenario.Value
        $expectedFile = "checkout/work/runtime-acceptance/scenario-$id.json"
        if ($id -notmatch '^[a-z][a-z0-9-]{0,79}$' -or $member.file -ne $expectedFile -or $member.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Unexpected runtime scenario evidence path or digest.' }
        $localFile = "artifacts/runtime-scenarios/scenario-$id.json"
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/verification/$tag/$expectedFile", $localFile))
        $length = (Get-Item -LiteralPath $localFile).Length
        if ($length -le 0 -or $length -gt 262144 -or (Get-FileHash -LiteralPath $localFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $member.sha256) { throw 'A runtime scenario report is missing, oversized or changed during collection.' }
        $observed = Get-Content -LiteralPath $localFile -Raw | ConvertFrom-Json
        if ($observed.status -ne 'PASS' -or $observed.scenario -ne $id -or $observed.commit -ne $commit -or $observed.release -ne $tag -or $observed.sourceSha256 -ne $sha -or $observed.candidateBuildSha256 -ne $candidateSha -or $observed.acceptanceProfileSha256 -ne $runtimeProof.acceptanceProfileSha256 -or $observed.project -ne $runtimeProof.project -or $observed.identity.instanceId -ne $instance -or $observed.identity.machineId -ne $machine) { throw 'Runtime scenario evidence does not belong to this actual application build.' }
    }
    $cleanupReference = $runtimeProof.cleanup
    if ($cleanupReference.status -ne 'STOPPED' -or $cleanupReference.file -ne 'checkout/work/runtime-acceptance/cleanup.json' -or $cleanupReference.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Runtime cleanup lacks its actual owned resource report.' }
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/verification/$tag/$($cleanupReference.file)", 'artifacts/runtime-cleanup-evidence.json'))
    $cleanupFile = Get-Item -LiteralPath artifacts/runtime-cleanup-evidence.json
    if ($cleanupFile.Length -le 0 -or $cleanupFile.Length -gt 262144 -or (Get-FileHash -LiteralPath $cleanupFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $cleanupReference.sha256) { throw 'Runtime cleanup evidence is missing, oversized or changed during collection.' }
    $cleanupEvidence = Get-Content -LiteralPath $cleanupFile.FullName -Raw | ConvertFrom-Json
    Receive-RuntimeBrowser $cleanupEvidence $cleanupFile.FullName 'artifacts/runtime-acceptance.json'
    Receive-RuntimeCollaboration $cleanupEvidence $cleanupFile.FullName 'artifacts/runtime-acceptance.json'
    Receive-RuntimeObservability $runtimeProof
    if ($cleanupEvidence.status -ne 'STOPPED' -or $cleanupEvidence.unresolved.Count -ne 0 -or $cleanupEvidence.stoppedContainers.Count -eq 0 -or $cleanupEvidence.sourceResourcesChanged -ne $false -or $cleanupEvidence.commit -ne $commit -or $cleanupEvidence.release -ne $tag -or $cleanupEvidence.sourceSha256 -ne $sha -or $cleanupEvidence.candidateBuildSha256 -ne $candidateSha -or $cleanupEvidence.project -ne $runtimeProof.project) { throw 'Runtime cleanup did not prove this build owned resources were stopped.' }
    $resourceReference = $runtimeProof.resourceEvidence
    if ($resourceReference.file -ne 'checkout/work/runtime-acceptance/resource-summary.json' -or $resourceReference.sha256 -notmatch '^[a-f0-9]{64}$' -or $cleanupEvidence.resourceEvidence.file -ne $resourceReference.file -or $cleanupEvidence.resourceEvidence.sha256 -ne $resourceReference.sha256) { throw 'Runtime resources and cleanup lack a common bound evidence reference.' }
    $resourceSummary = Receive-RuntimeResource 'resource-summary.json' $resourceReference.sha256
    if ($resourceSummary.rawProbeFile -ne 'checkout/work/runtime-acceptance/resource-probes.jsonl') { throw 'Unexpected resource probe evidence location.' }
    Receive-RuntimeResource 'resource-probes.jsonl' $resourceSummary.rawProbeSha256
    if (@($resourceSummary.phases).Count -ne 4) { throw 'Runtime resource phase evidence is incomplete.' }
    foreach ($phase in $resourceSummary.phases) {
        $name = [System.IO.Path]::GetFileName($phase.file)
        if ($phase.file -ne "checkout/work/runtime-acceptance/$name") { throw 'Resource phase evidence escaped its owned directory.' }
        $null = Receive-RuntimeResource $name $phase.sha256
    }
    $python = $env:LOCAL_PYTHON_EXE
    if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
    if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Configure existing local Python for byte-only resource evidence validation.' }
    $validatedResources = Invoke-Checked $python @('-I', '-B', 'script/jenkins/validate-runtime-resources.py',
        '--proof', (Resolve-Path artifacts/runtime-acceptance.json).Path,
        '--cleanup', (Resolve-Path artifacts/runtime-cleanup-evidence.json).Path,
        '--summary', (Resolve-Path artifacts/runtime-resources/resource-summary.json).Path,
        '--probes', (Resolve-Path artifacts/runtime-resources/resource-probes.jsonl).Path,
        '--phase-directory', (Resolve-Path artifacts/runtime-resources).Path,
        '--browser-directory', (Resolve-Path artifacts/runtime-browser).Path,
        '--browser-build-directory', (Resolve-Path artifacts/fixture-build-resources/browser).Path,
        '--observability-directory', (Resolve-Path artifacts/runtime-observability).Path)
    $resourceVerdict = ($validatedResources | Select-Object -Last 1) | ConvertFrom-Json
    if ($resourceVerdict.status -ne 'VERIFIED' -or $resourceVerdict.productionCapacityVerified -ne $false -or $resourceVerdict.resourceSummarySha256 -ne $resourceReference.sha256) { throw 'Bounded runtime resources did not pass independent byte-level validation.' }
    $resourceVerdict | ConvertTo-Json | Set-Content -LiteralPath artifacts/runtime-resources/validated.json -Encoding utf8
    # This completion receipt is written only after all original scenario and
    # cleanup bytes have passed validation. Later production cutover failure
    # must not rerun this finished runtime or overwrite its frozen evidence.
    @{ kind='doorhandle-runtime-gate-passed'; status='VERIFIED'; release=$tag; commit=$commit;
       sourceSha256=$sha; candidateBuildSha256=$candidateSha; runtimeReceiptSha256=$runtimeResult.runtimeReceiptSha256;
       legacyCandidateSha256=$nativeCandidate.descriptorSha256; ragManifestSha256=$nativeCandidate.ragManifestSha256;
       cleanupReceiptSha256=$cleanupReference.sha256; resourceSummarySha256=$resourceReference.sha256;
       resourceProbeSha256=$resourceSummary.rawProbeSha256 } |
        ConvertTo-Json | Set-Content -LiteralPath artifacts/runtime-gate-passed.json -Encoding utf8
    if ($Action -eq 'VerifyRuntime') { return }
    $inputFile = "$remoteRoot/releases/$tag/work/private-cutover-input.json"
    $helper = "$remoteRoot/releases/$tag/script/docker/compact-cutover.py"
    $cutoverArgs = "--root '$remoteRoot' --runtime '$runtime' --tag '$tag' --source-sha256 '$sha' --config '$inputFile'"
    $failed = $null
    try {
        foreach ($phase in @('prepare', 'migrate', 'activate')) {
            $gate = 'DOORHANDLE_COMPACT_RELEASE_READY=true '
            Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "${gate}python3 -B '$helper' $phase $cutoverArgs"))
        }
    } catch { $failed = $_ }
    try {
        $output = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "python3 -B '$helper' status $cutoverArgs"))
        $summary = ($output | Select-Object -Last 1) | ConvertFrom-Json
        $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath artifacts/compact-cutover.json -Encoding UTF8
        if (-not $failed -and ($summary.phase -ne 'ACTIVE' -or $summary.status -ne 'ACTIVE' -or $summary.sourceRestorationAllowed -ne $false -or $summary.migrationReceiptSha256 -notmatch '^[a-f0-9]{64}$' -or $summary.candidateSemanticVerified -ne $true -or $summary.productionDataMaterialized -ne $true -or $summary.nativeProductionReadback.sha256 -notmatch '^[a-f0-9]{64}$')) { throw 'Cutover health/publication evidence is incomplete.' }
        if (-not $failed) {
            $nativeProduction = $summary.nativeProductionReadback
            if ($nativeProduction.file -notmatch ('^' + [regex]::Escape("$remoteRoot/releases/$tag/work/") + 'compact-cutover-[a-f0-9]{10}/native-production-readback\.json$')) { throw 'Native production public receipt escaped its fixed source cutover.' }
            Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$($nativeProduction.file)", 'artifacts/native-production-readback.json'))
            if ((Get-FileHash -LiteralPath artifacts/native-production-readback.json -Algorithm SHA256).Hash.ToLowerInvariant() -ne $nativeProduction.sha256) { throw 'Native production readback changed during collection.' }
            $materialized = Get-Content -LiteralPath artifacts/native-production-readback.json -Raw | ConvertFrom-Json
            if ($materialized.status -cne 'VERIFIED' -or $materialized.release -cne $tag -or $materialized.commit -cne $commit -or $materialized.sourceSha256 -cne $sha -or $materialized.identity.instanceId -cne $instance -or $materialized.identity.machineId -cne $machine -or $materialized.candidateSemanticVerified -ne $true -or $materialized.productionDataMaterialized -ne $true -or $materialized.runtimeTestVolumesPublished -ne $false -or $materialized.actualMountsVerified -ne $true -or $materialized.embeddingProtocolVerified -ne $true -or $materialized.ragManifestVerified -ne $true -or $materialized.actualNativeRowsVerified -ne $true -or $materialized.actualRagRecordsVerified -ne $true -or $materialized.actualNativeContentsVerified -ne $true) { throw 'Pristine native production data was not actually installed and read back.' }
        }
    } catch {
        if (-not $failed) { throw }
        Write-Host 'Cutover summary is unavailable; preserve remote private evidence and maintenance state.'
    }
    if ($failed) { throw $failed }
    return
}
if ($Action -eq 'Rehearse') {
    if ($env:ACTION -ne 'rehearse') { throw 'Rehearse requires the explicit rehearsal action' }
    foreach ($file in @('application-rehearsal.py', 'monolith-ops.py', 'memory-compat.py', 'model-secrets.py', 'assignment-compat.py', 'mcp-compat.py', 'mcp-runtime.py', 'compact-schema-guard.py')) {
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, (Get-PinnedSourceFile "script/docker/$file"), "${destination}:$remoteInbox/$file"))
    }
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'artifacts/source.tar.gz', "${destination}:$remoteInbox/source.tar.gz"))
    $keep = if ($env:REHEARSAL_KEEP -eq 'true') { ' --keep' } else { '' }
    $compatibleFlag = ''
    if (-not [string]::IsNullOrWhiteSpace($env:COMPATIBLE_BACKEND_IMAGE)) {
        $compatibleImage = Require-Value 'COMPATIBLE_BACKEND_IMAGE' '^sha256:[a-f0-9]{64}$'
        $compatibleFlag = " --compatible-backend-image '$compatibleImage'"
    }
    $runnerFlag = ''
    if (-not [string]::IsNullOrWhiteSpace($env:COMPATIBLE_RUNNER_IMAGE)) {
        $runnerImage = Require-Value 'COMPATIBLE_RUNNER_IMAGE' '^sha256:[a-f0-9]{64}$'
        $runnerFlag = " --compatible-runner-image '$runnerImage'"
    }
    $memoryModelFlag = ''
    if (-not [string]::IsNullOrWhiteSpace($env:REHEARSAL_MEMORY_EXTRACTION_MODEL)) {
        $memoryModel = Require-Value 'REHEARSAL_MEMORY_EXTRACTION_MODEL' '^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$'
        $memoryModelFlag = " --memory-extraction-model '$memoryModel'"
    }
    $buildRegistry = Get-BuildRegistryAssignment
    $output = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "$buildRegistry python3 '$remoteInbox/application-rehearsal.py' --root '$remoteRoot' --runtime '$runtime' --tag '$tag' --source-sha256 '$sha'$keep$compatibleFlag$runnerFlag$memoryModelFlag"))
    $receipt = ($output | Select-Object -Last 1) | ConvertFrom-Json
    if ($receipt.passed -ne $true -or $receipt.project -notmatch '^doorhandle-rehearsal-[a-f0-9]{12}$') { throw 'Rehearsal did not pass' }
    $evidence = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "cat '$remoteRoot/rehearsals/$($receipt.project)/result.json'"))
    $report = ($evidence -join "`n") | ConvertFrom-Json
    if ($report.passed -ne $true -or $report.productionChanged -ne $false -or $report.sourceSha256 -ne $sha -or $report.release -ne $tag) { throw 'Rehearsal evidence identity differs' }
    if ($runnerFlag -and $report.compatibleBaselineRunner -ne $runnerImage) { throw 'Rehearsal runner differs from the explicit selection' }
    if ($compatibleFlag -and $report.compatibleBaselineBackend -ne $compatibleImage) { throw 'Rehearsal backend differs from the explicit selection' }
    if ($memoryModelFlag -and $report.selectedMemoryExtractionModel -ne $memoryModel) { throw 'Rehearsal extraction model differs from the explicit selection' }
    $report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath artifacts/application-rehearsal.json -Encoding UTF8
    return
}
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, (Get-PinnedSourceFile 'script/jenkins/deploy-remote.sh'), "${destination}:$remoteInbox/deploy-remote.sh"))
foreach ($file in @('memory-compat.py', 'model-secrets.py', 'assignment-compat.py', 'mcp-compat.py', 'mcp-runtime.py', 'compact-schema-guard.py')) {
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, (Get-PinnedSourceFile "script/docker/$file"), "${destination}:$remoteInbox/$file"))
}
function Save-McpRuntimeEvidence {
    $body = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "cat '$remoteRoot/state/mcp-runtime-transition.json'"))
    $receipt = ($body -join "`n") | ConvertFrom-Json
    if ($receipt.schema -ne 1 -or $receipt.project -ne 'doorhandlecatch-monolith' -or $receipt.phase -notin @('PREPARING','PREPARED','APPLYING','VERIFIED','FINALIZED','RESTORED','NEEDS_REVIEW') -or $receipt.action -notin @('replace','preserve','disabled') -or $receipt.attempt -notmatch '^[a-f0-9]{32}$') { throw 'MCP runtime receipt format is invalid' }
    foreach ($value in @($receipt.selectedImage, $receipt.previousImage)) { if ($value -and $value -notmatch '^sha256:[a-f0-9]{64}$') { throw 'MCP runtime image identity is invalid' } }
    $safe = [pscustomobject]@{ schema=1; project=$receipt.project; phase=$receipt.phase; action=$receipt.action; attempt=$receipt.attempt; revision=$receipt.revision; requiredProtocol=$receipt.requiredProtocol; selectedImage=$receipt.selectedImage; previousImage=$receipt.previousImage; poolVerified=$receipt.poolVerified; retentionVerified=$receipt.retentionVerified; pendingExecutions=$receipt.pendingExecutions; imageOperations=$receipt.imageOperations; checkedAt=$receipt.checkedAt; declarationOnly=$receipt.declarationOnly }
    $safe | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath artifacts/mcp-runtime-transition.json -Encoding UTF8
    return $safe
}
try {
if ($env:ACTION -eq 'rollback') {
    Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "bash '$remoteInbox/deploy-remote.sh' rollback '$remoteRoot' '$runtime' '$tag'"))
} elseif ($env:ACTION -eq 'verify-deploy') {
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'artifacts/source.tar.gz', "${destination}:$remoteInbox/source.tar.gz"))
    $buildRegistry = Get-BuildRegistryAssignment
    Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "$buildRegistry bash '$remoteInbox/deploy-remote.sh' deploy '$remoteRoot' '$runtime' '$tag' '$sha'"))
} else { throw 'Unknown pipeline ACTION' }
} catch {
    $publishFailure = $_
    try { $null = Save-McpRuntimeEvidence } catch { Write-Host 'Runner receipt is unavailable; original deployment error is retained.' }
    throw $publishFailure
}
$memoryTransitionText = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "cat '$remoteRoot/state/memory-transition.json'"))
$memoryTransition = ($memoryTransitionText -join "`n") | ConvertFrom-Json
if ($memoryTransition.phase -ne 'VERIFIED') { throw 'Memory transition has not passed protocol verification' }
$memoryTransition | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath artifacts/memory-transition.json -Encoding UTF8
$modelSecretText = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "cat '$remoteRoot/state/model-secret-transition.json'"))
$modelSecret = ($modelSecretText -join "`n") | ConvertFrom-Json
if ($modelSecret.enabled -eq $true -and $modelSecret.decryptionVerified -ne $true) { throw 'Model key recovery proof is not verified' }
$modelSecret | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath artifacts/model-secret-transition.json -Encoding UTF8
$assignmentText = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "cat '$remoteRoot/state/assignment-transition.json'"))
$assignment = ($assignmentText -join "`n") | ConvertFrom-Json
if ($assignment.schema -ne 1 -or $assignment.project -ne 'doorhandlecatch-monolith' -or $assignment.assignmentWrites -isnot [bool] -or $assignment.declarationOnly -ne $true) { throw 'Assignment format receipt is invalid' }
$assignment | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath artifacts/assignment-transition.json -Encoding UTF8
$mcpText = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "cat '$remoteRoot/state/mcp-transition.json'"))
$mcp = ($mcpText -join "`n") | ConvertFrom-Json
if ($mcp.schema -ne 1 -or $mcp.project -ne 'doorhandlecatch-monolith' -or $mcp.writesEnabled -isnot [bool] -or $mcp.required -notin @(0, 2, 3, 4) -or $mcp.declarationOnly -ne $true) { throw 'MCP protocol receipt is invalid' }
$mcp | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath artifacts/mcp-transition.json -Encoding UTF8
$mcpRuntime = Save-McpRuntimeEvidence
if ($mcpRuntime.schema -ne 1 -or $mcpRuntime.project -ne 'doorhandlecatch-monolith' -or $mcpRuntime.phase -notin @('FINALIZED', 'VERIFIED') -or $mcpRuntime.poolVerified -isnot [bool]) { throw 'MCP runner transition is unverified' }
@{ release = $tag; action = $env:ACTION; host = $targetHost; status = 'healthy'; memoryProtocolRequired = $memoryTransition.requiredProtocol; memoryBridgePreserved = $memoryTransition.preserved; assignmentWrites = $assignment.assignmentWrites; assignmentFormatRequired = $assignment.required; assignmentCompatibilityDeclaredOnly = $assignment.declarationOnly; nativeMcpRequired = $mcp.required; mcpWrites = $mcp.writesEnabled; mcpCompatibilityDeclaredOnly = $mcp.declarationOnly; mcpRuntimeAction = $mcpRuntime.action; mcpRuntimeRequired = $mcpRuntime.requiredProtocol; mcpRuntimePoolVerified = $mcpRuntime.poolVerified } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath artifacts/deployment.json -Encoding UTF8
