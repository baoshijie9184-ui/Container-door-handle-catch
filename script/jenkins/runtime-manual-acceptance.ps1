# Dot-sourced by the existing pipeline after its credential/host admission.
# The tunnel is only a bounded SSH client; no local application is started.
function Get-ManualBinding {
    $request=Get-Content -LiteralPath artifacts/runtime-execution-request.json -Raw | ConvertFrom-Json
    $package=Get-Content -LiteralPath artifacts/release.json -Raw | ConvertFrom-Json
    if ($request.release -cne $tag -or $request.commit -cne $package.commit -or $request.sourceSha256 -cne $package.sourceSha256 -or
        $request.runtime -cne $runtime -or $request.settings -cnotmatch '^/(home|srv|opt)/[A-Za-z0-9_./-]+\.json$' -or
        $request.settings -cmatch '(^|/)\.\.(/|$)' -or $request.helperSha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $request.candidateBuildSha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $request.instanceId -cne $env:DOORHANDLE_ECS_INSTANCE_ID -or $request.machineId -cne $env:DOORHANDLE_ECS_MACHINE_ID -or
        $request.manualAcceptanceSeconds -ne ([int]$env:MANUAL_ACCEPTANCE_MINUTES*60)) { throw 'Manual handoff is not bound to this candidate.' }
    return $request
}
function Get-ManualCommand($Request,[string]$Phase) {
    if ($Phase -cnotin @('manual-status','manual-decision')) { throw 'Unsupported manual protocol phase.' }
    $helper="$remoteRoot/releases/$tag/script/docker/compact-runtime-acceptance.py"
    $binding="--root '$remoteRoot' --runtime '$runtime' --tag '$tag' --commit '$($Request.commit)' --source-sha256 '$($Request.sourceSha256)' --instance-id '$($Request.instanceId)' --machine-id '$($Request.machineId)' --settings '$($Request.settings)'"
    return "test `"`$(sha256sum '$helper' | cut -d ' ' -f 1)`" = '$($Request.helperSha256)' && python3 -B '$helper' $Phase $binding"
}
function Get-ManualPrivateDirectory {
    $root=Require-Value 'DOORHANDLE_MANUAL_ACCEPTANCE_PRIVATE_ROOT' '^[A-Za-z]:[\\/][^\r\n]+$'
    $root=[IO.Path]::GetFullPath($root)
    $directory=[IO.Path]::GetFullPath((Join-Path $root $tag))
    if (-not $directory.StartsWith($root.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Private handoff path escaped its configured root.' }
    return $directory
}
function Stop-ManualTunnel {
    $directory=Get-ManualPrivateDirectory
    $journal=Join-Path $directory 'tunnel.json'
    if (-not (Test-Path -LiteralPath $directory)) { return }
    if (Test-Path -LiteralPath $journal) {
        $owned=Get-Content -LiteralPath $journal -Raw | ConvertFrom-Json
        if ($owned.release -cne $tag -or $owned.pid -le 0 -or $owned.processPath -notlike '*ssh.exe') { throw 'Foreign local tunnel journal.' }
        $process=Get-Process -Id $owned.pid -ErrorAction SilentlyContinue
        if ($process) {
            if ($process.StartTime.ToUniversalTime().Ticks -ne $owned.startTicks -or $process.Path -cne $owned.processPath) { throw 'Tunnel process identity was reused; do not stop it.' }
            $process.Kill(); $process.WaitForExit(10000) | Out-Null
            if (-not $process.HasExited) { throw 'Owned tunnel did not stop.' }
        }
    }
    foreach ($name in @('accounts.json','access.md')) {
        $path=Join-Path $directory $name
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    }
    "Manual candidate access ended. Release: $tag. The original runtime owns application cleanup." |
        Set-Content -LiteralPath (Join-Path $directory 'CLOSED.txt') -Encoding utf8
}
function Await-ManualRuntime {
    while (-not (Test-Path -LiteralPath artifacts/runtime-execution-request.json)) {
        if (Test-Path -LiteralPath artifacts/runtime-owner-finished.json) { throw 'Runtime finished before a manual handoff.' }
        Start-Sleep -Seconds 2
    }
    $request=Get-ManualBinding
    while ($true) {
        if (Test-Path -LiteralPath artifacts/runtime-owner-finished.json) { throw 'Runtime ended before manual acceptance.' }
        $lines=Invoke-Checked 'ssh.exe' ($sshOptions + @('-p',$portText,$destination,(Get-ManualCommand $request 'manual-status')))
        $ready=($lines | Select-Object -Last 1) | ConvertFrom-Json
        foreach ($key in @('release','commit','sourceSha256','candidateBuildSha256')) {
            if ($ready.$key -cne $request.$key) { throw 'Manual status belongs to another candidate.' }
        }
        if ($ready.terminal -eq $true) { throw 'Runtime terminated without a manual acceptance window.' }
        if ($ready.status -ceq 'READY_FOR_MANUAL_ACCEPTANCE') { break }
        if ($ready.status -cnotin @('STARTING','RUNNING')) { throw 'Unexpected manual status.' }
        Start-Sleep -Seconds 5
    }
    $expectedFile="$remoteRoot/verification/$tag/checkout/work/runtime-acceptance/manual-access.json"
    $remaining=[int][Math]::Floor([double]$ready.expiresAtUnix-[DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
    if ($ready.executionId -cnotmatch '^[a-f0-9]{32}$' -or $ready.targetSchema -cnotmatch '^doorhandle_compact_candidate_[a-f0-9]{10}$' -or
        $ready.targetTableCount -ne 29 -or $ready.port -lt 1024 -or $ready.port -gt 65535 -or
        $ready.credentialsFile -cne $expectedFile -or $remaining -le 0 -or $remaining -gt $request.manualAcceptanceSeconds -or
        $ready.productionPromotionAllowed -ne $false -or $ready.finalCleanupRequired -ne $true -or $ready.automaticBrowserChecks -ne 21) {
        throw 'Manual entry is not the bounded tested 29-table candidate.'
    }
    $directory=Get-ManualPrivateDirectory
    if (Test-Path -LiteralPath $directory) { throw 'Private manual handoff already exists; do not reopen its window.' }
    $ancestor=Split-Path -Parent $directory
    while ($ancestor) {
        if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Private handoff path contains a reparse point.' }
        $ancestor=Split-Path -Parent $ancestor
    }
    New-Item -ItemType Directory -Path $directory | Out-Null
    $acl=[Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true,$false)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    Set-Acl -LiteralPath $directory -AclObject $acl
    # Allows a failed private delivery to reject this exact window, without
    # publishing a usable READY entry before the tunnel and account guide exist.
    $ready | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $directory 'handoff.json') -Encoding utf8
    $accountsFile=Join-Path $directory 'accounts.json'
    Invoke-Checked 'scp.exe' ($sshOptions + @('-P',$portText,"${destination}:$expectedFile",$accountsFile)) | Out-Null
    $access=Get-Content -LiteralPath $accountsFile -Raw | ConvertFrom-Json
    if ($access.release -cne $tag -or $access.commit -cne $request.commit -or $access.executionId -cne $ready.executionId -or
        $access.expiresAtUnix -ne $ready.expiresAtUnix -or (@($access.accounts.PSObject.Properties.Name | Sort-Object) -join ',') -cne 'inspector,peer,reviewer,supervisor') {
        throw 'Private account delivery does not match the waiting candidate.'
    }
    $listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0); $listener.Start()
    $localPort=$listener.LocalEndpoint.Port; $listener.Stop()
    $info=[Diagnostics.ProcessStartInfo]::new('ssh.exe')
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.Environment['JENKINS_NODE_COOKIE']='manual-tunnel-'+$tag
    # The remote sleep ends the tunnel even if Jenkins disconnects permanently.
    foreach ($argument in ($sshOptions + @('-T','-o','ExitOnForwardFailure=yes','-L',"127.0.0.1:${localPort}:127.0.0.1:$($ready.port)",'-p',$portText,$destination,"sleep $remaining"))) {
        $info.ArgumentList.Add([string]$argument)
    }
    $process=[Diagnostics.Process]::Start($info)
    @{release=$tag;pid=$process.Id;startTicks=$process.StartTime.ToUniversalTime().Ticks;processPath=$process.MainModule.FileName} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $directory 'tunnel.json') -Encoding utf8
    try {
        $connected=$false
        for ($attempt=0;$attempt -lt 30;$attempt++) {
            if ($process.HasExited) { throw 'Private candidate SSH tunnel exited before entry was available.' }
            $probe=[Net.Sockets.TcpClient]::new()
            try { $probe.Connect('127.0.0.1',$localPort); $connected=$true } catch {} finally { $probe.Dispose() }
            if ($connected) { break }; Start-Sleep -Seconds 1
        }
        if (-not $connected) { throw 'Private candidate tunnel is unavailable.' }
        $url="http://127.0.0.1:$localPort/"
        $guide=@("# 本轮 29 表候选人工验收", "", "入口：$url", "提交：$($ready.commit)",
            "候选库：$($ready.targetSchema)（不是原 131 表生产站点）", "截止 UTC：$([DateTimeOffset]::FromUnixTimeSeconds([long]$ready.expiresAtUnix).ToString('u'))", "",
            '账号仅用于本轮隔离候选；模型为受控本地脚本，不调用付费外部模型。', '', '| 角色 | 用户名 | 密码 |', '|---|---|---|')
        foreach ($alias in @('supervisor','reviewer','inspector','peer')) {
            $account=$access.accounts.$alias
            if ($account.username -cnotmatch '^cf_[a-f0-9]+_(supervisor|reviewer|inspector|peer)$' -or $account.password -cnotmatch '^[A-Za-z0-9_-]{1,128}$') { throw 'Invalid private test account format.' }
            $guide += "| $alias | $($account.username) | $($account.password) |"
        }
        $guide += @('', '可检查人员资料/入职日期、设备及历史领用、报告与修改记录。验收完成后在 Jenkins 当前 input 选择“验收通过”；发现问题选择“发现问题”，或在聊天中告知负责助手代为处理同一 input。不要操作生产站点。',
            '窗口到期自动收尾；仅停止本轮候选临时资源，不关闭 ECS 或原业务服务。入口在窗口结束后失效，最终成功仍要求候选及依赖已停止。')
        $guidePath=Join-Path $directory 'access.md'
        $guide -join "`r`n" | Set-Content -LiteralPath $guidePath -Encoding utf8
        $public=@{}; foreach ($property in $ready.PSObject.Properties) { $public[$property.Name]=$property.Value }
        $public.localUrl=$url; $public.privateGuide=$guidePath
        $public | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath artifacts/manual-acceptance-ready.json -Encoding utf8
        Write-Host "29-table candidate ready: $url; private guide: $guidePath; ends at $($ready.expiresAtUnix)."
    } catch { Stop-ManualTunnel; throw }
}
function Complete-ManualRuntime {
    try {
        $delivered=Test-Path -LiteralPath artifacts/manual-acceptance-ready.json
        $readyFile=if ($delivered) {'artifacts/manual-acceptance-ready.json'} else {Join-Path (Get-ManualPrivateDirectory) 'handoff.json'}
        if (-not (Test-Path -LiteralPath $readyFile)) { return }
        $request=Get-ManualBinding
        $ready=Get-Content -LiteralPath $readyFile -Raw | ConvertFrom-Json
        foreach ($key in @('release','commit','sourceSha256','candidateBuildSha256')) {
            if ($ready.$key -cne $request.$key) { throw 'Manual completion belongs to another candidate.' }
        }
        $decision=if ($delivered) {Require-Value 'MANUAL_ACCEPTANCE_DECISION' '^(ACCEPTED|REJECTED)$'} else {'REJECTED'}
        $actor=[string]$env:MANUAL_ACCEPTANCE_SUBMITTER
        if (-not $actor) { $actor='jenkins-cancelled-or-expired' }
        if ($actor.Length -gt 160 -or $actor -match '[\x00-\x1f\x7f]') { throw 'Invalid manual submitter.' }
        $payload=@{decision=$decision;submittedBy=$actor;executionId=$ready.executionId}
        foreach ($key in @('release','commit','sourceSha256','candidateBuildSha256')) { $payload[$key]=$request.$key }
        $lines=($payload | ConvertTo-Json -Compress) | & ssh.exe @sshOptions -p $portText $destination (Get-ManualCommand $request 'manual-decision')
        if ($LASTEXITCODE -ne 0) { throw 'Manual decision was not acknowledged; original deadline and cleanup remain authoritative.' }
        $ack=($lines | Select-Object -Last 1) | ConvertFrom-Json
        if ($ack.status -cne 'DECISION_RECORDED' -or $ack.executionId -cne $ready.executionId -or $ack.decision -cne $decision) { throw 'Manual decision acknowledgement differs.' }
    } finally { Stop-ManualTunnel }
}
