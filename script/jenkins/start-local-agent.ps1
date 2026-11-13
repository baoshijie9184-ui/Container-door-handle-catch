param(
    [string]$JavaExe = '',
    [switch]$DownloadAgent,
    [switch]$PrepareOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$agentRoot = Join-Path $projectRoot 'work/jenkins/local-agent'
if (-not $JavaExe) { $JavaExe = Join-Path $projectRoot 'work/jenkins/runtime/jdk-25.0.5+8-jre/bin/java.exe' }
$agentJar = Join-Path $agentRoot 'agent.jar'
$secretFile = Join-Path $agentRoot 'secret'
$pidFile = Join-Path $agentRoot 'agent.pid'
New-Item -ItemType Directory -Path $agentRoot -Force | Out-Null
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User

function Test-OwnerOnlyAcl($Acl, [System.Security.Principal.SecurityIdentifier]$Owner, [bool]$Directory) {
    if (-not $Acl.AreAccessRulesProtected -or $Acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $Owner.Value) { return $false }
    $rules = @($Acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
    if ($rules.Count -ne 1) { return $false }
    $rule = $rules[0]
    $inheritance = [System.Security.AccessControl.InheritanceFlags]::None
    if ($Directory) { $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit }
    return $rule.IdentityReference.Value -eq $Owner.Value -and -not $rule.IsInherited -and `
        $rule.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow -and `
        $rule.FileSystemRights -eq [System.Security.AccessControl.FileSystemRights]::FullControl -and `
        $rule.InheritanceFlags -eq $inheritance -and `
        $rule.PropagationFlags -eq [System.Security.AccessControl.PropagationFlags]::None
}

function Protect-OwnerOnlyPath([string]$LiteralPath, [System.Security.Principal.SecurityIdentifier]$Owner, [bool]$Directory) {
    $item = Get-Item -LiteralPath $LiteralPath -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or $item.PSIsContainer -ne $Directory) {
        throw 'The local agent private path must be a regular directory or file, without links.'
    }
    # Read neither audit rules nor SACL. Set-Acl can attempt to persist those
    # sections even when only an owner/DACL was supplied, requiring privileges
    # that an ordinary local Jenkins account should not need.
    $sections = [System.Security.AccessControl.AccessControlSections]::Access -bor [System.Security.AccessControl.AccessControlSections]::Owner
    $current = [System.IO.FileSystemAclExtensions]::GetAccessControl($item, $sections)
    if (Test-OwnerOnlyAcl $current $Owner $Directory) { return }
    if ($Directory) { $replacement = [System.Security.AccessControl.DirectorySecurity]::new() }
    else { $replacement = [System.Security.AccessControl.FileSecurity]::new() }
    if ($current.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $Owner.Value) { $replacement.SetOwner($Owner) }
    $replacement.SetAccessRuleProtection($true, $false)
    if ($Directory) {
        $replacement.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
            $Owner, 'FullControl',
            ([System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit),
            [System.Security.AccessControl.PropagationFlags]::None, 'Allow'))
    } else {
        $replacement.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new($Owner, 'FullControl', 'Allow'))
    }
    # This API persists only sections marked modified: Access and, when needed,
    # Owner. It does not request SeSecurityPrivilege or alter the existing SACL.
    [System.IO.FileSystemAclExtensions]::SetAccessControl($item, $replacement)
    $observed = [System.IO.FileSystemAclExtensions]::GetAccessControl($item, $sections)
    if (-not (Test-OwnerOnlyAcl $observed $Owner $Directory)) { throw 'Local agent owner-only ACL could not be verified.' }
}

Protect-OwnerOnlyPath $agentRoot $identity $true
$ownerMarker = Join-Path $agentRoot '.owner-only'
if (-not (Test-Path -LiteralPath $ownerMarker -PathType Leaf) -or (Get-Content -LiteralPath $ownerMarker -Raw).Trim() -ne $identity.Value) {
    $identity.Value | Set-Content -LiteralPath $ownerMarker -Encoding ascii
}
if (Test-Path -LiteralPath $secretFile -PathType Leaf) { Protect-OwnerOnlyPath $secretFile $identity $false }
if ($PrepareOnly) { Write-Output 'Local agent directory prepared with owner-only ACL. No processes were started.'; return }
if (-not (Test-Path -LiteralPath $JavaExe -PathType Leaf)) { throw 'Select the existing Jenkins Java runtime.' }
if (-not (Test-Path -LiteralPath $secretFile -PathType Leaf)) { throw 'Run configure-local.groovy before starting the local agent.' }
if (Test-Path -LiteralPath $pidFile) {
    $recordedProcessId = [int](Get-Content -LiteralPath $pidFile -Raw)
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedProcessId" -ErrorAction SilentlyContinue
    if ($existing -and $existing.CommandLine -like '*-name doorhandle-local-ci*' -and $existing.ExecutablePath -eq (Resolve-Path -LiteralPath $JavaExe).Path) {
        Write-Output "Local Jenkins agent already running: PID $recordedProcessId"
        return
    }
}
if ($DownloadAgent -or -not (Test-Path -LiteralPath $agentJar -PathType Leaf)) {
    Invoke-WebRequest -Uri 'http://127.0.0.1:8080/jnlpJars/agent.jar' -OutFile $agentJar -TimeoutSec 15 | Out-Null
}
$arguments = '-jar "{0}" -url http://127.0.0.1:8080/ -name doorhandle-local-ci -secret "@{1}" -webSocket -workDir "{2}"' -f $agentJar, $secretFile, $agentRoot
. (Join-Path $PSScriptRoot 'start-detached-java.ps1')
$process = Start-DetachedJenkinsJava -JavaExe (Resolve-Path -LiteralPath $JavaExe).Path -Arguments $arguments `
    -WorkingDirectory $agentRoot -StandardOutput (Join-Path $agentRoot 'agent.out.log') `
    -StandardError (Join-Path $agentRoot 'agent.err.log') -PidFile $pidFile
Write-Output "Local Jenkins agent started: PID $($process.Id). No ECS or project tests were started."
