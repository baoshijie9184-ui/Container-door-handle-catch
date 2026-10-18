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
    foreach ($file in @('application-rehearsal.py', 'monolith-ops.py', 'memory-compat.py')) {
        Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, "script/docker/$file", "${destination}:$remoteInbox/$file"))
    }
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'artifacts/source.tar.gz', "${destination}:$remoteInbox/source.tar.gz"))
    $keep = if ($env:REHEARSAL_KEEP -eq 'true') { ' --keep' } else { '' }
    $output = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "python3 '$remoteInbox/application-rehearsal.py' --root '$remoteRoot' --runtime '$runtime' --tag '$tag' --source-sha256 '$sha'$keep"))
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
if ($env:ACTION -eq 'rollback') {
    Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "bash '$remoteInbox/deploy-remote.sh' rollback '$remoteRoot' '$runtime' '$tag'"))
} elseif ($env:ACTION -eq 'verify-deploy') {
    $sha = (Get-FileHash -LiteralPath artifacts/source.tar.gz -Algorithm SHA256).Hash.ToLowerInvariant()
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P', $portText, 'artifacts/source.tar.gz', "${destination}:$remoteInbox/source.tar.gz"))
    Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "bash '$remoteInbox/deploy-remote.sh' deploy '$remoteRoot' '$runtime' '$tag' '$sha'"))
} else { throw 'Unknown pipeline ACTION' }
$memoryTransitionText = Invoke-Checked 'ssh.exe' ($sshOptions + @('-p', $portText, $destination, "cat '$remoteRoot/state/memory-transition.json'"))
$memoryTransition = ($memoryTransitionText -join "`n") | ConvertFrom-Json
if ($memoryTransition.phase -ne 'VERIFIED') { throw 'Memory transition has not passed protocol verification' }
$memoryTransition | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath artifacts/memory-transition.json -Encoding UTF8
@{ release = $tag; action = $env:ACTION; host = $targetHost; status = 'healthy'; memoryProtocolRequired = $memoryTransition.requiredProtocol; memoryBridgePreserved = $memoryTransition.preserved } | ConvertTo-Json | Set-Content -LiteralPath artifacts/deployment.json -Encoding UTF8
