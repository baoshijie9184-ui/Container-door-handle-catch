param([Parameter(Mandatory = $true)][ValidateSet('Preflight', 'Package', 'Publish', 'Rehearse')][string]$Action)
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

$tag = Require-Value 'RELEASE_TAG' '^ci-[0-9]+-[a-f0-9]{12}$'
New-Item -ItemType Directory -Force -Path artifacts | Out-Null
if ($Action -eq 'Package') {
    Invoke-Checked 'git.exe' @('diff', '--exit-code', 'HEAD', '--')
    Invoke-Checked 'git.exe' @('archive', '--format=tar.gz', '--output=artifacts/source.tar.gz', 'HEAD')
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    @{ release = $tag; commit = $env:GIT_COMMIT; sourceSha256 = $sha } | ConvertTo-Json | Set-Content -LiteralPath artifacts/release.json -Encoding UTF8
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
$keyAcl = New-Object System.Security.AccessControl.FileSecurity
$keyAcl.SetOwner($identity)
$keyAcl.SetAccessRuleProtection($true, $false)
$keyAcl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')))
Set-Acl -LiteralPath $env:DEPLOY_KEY -AclObject $keyAcl
$sshOptions = @('-i', $env:DEPLOY_KEY, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', "UserKnownHostsFile=$env:DEPLOY_KNOWN_HOSTS", '-o', 'ConnectTimeout=12', '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3')
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
if ($Action -eq 'Rehearse') {
    if ($env:ACTION -ne 'rehearse') { throw 'Rehearse requires the explicit rehearsal action' }
    foreach ($file in @('application-rehearsal.py', 'monolith-ops.py', 'memory-compat.py', 'model-secrets.py', 'assignment-compat.py', 'mcp-compat.py', 'mcp-runtime.py')) {
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
    $output = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "python3 '$remoteInbox/application-rehearsal.py' --root '$remoteRoot' --runtime '$runtime' --tag '$tag' --source-sha256 '$sha'$keep$compatibleFlag"))
    $receipt = ($output | Select-Object -Last 1) | ConvertFrom-Json
    if ($receipt.passed -ne $true -or $receipt.project -notmatch '^doorhandle-rehearsal-[a-f0-9]{12}$') { throw 'Rehearsal did not pass' }
    $evidence = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "cat '$remoteRoot/rehearsals/$($receipt.project)/result.json'"))
    $report = ($evidence -join "`n") | ConvertFrom-Json
    if ($report.passed -ne $true -or $report.productionChanged -ne $false -or $report.sourceSha256 -ne $sha -or $report.release -ne $tag) { throw 'Rehearsal evidence identity differs' }
    $report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath artifacts/application-rehearsal.json -Encoding UTF8
    return
}
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/jenkins/deploy-remote.sh', "${destination}:$remoteInbox/deploy-remote.sh"))
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/docker/memory-compat.py', "${destination}:$remoteInbox/memory-compat.py"))
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/docker/model-secrets.py', "${destination}:$remoteInbox/model-secrets.py"))
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/docker/assignment-compat.py', "${destination}:$remoteInbox/assignment-compat.py"))
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/docker/mcp-compat.py', "${destination}:$remoteInbox/mcp-compat.py"))
Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'script/docker/mcp-runtime.py', "${destination}:$remoteInbox/mcp-runtime.py"))
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
    Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "bash '$remoteInbox/deploy-remote.sh' deploy '$remoteRoot' '$runtime' '$tag' '$sha'"))
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
