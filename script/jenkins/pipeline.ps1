param([Parameter(Mandatory = $true)][ValidateSet('Preflight', 'Package', 'PrepareFixtures', 'CleanupFixtures', 'VerifyEcs', 'Publish', 'Rehearse', 'CompactCutover')][string]$Action)
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
New-Item -ItemType Directory -Force -Path artifacts | Out-Null
if ($Action -eq 'Package') {
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $actualCommit = ((Invoke-Checked 'git.exe' @('rev-parse', 'HEAD')) | Select-Object -Last 1).Trim()
    if ($actualCommit -ne $commit -or -not $tag.EndsWith('-' + $commit.Substring(0, 12))) {
        throw 'Package metadata must match the exact checked out commit and release tag.'
    }
    Invoke-Checked 'git.exe' @('diff', '--quiet', 'HEAD', '--')
    Invoke-Checked 'git.exe' @('archive', '--format=tar.gz', '--output=artifacts/source.tar.gz', 'HEAD')
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
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "test ! -e '$remoteInbox/source.tar.gz' && mkdir '$remoteInbox/.fixture-upload'"))
        foreach ($item in @(@('artifacts/source.tar.gz','source.tar.gz'), @('artifacts/application.jar','application.jar'),
                            @('artifacts/fixture-build-artifacts.json','build-artifacts.json'), @('script/jenkins/prepare-compact-fixtures.py','prepare-compact-fixtures.py'))) {
            Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, $item[0], "${destination}:$remoteInbox/$($item[1])"))
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
    if ($env:CI_FIXTURES_PREPARED -eq 'true') {
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "test -f '$remoteInbox/source.tar.gz' && mkdir '$remoteInbox/.verification-upload' && test `"`$(sha256sum '$remoteInbox/source.tar.gz' | cut -d ' ' -f 1)`" = '$sha'"))
    } else {
        Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "test ! -e '$remoteInbox/source.tar.gz' && mkdir '$remoteInbox/.verification-upload'"))
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'artifacts/source.tar.gz', "${destination}:$remoteInbox/source.tar.gz"))
    }
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/jenkins/verify-remote.py', "${destination}:$remoteInbox/verify-remote.py"))
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
if ($Action -eq 'CompactCutover') {
    $commit = Require-Value 'GIT_COMMIT' '^[a-f0-9]{40}$'
    $instance = Require-Value 'DOORHANDLE_ECS_INSTANCE_ID' '^i-[a-z0-9]+$'
    $machine = Require-Value 'DOORHANDLE_ECS_MACHINE_ID' '^[a-f0-9]{32}$'
    $settings = Require-Value 'COMPACT_CUTOVER_SETTINGS' '^/(home|srv|opt)/[A-Za-z0-9_./-]+\.json$'
    if ($settings -match '(^|/)\.\.(/|$)') { throw 'Unsafe private ECS cutover settings path' }
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    $package = Get-Content -LiteralPath artifacts/release.json -Raw | ConvertFrom-Json
    $verified = Get-Content -LiteralPath artifacts/ecs/evidence/verification-receipt.json -Raw | ConvertFrom-Json
    $executed = Get-Content -LiteralPath artifacts/ecs/evidence/reports/receipt.json -Raw | ConvertFrom-Json
    if ($package.release -ne $tag -or $package.commit -ne $commit -or $package.sourceSha256 -ne $sha -or $verified.release -ne $tag -or $verified.commit -ne $commit -or $verified.sourceSha256 -ne $sha -or $verified.scope -ne 'mysql' -or $verified.status -ne 'PASS' -or $verified.fixtureReadinessValidated -ne $true -or $verified.verificationExitCode -ne 0 -or $verified.identity.instanceId -ne $instance -or $verified.identity.machineId -ne $machine) {
        throw 'Cutover cannot use another source, host, scope or failed ECS verification attempt.'
    }
    if ($executed.wholeMigrationRequested -ne $true -or $executed.wholeMigrationTests.passed -le 0 -or $executed.wholeMigrationTests.failed -ne 0 -or $executed.wholeMigrationTests.skipped -ne 0 -or $executed.javaTests.skipped -ne 0) {
        throw 'Whole migration, restoration and MySQL acceptance must actually execute without skipped cases.'
    }
    foreach ($file in @('memory-compat.py', 'model-secrets.py', 'assignment-compat.py', 'mcp-compat.py', 'mcp-runtime.py', 'compact-schema-guard.py', 'compact-cutover.py')) {
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "script/docker/$file", "${destination}:$remoteInbox/$file"))
    }
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/jenkins/deploy-remote.sh', "${destination}:$remoteInbox/deploy-remote.sh"))
    $buildRegistry = Get-BuildRegistryAssignment
    Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "$buildRegistry bash '$remoteInbox/deploy-remote.sh' build-only '$remoteRoot' '$runtime' '$tag' '$sha' '$settings' '$instance' '$machine' '$commit'"))
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "${destination}:$remoteRoot/releases/$tag/candidate-build.json", 'artifacts/compact-candidate-build.json'))
    $buildReceipt = Get-Content -LiteralPath artifacts/compact-candidate-build.json -Raw | ConvertFrom-Json
    if ($buildReceipt.kind -ne 'doorhandle-compact-candidate-build' -or $buildReceipt.status -ne 'BUILT' -or $buildReceipt.commit -ne $commit -or $buildReceipt.sourceSha256 -ne $sha -or $buildReceipt.release -ne $tag -or $buildReceipt.ecs.instanceId -ne $instance -or $buildReceipt.ecs.machineId -ne $machine) {
        throw 'Candidate image/artifact build receipt differs from this fixed Jenkins source.'
    }
    $inputFile = "$remoteRoot/releases/$tag/work/private-cutover-input.json"
    $helper = "$remoteRoot/releases/$tag/script/docker/compact-cutover.py"
    $cutoverArgs = "--root '$remoteRoot' --runtime '$runtime' --tag '$tag' --source-sha256 '$sha' --config '$inputFile'"
    $failed = $null
    try {
        foreach ($phase in @('prepare', 'migrate', 'activate')) {
            $gate = if ($phase -eq 'activate') { 'DOORHANDLE_COMPACT_RELEASE_READY=true ' } else { '' }
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
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "script/docker/$file", "${destination}:$remoteInbox/$file"))
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
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/jenkins/deploy-remote.sh', "${destination}:$remoteInbox/deploy-remote.sh"))
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/docker/memory-compat.py', "${destination}:$remoteInbox/memory-compat.py"))
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/docker/model-secrets.py', "${destination}:$remoteInbox/model-secrets.py"))
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/docker/assignment-compat.py', "${destination}:$remoteInbox/assignment-compat.py"))
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/docker/mcp-compat.py', "${destination}:$remoteInbox/mcp-compat.py"))
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/docker/mcp-runtime.py', "${destination}:$remoteInbox/mcp-runtime.py"))
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/docker/compact-schema-guard.py', "${destination}:$remoteInbox/compact-schema-guard.py"))
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
