<#
Compile the trusted Jenkinsfile with the installed local Jenkins CPS compiler.
This does not call Script.run, start/queue a build, change a job or enable any
global script-splitting option. Declarative syntax validation alone does not
perform the bytecode-generation check which detects MethodTooLargeException.
#>
param(
    [Parameter(Mandatory=$true)][string]$PipelineFile,
    [Parameter(Mandatory=$true)][string]$EvidenceFile,
    [string]$Commit=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$project='D:/AI/lunwen1/DoorHandleCatch'
$source=(Resolve-Path -LiteralPath $PipelineFile).Path
$target=[IO.Path]::GetFullPath($EvidenceFile)
if(-not $source.StartsWith($project.Replace('/','\')+'\',[StringComparison]::OrdinalIgnoreCase) -or
    -not $target.StartsWith(($project+'/work/jenkins/').Replace('/','\'),[StringComparison]::OrdinalIgnoreCase) -or
    (Test-Path -LiteralPath $target) -or -not (Test-Path -LiteralPath (Split-Path -Parent $target) -PathType Container)) {
    throw 'Use an existing trusted project source and a fresh D-project Jenkins metadata evidence destination.'
}
foreach($path in @($source,(Split-Path -Parent $target))) {
    $item=Get-Item -LiteralPath $path -Force
    while($null -ne $item) {
        if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Compile inputs/evidence cannot use links or junctions.'}
        $item=if($item -is [IO.FileInfo]){$item.Directory}else{$item.Parent}
    }
}
$sourceKind='WORKTREE_BYTES'
if($Commit) {
    if($Commit -cnotmatch '^[a-f0-9]{40}$'){throw 'A complete fixed Git commit is required for SCM byte compilation.'}
    $resolved=& git.exe -C $project rev-parse --verify "$Commit^{commit}"
    if($LASTEXITCODE -ne 0 -or $resolved -cne $Commit){throw 'The fixed source is not the exact local Git commit.'}
    $start=[Diagnostics.ProcessStartInfo]::new();$start.FileName=(Get-Command git.exe -CommandType Application | Select-Object -First 1).Source
    $start.UseShellExecute=$false;$start.CreateNoWindow=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
    foreach($argument in @('-C',$project,'cat-file','blob',($Commit+':Jenkinsfile.ecs-monolith'))){$start.ArgumentList.Add($argument)}
    $process=[Diagnostics.Process]::new();$process.StartInfo=$start;$bytes=[IO.MemoryStream]::new();$started=$false
    try {
        if(-not $process.Start()){throw 'Cannot read the exact SCM Jenkinsfile blob.'}
        $started=$true
        $errors=$process.StandardError.ReadToEndAsync();$buffer=[byte[]]::new(65536)
        while(($count=$process.StandardOutput.BaseStream.Read($buffer,0,$buffer.Length)) -gt 0) {
            if($bytes.Length+$count -gt 1MB){throw 'The SCM Jenkinsfile exceeds its compile bound.'}
            $bytes.Write($buffer,0,$count)
        }
        $process.WaitForExit();$null=$errors.GetAwaiter().GetResult()
        if($process.ExitCode -ne 0){throw 'The fixed SCM Jenkinsfile blob is unavailable.'}
        $raw=$bytes.ToArray();$sourceKind='GIT_BLOB'
    } finally {if($started -and -not $process.HasExited){$process.Kill()};$process.Dispose();$bytes.Dispose()}
} else {$raw=[IO.File]::ReadAllBytes($source)}
if($raw.Length -le 0 -or $raw.Length -gt 1MB){throw 'Use the bounded existing Jenkinsfile.'}
$encodedSource=[Convert]::ToBase64String($raw)
$sourceSha=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($raw)).ToLowerInvariant()
$recipe=@'
import jenkins.model.Jenkins
import groovy.json.JsonOutput
import groovy.lang.GroovyCodeSource
def j=Jenkins.get()
def job=j.getItemByFullName('doorhandle-java')
assert job != null
def state={ [lastBuild:job.lastBuild?.number,building:job.lastBuild?.isBuilding(),queued:job.isInQueue()] }
def before=state()
assert !before.building && !before.queued
byte[] raw='__SOURCE_BASE64__'.decodeBase64()
def digest=java.security.MessageDigest.getInstance('SHA-256').digest(raw).encodeHex().toString()
assert digest=='__SOURCE_SHA__'
def loader=j.pluginManager.uberClassLoader
def transformer=loader.loadClass('org.jenkinsci.plugins.pipeline.modeldefinition.parser.RuntimeASTTransformer')
def splitting=transformer.getDeclaredField('SCRIPT_SPLITTING_TRANSFORMATION'); splitting.accessible=true
def splittingBefore=splitting.get(null)
def factoryType=loader.loadClass('org.jenkinsci.plugins.workflow.cps.CpsGroovyShellFactory')
def constructor=factoryType.declaredConstructors.find{it.parameterTypes.size()==1}
assert constructor != null
constructor.accessible=true
def factory=constructor.newInstance([null] as Object[])
def sandbox=factoryType.getDeclaredMethod('withSandbox',Boolean.TYPE); sandbox.accessible=true
sandbox.invoke(factory,true)
def build=factoryType.getDeclaredMethod('build'); build.accessible=true
def shell=build.invoke(factory)
def report=[kind:'doorhandle-local-jenkins-cps-compilation',sourceSha256:digest,sourceBytes:raw.length,
  sourceKind:'__SOURCE_KIND__',commit:'__COMMIT__',sourcePath:'Jenkinsfile.ecs-monolith',
  workflowCps:j.pluginManager.getPlugin('workflow-cps')?.version,
  declarative:j.pluginManager.getPlugin('pipeline-model-definition')?.version,
  sandbox:true,factoryExecutionWasNull:true,scriptInstantiated:false,scriptRunInvoked:false,buildTriggered:false,
  compilerApi:'CpsGroovyShellFactory(null).withSandbox(true).build().classLoader.parseClass',
  globalConfigurationChanged:false,scriptSplittingBefore:splittingBefore,before:before]
try {
  def parsed=shell.classLoader.parseClass(new GroovyCodeSource(new String(raw,'UTF-8'),'WorkflowScript','/groovy/shell'),false)
  report.compiledClass=parsed.name
  report.status='CPS_COMPILATION_PASS'
  report.compileSucceeded=true
} catch(Throwable error) {
  report.status='CPS_COMPILATION_FAILED'
  report.compileSucceeded=false
  report.errorType=error.class.name
  report.errorStack=error.stackTrace.take(10).collect{[type:it.className,method:it.methodName,line:it.lineNumber]}
  def failure=error.message ?: ''
  def match=failure =~ /Method too large: ([A-Za-z0-9_.$]+)/
  report.methodTooLarge=match.find()
  if(report.methodTooLarge) report.failedMethod=match.group(1)
} finally {
  report.after=state()
  report.scriptSplittingAfter=splitting.get(null)
  assert report.after==before
  assert report.scriptSplittingAfter==splittingBefore
}
println JsonOutput.toJson(report)
'@
$recipe=$recipe.Replace('__SOURCE_BASE64__',$encodedSource).Replace('__SOURCE_SHA__',$sourceSha).Replace('__SOURCE_KIND__',$sourceKind).Replace('__COMMIT__',$Commit)
$account=$null;$password=$null
foreach($line in Get-Content -LiteralPath ($project+'/work/jenkins/local-access.md') -Encoding utf8) {
    if(-not $line.StartsWith('|')){continue};$parts=$line.Split('|');if($parts.Count -lt 4){continue}
    $label=$parts[1].Trim();$value=$parts[2].Trim().Trim('`')
    if($label -in @('用户名','账号','Username')){$account=$value}
    if($label -in @('密码','Password')){$password=$value}
}
if(-not $account -or -not $password){throw 'Existing local Jenkins login fields are unavailable.'}
$handler=[Net.Http.HttpClientHandler]::new();$handler.UseProxy=$false;$handler.UseCookies=$true
$handler.Credentials=[Net.NetworkCredential]::new($account,$password)
$client=[Net.Http.HttpClient]::new($handler);$client.BaseAddress=[Uri]'http://127.0.0.1:8080/'
$client.Timeout=[TimeSpan]::FromSeconds(45)
$client.DefaultRequestHeaders.Authorization=[Net.Http.Headers.AuthenticationHeaderValue]::new('Basic',[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($account+':'+$password)))
try {
    $who=$client.GetStringAsync('whoAmI/api/json').GetAwaiter().GetResult()|ConvertFrom-Json
    if(-not $who.authenticated -or $who.name -cne $account){throw 'The existing Jenkins administrator was not authenticated.'}
    $crumb=$client.GetStringAsync('crumbIssuer/api/json').GetAwaiter().GetResult()|ConvertFrom-Json
    $client.DefaultRequestHeaders.Add([string]$crumb.crumbRequestField,[string]$crumb.crumb)
    $form=[Collections.Generic.Dictionary[string,string]]::new();$form.Add('script',$recipe)
    $content=[Net.Http.FormUrlEncodedContent]::new($form)
    try {
        $response=$client.PostAsync('scriptText',$content).GetAwaiter().GetResult()
        if(-not $response.IsSuccessStatusCode){throw ('Compile-only Jenkins API failed with HTTP '+[int]$response.StatusCode)}
        $report=$response.Content.ReadAsStringAsync().GetAwaiter().GetResult()|ConvertFrom-Json
    } finally {$content.Dispose()}
    if($report.sourceSha256 -cne $sourceSha -or $report.scriptRunInvoked -ne $false -or $report.buildTriggered -ne $false -or
        $report.globalConfigurationChanged -ne $false -or $report.sourceKind -cne $sourceKind -or $report.commit -cne $Commit -or
        (-not $Commit -and (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -cne $sourceSha)) {
        throw 'The nonexecuting compilation evidence or source identity differs.'
    }
    $report|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $target -Encoding utf8
    $report|ConvertTo-Json -Depth 8 -Compress
} finally {$client.Dispose();$handler.Dispose()}
