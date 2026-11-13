param([string]$WorkerRequest = '')
$script:DetachedJenkinsJavaHelperPath = $PSCommandPath

# WMI owns this hidden launcher, not the short-lived interactive tool process.
# https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/create-method-in-class-win32-process
# https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-processstartup
function Write-DetachedJavaState([string]$Path, $Value) {
    $temporary = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
    [IO.File]::Move($temporary, $Path)
}

function Start-DetachedJenkinsJava {
    param(
        [Parameter(Mandatory=$true)][string]$JavaExe,
        [Parameter(Mandatory=$true)][string]$Arguments,
        [Parameter(Mandatory=$true)][string]$WorkingDirectory,
        [Parameter(Mandatory=$true)][string]$StandardOutput,
        [Parameter(Mandatory=$true)][string]$StandardError,
        [Parameter(Mandatory=$true)][string]$PidFile,
        [hashtable]$EnvironmentOverrides = @{}
    )
    $ErrorActionPreference = 'Stop'
    $launcher = (Get-Process -Id $PID).Path
    $helper = $script:DetachedJenkinsJavaHelperPath
    foreach ($path in @($launcher, $helper, $JavaExe, $WorkingDirectory, $PidFile, $StandardOutput, $StandardError)) {
        if (-not [IO.Path]::IsPathFullyQualified($path) -or $path.Contains('"') -or $path -match '[\r\n]') {
            throw 'Detached Java startup requires absolute paths without quotes or line breaks.'
        }
    }
    $launchLock = [IO.File]::Open(($PidFile + '.launch.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    try {
        if (Test-Path -LiteralPath $PidFile -PathType Leaf) {
            $recordedId = 0
            if ([int]::TryParse((Get-Content -LiteralPath $PidFile -Raw).Trim(), [ref]$recordedId)) {
                $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedId"
                if ($existing -and $existing.ExecutablePath -eq $JavaExe -and $existing.CommandLine.EndsWith($Arguments, [StringComparison]::Ordinal)) {
                    return [pscustomobject]@{ Id=$recordedId; LauncherId=[int]$existing.ParentProcessId; Receipt=''; Existing=$true }
                }
            }
        }
        # A still-live owner also blocks a retry after an unknown startup result.
        $check = [IO.File]::Open(($PidFile + '.lifetime.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
        $check.Dispose()
        $directory = $PidFile + '.starts/' + [guid]::NewGuid().ToString('N')
        [void][IO.Directory]::CreateDirectory($directory)
        $requestPath = Join-Path $directory 'request.json'
        $request = @{ javaExe=$JavaExe; arguments=$Arguments; workingDirectory=$WorkingDirectory;
            stdout=$StandardOutput; stderr=$StandardError; pidFile=$PidFile }
        Write-DetachedJavaState $requestPath $request
        $environment = [Environment]::GetEnvironmentVariables()
        foreach ($entry in $EnvironmentOverrides.GetEnumerator()) { $environment[$entry.Key] = [string]$entry.Value }
        # Keep values in memory only; the launch record never contains environment values.
        $variables = [string[]]@($environment.GetEnumerator() | ForEach-Object { $_.Key + '=' + $_.Value })
        $startup = New-CimInstance -Namespace root/cimv2 -ClassName Win32_ProcessStartup -ClientOnly -Property @{
            ShowWindow=[uint16]0; CreateFlags=[uint32](16777216 -bor 1024); EnvironmentVariables=$variables
        }
        $command = '"{0}" -NoLogo -NoProfile -NonInteractive -File "{1}" -WorkerRequest "{2}"' -f $launcher, $helper, $requestPath
        $created = Invoke-CimMethod -Namespace root/cimv2 -ClassName Win32_Process -MethodName Create -Arguments @{
            CommandLine=$command; CurrentDirectory=$WorkingDirectory; ProcessStartupInformation=$startup
        }
        if ($created.ReturnValue -ne 0) { throw "Detached Java creation failed with WMI return value $($created.ReturnValue); no fallback launch was attempted." }
        $receiptPath = Join-Path $directory 'startup.json'
        $failurePath = Join-Path $directory 'launcher-failure.json'
        $deadline = [DateTime]::UtcNow.AddSeconds(20)
        while ([DateTime]::UtcNow -lt $deadline) {
            if (Test-Path -LiteralPath $failurePath -PathType Leaf) {
                throw "Detached Java launcher failed; inspect $failurePath before retrying."
            }
            if (Test-Path -LiteralPath $receiptPath -PathType Leaf) {
                $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
                if ($receipt.status -ne 'STARTED' -or $receipt.launcherPid -ne $created.ProcessId) {
                    throw 'Detached Java did not publish a matching successful startup; inspect its original record before retrying.'
                }
                $actual = Get-CimInstance Win32_Process -Filter "ProcessId=$($receipt.javaPid)"
                if (-not $actual -or $actual.ExecutablePath -ne $JavaExe -or $actual.ParentProcessId -ne $created.ProcessId) {
                    throw 'Detached Java exited or its process identity differs; inspect its original logs and exit record.'
                }
                return [pscustomobject]@{ Id=[int]$receipt.javaPid; LauncherId=[int]$created.ProcessId; Receipt=$receiptPath }
            }
            Start-Sleep -Milliseconds 200
        }
        throw "Detached Java startup outcome is unknown; inspect $directory before retrying."
    } finally { $launchLock.Dispose() }
}

if ($WorkerRequest) {
    $ErrorActionPreference = 'Stop'
    $request = Get-Content -LiteralPath $WorkerRequest -Raw | ConvertFrom-Json
    $directory = Split-Path -Parent $WorkerRequest
    $owner = $null; $stdout = $null; $stderr = $null; $process = $null; $started = $false
    try {
        $owner = [IO.File]::Open(($request.pidFile + '.lifetime.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
        # Append so even an interrupted earlier JVM keeps its original output.
        $stdout = [IO.File]::Open($request.stdout, 'Append', 'Write', 'Read')
        $stderr = [IO.File]::Open($request.stderr, 'Append', 'Write', 'Read')
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = [Diagnostics.ProcessStartInfo]::new($request.javaExe, $request.arguments)
        $process.StartInfo.WorkingDirectory = $request.workingDirectory
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        $process.StartInfo.RedirectStandardOutput = $true
        $process.StartInfo.RedirectStandardError = $true
        $started = $process.Start()
        if (-not $started) { throw 'Java did not start.' }
        $outCopy = $process.StandardOutput.BaseStream.CopyToAsync($stdout)
        $errCopy = $process.StandardError.BaseStream.CopyToAsync($stderr)
        [IO.File]::WriteAllText($request.pidFile, ([string]$process.Id + [Environment]::NewLine), [Text.Encoding]::ASCII)
        Write-DetachedJavaState (Join-Path $directory 'startup.json') @{
            status='STARTED'; javaPid=$process.Id; launcherPid=$PID; startedAtUtc=[DateTime]::UtcNow.ToString('o');
            javaStartTimeUtc=$process.StartTime.ToUniversalTime().ToString('o');
            strategy='WMI_CREATE_BREAKAWAY_HIDDEN'; stdout=$request.stdout; stderr=$request.stderr
        }
        $process.WaitForExit()
        [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($outCopy, $errCopy))
        $stdout.Flush(); $stderr.Flush()
        Write-DetachedJavaState (Join-Path $directory 'exit.json') @{
            status='EXITED'; javaPid=$process.Id; launcherPid=$PID; exitCode=$process.ExitCode;
            exitedAtUtc=[DateTime]::UtcNow.ToString('o')
        }
    } catch {
        Write-DetachedJavaState (Join-Path $directory 'launcher-failure.json') @{
            status='FAILED_OR_UNKNOWN'; javaStarted=$started; launcherPid=$PID; errorType=$_.Exception.GetType().FullName;
            observedAtUtc=[DateTime]::UtcNow.ToString('o')
        }
        # Do not kill or silently relaunch a JVM with an unknown outcome.
        throw
    } finally {
        if ($stdout) { $stdout.Dispose() }; if ($stderr) { $stderr.Dispose() }
        if ($process) { $process.Dispose() }; if ($owner) { $owner.Dispose() }
    }
}
