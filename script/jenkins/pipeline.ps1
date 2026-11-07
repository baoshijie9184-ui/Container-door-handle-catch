param([Parameter(Mandatory = $true)][ValidateSet('Preflight', 'Package', 'PrepareTools', 'CleanupTools', 'PrepareFixtures', 'CleanupFixtures', 'VerifyEcs', 'VerifyEmbedding', 'PreserveLegacy', 'PrepareLegacyCandidate', 'CleanupLegacyCandidate', 'VerifyRuntime', 'CleanupRuntime', 'Publish', 'Rehearse', 'CompactCutover')][string]$Action)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path

function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Command failed with exit $LASTEXITCODE" }
}
function Require-Value([string]$Name, [string]$Pattern) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value) -or $value -notmatch $Pattern) { throw "Invalid or missing $Name" }
    return $value
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

$tag = Require-Value 'RELEASE_TAG' '^ci-[0-9]+-[a-f0-9]{12}$'
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
}
if ($Action -eq 'VerifyRuntime' -and ($env:ACTION -ne 'verify-runtime' -or $env:DOORHANDLE_CI_SCOPE -ne 'mysql' -or $env:CI_ECS_VERIFIED -ne 'true')) {
    throw 'Runtime acceptance requires this build passing the complete MySQL ECS verification.'
}
if ($Action -in @('VerifyRuntime', 'CompactCutover') -and $env:CI_LEGACY_CANDIDATE_PREPARED -ne 'true') {
    throw 'Runtime acceptance requires this fixed build preserved native data candidate.'
}
New-Item -ItemType Directory -Force -Path artifacts | Out-Null
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
if ($Action -eq 'Preflight') {
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
if ($Action -eq 'PreserveLegacy') {
    if ($env:CI_ECS_VERIFIED -ne 'true') { throw 'Original source preservation requires this fixed commit ECS source verification first.' }
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    & ./script/jenkins/preserve-legacy-input.ps1 -SshOptions $sshOptions -Destination $destination -PortText $portText -RemoteRoot $remoteRoot -Tag $tag -Commit $commit -SourceSha256 $sha -SnapshotDirectory $env:LEGACY_SOURCE_SNAPSHOT
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
        $preservation = Get-Content -LiteralPath artifacts/legacy-source-preservation.json -Raw | ConvertFrom-Json
        if ($preservation.status -ne 'RESTORED_VERIFIED' -or $preservation.release -ne $tag -or $preservation.commit -ne $commit -or $preservation.sourceSha256 -ne $sha -or $preservation.identity.instanceId -ne $instance -or $preservation.identity.machineId -ne $machine) {
            throw 'Native data candidate requires this exact build byte-preserved and independently recovered legacy inputs.'
        }
        if ($preservation.profile -cne 'legacy-stores-with-windows-mcp-and-kafka-v1' -or $preservation.kafkaFiles -ne 309 -or $preservation.kafkaBytes -ne 1184990233 -or $preservation.archiveEncoding -cne 'TAR_GZIP' -or $preservation.legacyKafkaReplay -cne 'NOT_PERFORMED') {
            throw 'Complete runtime acceptance requires the full old Kafka log archive without replaying it.'
        }
        $output = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "${helperGuard}python3 -B '$helper' run $arguments --dimension 256"))
        $prepared = ($output | Select-Object -Last 1) | ConvertFrom-Json
        if ($prepared.status -ne 'PREPARED' -or $prepared.release -ne $tag -or $prepared.commit -ne $commit -or $prepared.sourceSha256 -ne $sha -or $prepared.identity.instanceId -ne $instance -or $prepared.identity.machineId -ne $machine -or $prepared.identity.executionLocation -ne 'ECS' -or $prepared.descriptorSha256 -notmatch '^[a-f0-9]{64}$' -or $prepared.ragManifestSha256 -notmatch '^[a-f0-9]{64}$' -or $prepared.publicSummarySha256 -notmatch '^[a-f0-9]{64}$' -or $prepared.legacyRagRecords -ne 83 -or $prepared.modelCallsPerformed -ne $false -or $prepared.productionPromotionAllowed -ne $false) {
            throw 'Native data candidate does not prove fixed-source preservation without paid calls or promotion.'
        }
        # This public summary contains only counts, hashes and status. Private
        # source text, per-record inventories and candidate paths stay on ECS.
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/verification/$tag/checkout/work/legacy-candidate/public-summary.json", 'artifacts/legacy-candidate.json'))
        $summaryFile = Get-Item -LiteralPath artifacts/legacy-candidate.json
        if ($summaryFile.Length -le 0 -or $summaryFile.Length -gt 262144 -or (Get-FileHash -LiteralPath $summaryFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $prepared.publicSummarySha256) { throw 'Native candidate public evidence changed during collection.' }
        $summary = Get-Content -LiteralPath $summaryFile.FullName -Raw | ConvertFrom-Json
        foreach ($key in @('status', 'release', 'commit', 'sourceSha256', 'descriptorSha256', 'ragManifestSha256', 'legacyRagRecords', 'modelCallsPerformed', 'productionPromotionAllowed')) {
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
            if ($outcome.status -notin @('PREPARED', 'FAILED') -or $outcome.release -ne $tag -or $outcome.commit -ne $commit -or $outcome.sourceSha256 -ne $sha -or $outcome.identity.instanceId -ne $instance -or $outcome.identity.machineId -ne $machine -or $outcome.modelCallsPerformed -ne $false -or $outcome.productionPromotionAllowed -ne $false) { throw 'Native candidate final outcome belongs to another build or data policy.' }
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
        $result = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "python3 -B '$remoteInbox/prepare-ecs-tools.py' $arguments"))
        $prepared = ($result | Select-Object -Last 1) | ConvertFrom-Json
        if ($prepared.status -ne 'PREPARED' -or $prepared.release -ne $tag -or $prepared.commit -ne $commit -or $prepared.sourceSha256 -ne $sha) { throw 'ECS tool image preparation did not return matching source evidence.' }
        foreach ($image in @($prepared.mavenImageId, $prepared.nodeImageId, $prepared.pythonImageId)) {
            if ($image -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Prepared ECS tools require immutable image IDs.' }
        }
        $prepared | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath artifacts/ecs-tool-preparation.json -Encoding utf8
        $result = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "python3 -B '$executor' prepare $arguments --maven-image '$($prepared.mavenImageId)' --node-image '$($prepared.nodeImageId)' --python-image '$($prepared.pythonImageId)'"))
        $registered = ($result | Select-Object -Last 1) | ConvertFrom-Json
        if ($registered.status -ne 'PREPARED' -or $registered.release -ne $tag -or $registered.manifest -ne "$remoteInbox/tool-runtime/manifest.json" -or $registered.manifestSha256 -notmatch '^[a-f0-9]{64}$') { throw 'ECS tool registration differs from the fixed build inbox.' }
        $registered | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath artifacts/ecs-tool-runtime.json -Encoding utf8
    } else {
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
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, (Get-PinnedSourceFile 'script/jenkins/verify-remote.py'), "${destination}:$remoteInbox/verify-remote.py"))
    $manifestFlag = if ($scope -eq 'mysql') { " --fixture-manifest '$fixture'" } else { '' }
    $remoteCommand = "python3 -B '$remoteInbox/verify-remote.py' --root '$remoteRoot' --tag '$tag' --source-sha256 '$sha' --commit '$commit' --instance-id '$instance' --machine-id '$machine' --scope '$scope' --attempt '$attempt'$manifestFlag"
    $verifyExit = 1
    try {
        $verifyArguments = $sshOptions + @('-p', $portText, $destination, $remoteCommand)
        & 'ssh.exe' @verifyArguments
        $verifyExit = $LASTEXITCODE
    } catch {
        if ($LASTEXITCODE) { $verifyExit = $LASTEXITCODE }
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
    function Receive-RuntimeResource([string]$Name, [string]$Digest) {
        $names = @('resource-summary.json', 'resource-probes.jsonl',
            'resource-phase-1-runtime-start.json', 'resource-phase-2-runtime-backup.json', 'resource-phase-3-runtime-restore.json')
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
    if ($Action -eq 'CleanupRuntime') {
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
        if ($cleanupEvidence -and $cleanupEvidence.resourceEvidence) {
            $reference = $cleanupEvidence.resourceEvidence
            if ($reference.file -ne 'checkout/work/runtime-acceptance/resource-summary.json') { throw 'Unexpected failed runtime resource evidence location.' }
            $summary = Receive-RuntimeResource 'resource-summary.json' $reference.sha256
            if ($summary.release -ne $tag -or $summary.commit -ne $commit -or $summary.sourceSha256 -ne $sha -or $summary.project -ne $cleanupEvidence.project) { throw 'Failed runtime resource observations belong to another build.' }
            if ($summary.rawProbeSha256) {
                if ($summary.rawProbeFile -ne 'checkout/work/runtime-acceptance/resource-probes.jsonl') { throw 'Unexpected failed runtime probe location.' }
                Receive-RuntimeResource 'resource-probes.jsonl' $summary.rawProbeSha256
            }
            if (@($summary.phases).Count -gt 3) { throw 'Failed runtime phase evidence exceeds its bound.' }
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
    if (Test-Path -LiteralPath artifacts/fixture-build-artifacts.json) {
        $existingPlan = Get-Content -LiteralPath artifacts/fixture-build-artifacts.json -Raw | ConvertFrom-Json
        foreach ($key in $artifactPlan.Keys) { if ($existingPlan.$key -ne $artifactPlan[$key]) { throw 'Candidate and fixture artifact plans differ.' } }
    } else {
        $artifactPlan | ConvertTo-Json | Set-Content -LiteralPath artifacts/fixture-build-artifacts.json -Encoding utf8
    }
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'artifacts/application.jar', "${destination}:$remoteInbox/application.jar"))
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'artifacts/fixture-build-artifacts.json', "${destination}:$remoteInbox/build-artifacts.json"))
    Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "chmod 600 '$remoteInbox/application.jar' '$remoteInbox/build-artifacts.json'"))
    foreach ($file in @('memory-compat.py', 'model-secrets.py', 'assignment-compat.py', 'mcp-compat.py', 'mcp-runtime.py', 'compact-schema-guard.py', 'compact-cutover.py')) {
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, (Get-PinnedSourceFile "script/docker/$file"), "${destination}:$remoteInbox/$file"))
    }
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, (Get-PinnedSourceFile 'script/jenkins/deploy-remote.sh'), "${destination}:$remoteInbox/deploy-remote.sh"))
    $buildRegistry = Get-BuildRegistryAssignment
    Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "$buildRegistry bash '$remoteInbox/deploy-remote.sh' build-only '$remoteRoot' '$runtime' '$tag' '$sha' '$settings' '$instance' '$machine' '$commit'"))
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/releases/$tag/candidate-build.json", 'artifacts/compact-candidate-build.json'))
    $buildReceipt = Get-Content -LiteralPath artifacts/compact-candidate-build.json -Raw | ConvertFrom-Json
    if ($buildReceipt.kind -ne 'doorhandle-compact-candidate-build' -or $buildReceipt.status -ne 'BUILT' -or $buildReceipt.commit -ne $commit -or $buildReceipt.sourceSha256 -ne $sha -or $buildReceipt.release -ne $tag -or $buildReceipt.ecs.instanceId -ne $instance -or $buildReceipt.ecs.machineId -ne $machine) {
        throw 'Candidate image/artifact build receipt differs from this fixed Jenkins source.'
    }
    if ($buildReceipt.applicationJarSha256 -ne $jarSha -or $buildReceipt.applicationJarBytes -ne $jarBytes) { throw 'The built image does not contain this pipeline application jar.' }
    $result = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "python3 -B '$runtimeHelper' run $runtimeArguments"))
    $runtimeResult = ($result | Select-Object -Last 1) | ConvertFrom-Json
    if ($runtimeResult.status -ne 'PASS' -or $runtimeResult.release -ne $tag -or $runtimeResult.runtimeScenarios -lt 9 -or $runtimeResult.ownedCleanup -ne 'STOPPED' -or $runtimeResult.runtimeReceiptSha256 -notmatch '^[a-f0-9]{64}$') { throw 'Complete application runtime acceptance did not pass and clean up its owned resources.' }
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/verification/$tag/runtime-acceptance.json", 'artifacts/runtime-acceptance.json'))
    if ((Get-FileHash -LiteralPath artifacts/runtime-acceptance.json -Algorithm SHA256).Hash.ToLowerInvariant() -ne $runtimeResult.runtimeReceiptSha256) { throw 'The actual runtime acceptance receipt changed during collection.' }
    $runtimeProof = Get-Content -LiteralPath artifacts/runtime-acceptance.json -Raw | ConvertFrom-Json
    $candidateSha = (Get-FileHash -LiteralPath artifacts/compact-candidate-build.json -Algorithm SHA256).Hash.ToLowerInvariant()
    $wholeProof = Get-Content -LiteralPath artifacts/ecs/evidence/reports/migration.json -Raw | ConvertFrom-Json
    if ($runtimeProof.status -ne 'PASS' -or $runtimeProof.commit -ne $commit -or $runtimeProof.release -ne $tag -or $runtimeProof.sourceSha256 -ne $sha -or $runtimeProof.candidateBuildSha256 -ne $candidateSha -or $runtimeProof.acceptanceProfileSha256 -ne $verified.acceptanceProfileSha256 -or $runtimeProof.migrationReceiptSha256 -ne $wholeProof.migrationReceiptSha256 -or $runtimeProof.initialTargetSnapshotSha256 -ne $wholeProof.targetSnapshotSha256 -or $runtimeProof.identity.instanceId -ne $instance -or $runtimeProof.identity.machineId -ne $machine -or $runtimeProof.paidModelCalls -ne 0) { throw 'Application acceptance proof belongs to another build, dataset, image or execution host.' }
    $nativeCandidate = Get-Content -LiteralPath artifacts/legacy-candidate.json -Raw | ConvertFrom-Json
    $native = $runtimeProof.legacyData
    if ($native.legacyKafkaFiles -ne 309 -or $native.legacyKafkaBytes -ne 1184990233 -or $native.legacyKafkaReplay -cne 'NOT_PERFORMED') { throw 'Runtime acceptance lacks the original Kafka archive preservation boundary.' }
    if ($native.candidateSha256 -ne $nativeCandidate.descriptorSha256 -or $native.ragManifestSha256 -ne $nativeCandidate.ragManifestSha256 -or $native.originalLocalMem0Records -ne 32 -or $native.eligibleLocalMem0Records -ne 30 -or $native.activatedLocalMem0Records -ne 0 -or $native.archivedLocalMem0Records -ne 2 -or $native.localMem0SemanticStatus -ne 'NOT_ACTIVATED_SEMANTIC_NOT_VERIFIED' -or $native.productionPromotionAllowed -ne $false) { throw 'Runtime did not retain the admitted legacy data and its explicit semantic activation boundary.' }
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
        if ($proof.kind -ne 'doorhandle-legacy-runtime-readback' -or $proof.status -ne 'VERIFIED' -or $proof.phase -ne $phase -or $proof.commit -ne $commit -or $proof.release -ne $tag -or $proof.sourceSha256 -ne $sha -or $proof.candidateBuildSha256 -ne $candidateSha -or $proof.project -ne $runtimeProof.project -or $proof.identity.instanceId -ne $instance -or $proof.identity.machineId -ne $machine -or $proof.descriptorSha256 -ne $nativeCandidate.descriptorSha256 -or $proof.ragManifestSha256 -ne $nativeCandidate.ragManifestSha256 -or $proof.retrievalQueries -lt 83 -or $proof.sourceAndDocumentAndFloat32Verified -ne $true -or $proof.activatedLocalMem0Records -ne 0 -or $proof.localMem0SemanticStatus -ne 'NOT_ACTIVATED_SEMANTIC_NOT_VERIFIED' -or $proof.paidModelCalls -ne 0 -or $proof.productionPromotionAllowed -ne $false) { throw 'Native data readback did not verify this exact candidate without semantic activation or paid calls.' }
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
    if ($cleanupEvidence.status -ne 'STOPPED' -or $cleanupEvidence.unresolved.Count -ne 0 -or $cleanupEvidence.stoppedContainers.Count -eq 0 -or $cleanupEvidence.sourceResourcesChanged -ne $false -or $cleanupEvidence.commit -ne $commit -or $cleanupEvidence.release -ne $tag -or $cleanupEvidence.sourceSha256 -ne $sha -or $cleanupEvidence.candidateBuildSha256 -ne $candidateSha -or $cleanupEvidence.project -ne $runtimeProof.project) { throw 'Runtime cleanup did not prove this build owned resources were stopped.' }
    $resourceReference = $runtimeProof.resourceEvidence
    if ($resourceReference.file -ne 'checkout/work/runtime-acceptance/resource-summary.json' -or $resourceReference.sha256 -notmatch '^[a-f0-9]{64}$' -or $cleanupEvidence.resourceEvidence.file -ne $resourceReference.file -or $cleanupEvidence.resourceEvidence.sha256 -ne $resourceReference.sha256) { throw 'Runtime resources and cleanup lack a common bound evidence reference.' }
    $resourceSummary = Receive-RuntimeResource 'resource-summary.json' $resourceReference.sha256
    if ($resourceSummary.rawProbeFile -ne 'checkout/work/runtime-acceptance/resource-probes.jsonl') { throw 'Unexpected resource probe evidence location.' }
    Receive-RuntimeResource 'resource-probes.jsonl' $resourceSummary.rawProbeSha256
    if (@($resourceSummary.phases).Count -ne 3) { throw 'Runtime resource phase evidence is incomplete.' }
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
        '--phase-directory', (Resolve-Path artifacts/runtime-resources).Path)
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
        if (-not $failed -and ($summary.phase -ne 'ACTIVE' -or $summary.status -ne 'ACTIVE' -or $summary.sourceRestorationAllowed -ne $false -or $summary.migrationReceiptSha256 -notmatch '^[a-f0-9]{64}$')) { throw 'Cutover health/publication evidence is incomplete.' }
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
