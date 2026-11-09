# Dot-sourced only by the explicit nonadministrator migration mode. No client,
# service, credential or filesystem action occurs merely by loading functions.
function Invoke-NonAdminMetadataPolicy([string]$Action, $Record) {
    Require-Export ($Action -cin @('source', 'privileges')) 'Unknown metadata policy action.' 'NONADMIN_POLICY_ACTION_REQUIRED'
    Assert-Unlinked $script:nonAdminPolicy
    Assert-Unlinked $script:nonAdminSourceHelper
    Require-Export ((File-Sha $script:nonAdminSourceHelper) -ceq $script:nonAdminSourceHelperSha) 'The admitted source adapter changed.' 'NONADMIN_SOURCE_HELPER_CHANGED'
    Require-Export ((File-Sha $script:nonAdminPolicy) -ceq $script:nonAdminPolicySha) 'The admitted metadata policy changed.' 'NONADMIN_POLICY_CHANGED'
    Assert-Unlinked $script:policyPython
    Require-Export ((File-Sha $script:policyPython) -ceq $script:policyPythonSha) 'The admitted metadata interpreter changed.' 'NONADMIN_INTERPRETER_CHANGED'
    $body = $Record | ConvertTo-Json -Depth 12 -Compress
    Require-Export ([Text.Encoding]::UTF8.GetByteCount($body) -le 65536) 'Source metadata exceeds its bound.' 'NONADMIN_METADATA_BOUND'
    $start = [Diagnostics.ProcessStartInfo]::new(); $start.FileName = $script:policyPython
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true; $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
    $start.StandardInputEncoding = [Text.UTF8Encoding]::new($false)
    $start.Environment.Clear()
    foreach ($name in @('SystemRoot','WINDIR')) {
        $entry = [Environment]::GetEnvironmentVariable($name)
        if ($entry) { $start.Environment[$name] = $entry }
    }
    foreach ($argument in @('-I', '-S', '-B', $script:nonAdminPolicy, $Action)) { $start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new(); $process.StartInfo = $start; $started = $false
    try {
        Require-Export ($process.Start()) 'Cannot start the existing metadata interpreter.' 'NONADMIN_POLICY_START_FAILED'; $started = $true
        $stdout = $process.StandardOutput.ReadToEndAsync(); $stderr = $process.StandardError.ReadToEndAsync()
        $write = $process.StandardInput.WriteAsync($body)
        Require-Export ($write.Wait(10000)) 'Metadata input transfer timed out.' 'NONADMIN_POLICY_TIMEOUT'
        $write.GetAwaiter().GetResult(); $process.StandardInput.Close()
        Require-Export ($process.WaitForExit(30000)) 'Metadata policy timed out.' 'NONADMIN_POLICY_TIMEOUT'
        $answer = $stdout.GetAwaiter().GetResult(); $diagnostic = $stderr.GetAwaiter().GetResult()
        Require-Export ($process.ExitCode -eq 0 -and $answer.Length -le 16384 -and $diagnostic.Length -eq 0) 'Source metadata policy refused the observation.' 'NONADMIN_METADATA_REFUSED'
        Require-Export ((File-Sha $script:nonAdminPolicy) -ceq $script:nonAdminPolicySha -and
            (File-Sha $script:policyPython) -ceq $script:policyPythonSha) 'Metadata policy inputs changed.' 'NONADMIN_POLICY_CHANGED'
        return $answer | ConvertFrom-Json
    } finally {
        if ($started -and -not $process.HasExited) { $process.Kill($true); [void]$process.WaitForExit(10000) }
        $process.Dispose()
    }
}
function Convert-NonAdminProcess($Process) {
    Require-Export ($null -ne $Process -and $null -ne $Process.CreationDate) 'Required process identity metadata is unavailable.' 'NONADMIN_PROCESS_METADATA_REQUIRED'
    return [ordered]@{ processId = $Process.ProcessId; parentProcessId = $Process.ParentProcessId;
        name = $Process.Name; createdAtUtc = $Process.CreationDate.ToUniversalTime().ToString('o');
        executablePath = $Process.ExecutablePath; commandLine = $Process.CommandLine }
}
function Get-NonAdminReviewedSource {
    # A real service PID and its current owner-bound endpoint are required even
    # when Windows withholds the privileged executable/command-line properties.
    $service = Get-CimInstance Win32_Service -Filter "Name='MySQL83'"
    Require-Export ($null -ne $service -and $service.ProcessId -gt 0) 'The fixed running service is unavailable.' 'NONADMIN_SERVICE_REQUIRED'
    $parent = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $service.ProcessId)
    $endpoints = @(Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection -Filter 'LocalPort=3306' |
        Where-Object { $_.RemotePort -eq 0 })
    $owners = @($endpoints | Select-Object -ExpandProperty OwningProcess -Unique)
    Require-Export ($owners.Count -eq 1) 'One current source endpoint owner is required.' 'NONADMIN_ENDPOINT_OWNER_REQUIRED'
    $worker = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $owners[0])
    $computer = Get-CimInstance Win32_ComputerSystem
    $record = [ordered]@{ service = [ordered]@{ name = $service.Name; state = $service.State;
            processId = $service.ProcessId; pathName = $service.PathName };
        serviceProcess = Convert-NonAdminProcess $parent; worker = Convert-NonAdminProcess $worker;
        hostName = $computer.Name; endpoints = @($endpoints | ForEach-Object {
            $stateProperty = $_.CimInstanceProperties['State']
            Require-Export ($null -ne $stateProperty -and $null -ne $stateProperty.Value) 'A typed raw endpoint state is required.' 'NONADMIN_TCP_STATE_REQUIRED'
            [ordered]@{ localAddress = $_.LocalAddress; localPort = $_.LocalPort;
                remoteAddress = $_.RemoteAddress; remotePort = $_.RemotePort;
                owningProcess = $_.OwningProcess; state = $stateProperty.Value }
        }) }
    return Invoke-NonAdminMetadataPolicy 'source' $record
}
function Initialize-NonAdminCredentialHandleType {
    if ('DoorHandleMigrationExportV1.NativeFile' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;
namespace DoorHandleMigrationExportV1 {
 public static class NativeFile {
  [StructLayout(LayoutKind.Sequential)] public struct Info {
   public uint Attributes;
   public System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
   public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
  }
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle h,out Info i);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint GetFinalPathNameByHandle(SafeFileHandle h,StringBuilder s,uint n,uint f);
  [DllImport("advapi32.dll", SetLastError=true)] static extern uint GetSecurityInfo(SafeFileHandle h,uint t,uint s,out IntPtr o,out IntPtr g,out IntPtr d,out IntPtr a,out IntPtr descriptor);
  [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr p);
  public static string[] Observe(SafeFileHandle h) {
   Info i; if(!GetFileInformationByHandle(h,out i)) throw new IOException("CREDENTIAL_HANDLE_METADATA_UNAVAILABLE");
   StringBuilder path=new StringBuilder(32768); uint n=GetFinalPathNameByHandle(h,path,32768,0);
   if(n==0||n>=32768) throw new IOException("CREDENTIAL_FINAL_PATH_UNAVAILABLE");
   IntPtr owner,group,dacl,sacl,descriptor;
   if(GetSecurityInfo(h,1,1,out owner,out group,out dacl,out sacl,out descriptor)!=0) throw new IOException("CREDENTIAL_OWNER_UNAVAILABLE");
   try { return new string[]{path.ToString(),new SecurityIdentifier(owner).Value,
     i.Attributes.ToString(),i.Volume.ToString(),i.SizeHigh.ToString(),i.SizeLow.ToString(),i.Links.ToString(),
     i.IndexHigh.ToString(),i.IndexLow.ToString(),i.Creation.dwHighDateTime.ToString(),i.Creation.dwLowDateTime.ToString(),
     i.Write.dwHighDateTime.ToString(),i.Write.dwLowDateTime.ToString()}; }
   finally { if(descriptor!=IntPtr.Zero) LocalFree(descriptor); }
  }
 }
}
'@ | Out-Null
}
function Assert-NonAdminCredentialHandle {
    $path = 'D:\AI\lunwen1\DoorHandleCatch\work\model-mysql.private.json'
    Assert-Unlinked $path
    $state = [DoorHandleMigrationExportV1.NativeFile]::Observe($script:credentialStream.SafeFileHandle)
    $final = $state[0]; if ($final.StartsWith('\\?\')) { $final = $final.Substring(4) }
    Require-Export ($final -ieq $path -and $state[1] -ceq $script:owner.Value -and
        ([uint32]$state[2] -band 0x410) -eq 0 -and $state[4] -ceq '0' -and $state[5] -ceq '234' -and
        $state[6] -ceq '1' -and ($state[7] -ne '0' -or $state[8] -ne '0')) 'The fixed credential file owner, identity or links differ.' 'NONADMIN_CREDENTIAL_IDENTITY_REQUIRED'
    if ($null -ne $script:credentialObservation) {
        Require-Export (($state | ConvertTo-Json -Compress) -ceq ($script:credentialObservation | ConvertTo-Json -Compress)) 'The held credential file changed.' 'NONADMIN_CREDENTIAL_CHANGED'
    }
    return ,$state
}
function Read-NonAdminProjectCredentials {
    Initialize-NonAdminCredentialHandleType
    $path = 'D:\AI\lunwen1\DoorHandleCatch\work\model-mysql.private.json'; Assert-Unlinked $path
    $script:credentialStream = [IO.File]::Open($path, 'Open', 'Read', 'Read')
    $script:credentialObservation = Assert-NonAdminCredentialHandle
    $raw = [byte[]]::new(234); $read = 0
    while ($read -lt $raw.Length) {
        $n = $script:credentialStream.Read($raw, $read, $raw.Length - $read)
        Require-Export ($n -gt 0) 'The fixed credential file is incomplete.' 'NONADMIN_CREDENTIAL_BYTES_REQUIRED'; $read += $n
    }
    Require-Export ($script:credentialStream.ReadByte() -eq -1) 'The credential file exceeds its fixed size.' 'NONADMIN_CREDENTIAL_BYTES_REQUIRED'
    $hash = [Security.Cryptography.SHA256]::Create()
    try { $actual = [BitConverter]::ToString($hash.ComputeHash($raw)).Replace('-', '').ToLowerInvariant() } finally { $hash.Dispose() }
    Require-Export ($actual -ceq '97c366105bd23057d4733636b05766eb36e03da1a07af6e8b37dd0c4c90e6b2b') 'The reviewed project credential bytes changed.' 'NONADMIN_CREDENTIAL_SHA_REQUIRED'
    $value = [Text.UTF8Encoding]::new($false, $true).GetString($raw) | ConvertFrom-Json -AsHashtable
    Require-Export ((($value.Keys | Sort-Object) -join ',') -ceq 'database,password,url,username') 'Only the fixed credential shape is accepted.' 'NONADMIN_CREDENTIAL_SHAPE_REQUIRED'
    Require-Export (@($value.Values | Where-Object { $_ -isnot [string] }).Count -eq 0 -and
        $value.username -cmatch '^[A-Za-z0-9_]{1,32}$' -and $value.password.Length -gt 0 -and $value.password.Length -le 4096 -and
        $value.database -ceq 'doorhandle_model_verify_22e4bc5566' -and $value.url.StartsWith('jdbc:mysql://') -and
        $value.username -notmatch '[\x00\r\n]' -and $value.password -notmatch '[\x00\r\n]') 'The fixed credential fields are invalid.' 'NONADMIN_CREDENTIAL_SHAPE_REQUIRED'
    $uri = [Uri]::new($value.url.Substring(5))
    Require-Export ($uri.Host -cin @('localhost', '127.0.0.1') -and $uri.Port -eq 3306 -and
        $uri.UserInfo.Length -eq 0 -and $uri.AbsolutePath.Trim('/') -ceq $value.database) 'Credential endpoint differs from the reviewed local server.' 'NONADMIN_CREDENTIAL_ENDPOINT_REQUIRED'
    [void](Assert-NonAdminCredentialHandle)
    $script:expectedCredentialUser = $value.username
    return @{ DB_USERNAME = $value.username; DB_PASSWORD = $value.password }
}
function Get-NonAdminPrivilegeObservation([string]$Prefix) {
    $file = Join-Path $script:output "$Prefix-grants-private.txt"
    Invoke-PrivateClient $script:mysql ($script:mysqlArgs + @('--batch','--raw','--silent','--skip-column-names',
        '--skip-auto-rehash','--init-command=SET SESSION TRANSACTION READ ONLY', ('--database=' + $script:SourceSchema))) $file 'SHOW GRANTS FOR CURRENT_USER;' | Out-Null
    $grants = @()
    foreach ($line in [IO.File]::ReadAllLines($file)) {
        if (-not $line) { continue }
        # Parse only privileges/scope; account identities and grant text never
        # enter the metadata validator, arguments, diagnostics or public output.
        if ($line -match '^GRANT ([A-Z_ ,]+) ON (\*\.\*|`[A-Za-z0-9_]+`\.\*) TO ') {
            $scope = $Matches[2].Replace('`', '')
            if ($scope -ceq '*.*' -or $scope -ceq ($script:SourceSchema + '.*')) {
                $grants += [ordered]@{ scope = $scope; privileges = @($Matches[1].Split(',') | ForEach-Object { $_.Trim() }) }
            }
        }
    }
    $proved = Invoke-NonAdminMetadataPolicy 'privileges' ([ordered]@{ schema = $script:SourceSchema; grants = $grants })
    Write-PrivateJson (Join-Path $script:output "$Prefix-privileges-private.json") $proved
    return $proved
}
