[CmdletBinding()]
param(
    [string]$PythonPath = 'D:/ruanjian/anaconda3/envs/leetcode/python.exe',
    [string]$KafkaHome = 'D:/ruanjian/Kafka/kafka_2.13-4.2.0',
    [string]$JavaHome = 'C:/Program Files/Java/jdk-17',
    [string]$MySqlService = 'MySQL83',
    [string]$RedisService = 'Redis',
    [switch]$StartBackend
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$logRoot = Join-Path $projectRoot 'work/middlewares'
New-Item -ItemType Directory -Force -Path $logRoot,(Join-Path $logRoot 'tmp'),(Join-Path $logRoot 'chroma') | Out-Null
# dotenv-java 拒绝重复键，启动前检查文件，避免悄悄使用默认连接。
$envFile = Join-Path $projectRoot '.env'
if (Test-Path -LiteralPath $envFile) {
    $keys = @{}
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=') {
            $key = $Matches[1]
            if ($keys.ContainsKey($key)) { throw "Duplicate .env key: $key. Resolve it before starting services." }
            $keys[$key] = $true
        }
    }
}
function Listening([int]$Port) {
    $client = [Net.Sockets.TcpClient]::new()
    try { return $client.ConnectAsync('127.0.0.1', $Port).Wait(700) -and $client.Connected }
    catch { return $false }
    finally { $client.Dispose() }
}
function Start-Background([string]$Name,[string]$Executable,[string[]]$Arguments,[string]$Directory) {
    if (-not (Test-Path -LiteralPath $Executable)) { throw "Executable not found: $Executable" }
    $quoted = $Arguments | ForEach-Object { '"' + $_.Replace('"','\"') + '"' }
    $process = Start-Process -FilePath $Executable -ArgumentList $quoted -WorkingDirectory $Directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "$Name.out.log") -RedirectStandardError (Join-Path $logRoot "$Name.err.log")
    $process.Id | Set-Content -LiteralPath (Join-Path $logRoot "$Name.pid")
    Write-Output "$Name started pid=$($process.Id)"
}
foreach ($serviceName in @($MySqlService,$RedisService)) {
    $service = Get-Service -Name $serviceName
    if ($service.Status -ne 'Running') { Start-Service -Name $serviceName }
    Write-Output "$serviceName service running"
}
if (-not (Listening 9092)) {
    $config = Join-Path $logRoot 'kafka-server.properties'
    $data = Join-Path $logRoot 'kafka-data'
    $java = Join-Path $JavaHome 'bin/java.exe'
    New-Item -ItemType Directory -Force -Path $data | Out-Null
    $properties = @"
process.roles=broker,controller
node.id=1
controller.quorum.bootstrap.servers=127.0.0.1:9093
listeners=PLAINTEXT://127.0.0.1:9092,CONTROLLER://127.0.0.1:9093
advertised.listeners=PLAINTEXT://127.0.0.1:9092
inter.broker.listener.name=PLAINTEXT
controller.listener.names=CONTROLLER
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
log.dirs=$($data.Replace('\','/'))
num.partitions=1
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
share.coordinator.state.topic.replication.factor=1
share.coordinator.state.topic.min.isr=1
group.initial.rebalance.delay.ms=0
"@
    [IO.File]::WriteAllText($config, $properties, [Text.UTF8Encoding]::new($false))
    if (-not (Test-Path -LiteralPath (Join-Path $data 'meta.properties'))) {
        $clusterId = & $java '-cp' "$KafkaHome/libs/*" 'kafka.tools.StorageTool' 'random-uuid'
        if ($LASTEXITCODE -ne 0) { throw 'Kafka cluster ID generation failed' }
        & $java '-cp' "$KafkaHome/libs/*" 'kafka.tools.StorageTool' 'format' '--standalone' '-t' $clusterId '-c' $config
        if ($LASTEXITCODE -ne 0) { throw 'Kafka new workspace initialization failed' }
    }
    $logConfig = ([uri][IO.Path]::GetFullPath((Join-Path $KafkaHome 'config/log4j2.yaml'))).AbsoluteUri
    Start-Background 'kafka' $java @('-Xms512m','-Xmx1g',"-Djava.io.tmpdir=$logRoot/tmp","-Dkafka.logs.dir=$logRoot/kafka-logs","-Dlog4j2.configurationFile=$logConfig",'-cp',"$KafkaHome/libs/*",'kafka.Kafka',$config) $projectRoot
} else { Write-Output 'Kafka already listening on 9092' }
if (-not (Listening 8000)) {
    $chroma = Join-Path (Split-Path -Parent $PythonPath) 'Scripts/chroma.exe'
    Start-Background 'chroma' $chroma @('run','--host','127.0.0.1','--port','8000','--path',(Join-Path $logRoot 'chroma')) $projectRoot
} else { Write-Output 'Chroma already listening on 8000' }
if (-not (Listening 8081)) {
    $env:PYTHONIOENCODING = 'utf-8'
    $env:ANONYMIZED_TELEMETRY = 'false'
    Start-Background 'mem0' $PythonPath @('-m','uvicorn','main:app','--host','127.0.0.1','--port','8081') (Join-Path $projectRoot 'memory_service')
} else { Write-Output 'Mem0 already listening on 8081' }
foreach ($port in @(3306,6379,9092,8000,8081)) {
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while (-not (Listening $port) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 500 }
    if (-not (Listening $port)) { throw "Service on port $port did not start. Inspect logs in $logRoot." }
    Write-Output "Local port $port ready"
}
& $PythonPath (Join-Path $PSScriptRoot 'ensure-local-kafka-topics.py')
if ($LASTEXITCODE -ne 0) { throw 'Local Kafka topic initialization failed' }
if ($StartBackend -and -not (Listening 8080)) {
    $jar = Join-Path $projectRoot 'doorhandle-server/target/doorhandle-server-0.0.1-SNAPSHOT.jar'
    if (-not (Test-Path -LiteralPath $jar)) { throw 'Build the server Jar before starting the backend.' }
    Start-Background 'backend' (Join-Path $JavaHome 'bin/java.exe') @("-Djava.io.tmpdir=$logRoot/tmp",'-jar',$jar) $projectRoot
}
Write-Output "Logs and process IDs: $logRoot"
