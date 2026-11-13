param(
    [Parameter(Mandatory = $true)][string]$WarPath,
    [Parameter(Mandatory = $true)][string]$JavaExe,
    [Parameter(Mandatory = $true)][string]$JenkinsDataDir,
    [ValidateRange(1024, 65535)][int]$Port = 8080
)
$ErrorActionPreference = 'Stop'
foreach ($file in @($WarPath, $JavaExe)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Existing file not found: $file" }
}
if (-not (Test-Path -LiteralPath (Join-Path $JenkinsDataDir 'config.xml'))) { throw 'Select an existing Jenkins home with config.xml; no fresh installation is created.' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "Port $Port is already in use." }
$logDir = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path 'work/jenkins'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
. (Join-Path $PSScriptRoot 'start-detached-java.ps1')
$resolvedWar = (Resolve-Path -LiteralPath $WarPath).Path
$arguments = '-jar "{0}" --httpListenAddress=127.0.0.1 --httpPort={1}' -f $resolvedWar, $Port
$process = Start-DetachedJenkinsJava -JavaExe (Resolve-Path -LiteralPath $JavaExe).Path -Arguments $arguments `
    -WorkingDirectory (Split-Path -Parent $resolvedWar) -StandardOutput (Join-Path $logDir 'jenkins.out.log') `
    -StandardError (Join-Path $logDir 'jenkins.err.log') -PidFile (Join-Path $logDir 'jenkins.pid') `
    -EnvironmentOverrides @{JENKINS_HOME=(Resolve-Path -LiteralPath $JenkinsDataDir).Path}
Write-Output "Existing Jenkins process started: PID $($process.Id), http://127.0.0.1:$Port/"
