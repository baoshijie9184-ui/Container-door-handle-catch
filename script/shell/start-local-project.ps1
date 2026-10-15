[CmdletBinding()]
param(
    [string]$PythonPath = 'D:/ruanjian/anaconda3/envs/leetcode/python.exe',
    [string]$KafkaHome = 'D:/ruanjian/Kafka/kafka_2.13-4.2.0',
    [string]$JavaHome = 'C:/Program Files/Java/jdk-17',
    [string]$MySqlService = 'MySQL83',
    [string]$RedisService = 'Redis',
    [switch]$BuildBackend,
    [switch]$NoAgentUI,
    [switch]$NoFrontend,
    [switch]$OpenBrowser
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$logRoot = Join-Path $projectRoot 'work/middlewares'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$jar = Join-Path $projectRoot 'doorhandle-server/target/doorhandle-server-0.0.1-SNAPSHOT.jar'
if ($BuildBackend -or -not (Test-Path -LiteralPath $jar)) {
    $env:JAVA_HOME = $JavaHome
    $maven = (Get-Command mvn.cmd -ErrorAction Stop).Source
    Push-Location $projectRoot
    try {
        & $maven -B -pl doorhandle-server -am package -DskipTests
        if ($LASTEXITCODE -ne 0) { throw 'Backend build failed' }
    } finally { Pop-Location }
}
& (Join-Path $PSScriptRoot 'start-local-middlewares.ps1') -PythonPath $PythonPath -KafkaHome $KafkaHome -JavaHome $JavaHome -MySqlService $MySqlService -RedisService $RedisService -StartBackend

function Register-Process([string]$Name,[int]$ProcessId) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $process) { return }
    [ordered]@{ name=$Name; pid=$ProcessId; createdAt=$process.CreationDate.ToUniversalTime().ToString('o'); executable=$process.ExecutablePath } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot "$Name.process.json") -Encoding UTF8
}
foreach ($name in @('kafka','chroma','mem0','backend')) {
    $pidFile = Join-Path $logRoot "$name.pid"
    $recordFile = Join-Path $logRoot "$name.process.json"
    if (Test-Path -LiteralPath $pidFile) {
        $processId = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        if ($process -and [Math]::Abs(((Get-Item -LiteralPath $pidFile).LastWriteTimeUtc - $process.CreationDate.ToUniversalTime()).TotalSeconds) -lt 15) {
            Register-Process $name $processId
        }
    }
}
function Start-UI([string]$Name,[string]$Folder,[int]$Port) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
        if (-not $process -or -not $process.CommandLine.Replace('\','/').Contains($Folder.Replace('\','/'))) {
            throw "Port $Port is occupied by another program; this project will not stop it or select a different port."
        }
        Write-Output "$Name already running on $Port"
        return
    }
    $vite = Join-Path $Folder 'node_modules/vite/bin/vite.js'
    if (-not (Test-Path -LiteralPath $vite)) { throw "Dependencies missing in $Folder. Run npm install there first." }
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    $arguments = @($vite,$Folder,'--host','127.0.0.1','--port',"$Port",'--strictPort') | ForEach-Object { '"' + $_ + '"' }
    $oldOpen = $env:DOORHANDLE_DEV_OPEN_BROWSER
    $oldLogin = $env:VITE_BUSINESS_LOGIN_URL
    try {
        $env:DOORHANDLE_DEV_OPEN_BROWSER = 'false'
        if (-not $oldLogin) { $env:VITE_BUSINESS_LOGIN_URL = 'http://127.0.0.1:3001/#/login' }
        $process = Start-Process -FilePath $node -ArgumentList $arguments -WorkingDirectory $Folder -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "$Name.out.log") -RedirectStandardError (Join-Path $logRoot "$Name.err.log")
        $process.Id | Set-Content -LiteralPath (Join-Path $logRoot "$Name.pid")
        Register-Process $Name $process.Id
        Write-Output "$Name started pid=$($process.Id)"
    } finally {
        $env:DOORHANDLE_DEV_OPEN_BROWSER = $oldOpen
        $env:VITE_BUSINESS_LOGIN_URL = $oldLogin
    }
}
function Wait-HTTP([string]$Name,[string]$Url,[int]$Seconds) {
    Add-Type -AssemblyName System.Net.Http
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    $client = [Net.Http.HttpClient]::new([Net.Http.HttpClientHandler]@{UseProxy=$false})
    $client.Timeout = [TimeSpan]::FromSeconds(4)
    try {
        do {
            try {
                $response = $client.GetAsync($Url).GetAwaiter().GetResult()
                if ($response.IsSuccessStatusCode) { Write-Output "$Name ready: $Url"; return }
            } catch { }
            Start-Sleep -Milliseconds 500
        } while ([DateTime]::UtcNow -lt $deadline)
        throw "$Name health check failed. Inspect $logRoot"
    } finally { $client.Dispose() }
}
Wait-HTTP 'Backend' 'http://127.0.0.1:8080/actuator/health' 90
if (-not $NoFrontend) {
    Start-UI 'frontend' (Join-Path $projectRoot 'frontend') 3001
    Wait-HTTP 'Main UI' 'http://127.0.0.1:3001/index.html' 30
}
if (-not $NoAgentUI) {
    Start-UI 'agent-ui' (Join-Path $projectRoot 'frontend-agent') 3003
    Wait-HTTP 'Agent UI' 'http://127.0.0.1:3003/index.html' 30
}
& $PythonPath (Join-Path $PSScriptRoot 'check-local-services.py')
if ($LASTEXITCODE -ne 0) { throw 'One or more local services failed verification' }
Write-Output 'DoorHandleCatch local monolith is ready.'
if (-not $NoFrontend) { Write-Output 'Main UI: http://127.0.0.1:3001/#/login' }
if (-not $NoAgentUI) { Write-Output 'Agent UI: http://127.0.0.1:3003' }
Write-Output "Logs: $logRoot"
if ($OpenBrowser -and -not $NoFrontend) { Start-Process 'http://127.0.0.1:3001/#/login' }
