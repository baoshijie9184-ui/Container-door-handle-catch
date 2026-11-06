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
$directoryAcl = [System.Security.AccessControl.DirectorySecurity]::new()
$directoryAcl.SetOwner($identity)
$directoryAcl.SetAccessRuleProtection($true, $false)
$directoryAcl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
    $identity, 'FullControl',
    ([System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit),
    [System.Security.AccessControl.PropagationFlags]::None, 'Allow'))
Set-Acl -LiteralPath $agentRoot -AclObject $directoryAcl
$identity.Value | Set-Content -LiteralPath (Join-Path $agentRoot '.owner-only') -Encoding ascii
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
$acl = [System.Security.AccessControl.FileSecurity]::new()
$acl.SetOwner($identity)
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new($identity, 'FullControl', 'Allow'))
Set-Acl -LiteralPath $secretFile -AclObject $acl
if ($DownloadAgent -or -not (Test-Path -LiteralPath $agentJar -PathType Leaf)) {
    Invoke-WebRequest -Uri 'http://127.0.0.1:8080/jnlpJars/agent.jar' -OutFile $agentJar -TimeoutSec 15 | Out-Null
}
$arguments = '-jar "{0}" -url http://127.0.0.1:8080/ -name doorhandle-local-ci -secret "@{1}" -webSocket -workDir "{2}"' -f $agentJar, $secretFile, $agentRoot
$process = Start-Process -FilePath $JavaExe -ArgumentList $arguments -WindowStyle Hidden -PassThru `
    -WorkingDirectory $agentRoot `
    -RedirectStandardOutput (Join-Path $agentRoot 'agent.out.log') `
    -RedirectStandardError (Join-Path $agentRoot 'agent.err.log')
$process.Id | Set-Content -LiteralPath $pidFile
Write-Output "Local Jenkins agent started: PID $($process.Id). No ECS or project tests were started."
