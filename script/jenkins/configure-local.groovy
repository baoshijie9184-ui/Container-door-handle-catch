// Run as the authenticated administrator through /scriptText. No builds are started here.
import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import hudson.model.BooleanParameterDefinition
import hudson.model.ChoiceParameterDefinition
import hudson.model.Node
import hudson.model.ParametersDefinitionProperty
import hudson.model.StringParameterDefinition
import hudson.slaves.DumbSlave
import hudson.slaves.EnvironmentVariablesNodeProperty
import hudson.slaves.JNLPLauncher
import hudson.slaves.RetentionStrategy
import hudson.triggers.SCMTrigger
import hudson.tasks.LogRotator
import jenkins.model.Jenkins
import jenkins.model.JenkinsLocationConfiguration
import org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition
import org.jenkinsci.plugins.workflow.job.WorkflowJob
import org.jenkinsci.plugins.workflow.job.properties.DisableConcurrentBuildsJobProperty
import org.jenkinsci.plugins.workflow.job.properties.PipelineTriggersJobProperty

def project = new File('D:/AI/lunwen1/DoorHandleCatch').canonicalFile
def settingsFile = new File(project, 'work/jenkins/local-node.json').canonicalFile
def settings = new JsonSlurper().parse(settingsFile)
assert settings.version == 1
assert settings.instanceId == 'i-2zeieuov2aum486jm1ek'
assert settings.machineId ==~ /[a-f0-9]{32}/
assert settings.activate instanceof Boolean
def ci = Jenkins.get()
def job = ci.getItem('doorhandle-java')
assert job instanceof WorkflowJob
assert job.getDefinition() instanceof CpsScmFlowDefinition
assert !job.isBuilding() : 'Wait for the existing project build before reconfiguring.'
def nodeName = 'doorhandle-local-ci'
def agentRoot = new File(project, 'work/jenkins/local-agent').canonicalFile
def workspace = new File(project, 'work/jenkins/ci-workspaces/monolith').canonicalFile
def backup = new File(project, 'work/jenkins/configuration-' + UUID.randomUUID().toString())
assert backup.mkdirs()
new File(backup, 'controller.before.xml').setText(ci.getConfigFile().asString(), 'UTF-8')
new File(backup, 'job.before.xml').setText(job.getConfigFile().asString(), 'UTF-8')
def existingNode = ci.getNode(nodeName)
if (existingNode != null) {
    assert existingNode.getRemoteFS().replace('\\', '/') == agentRoot.path.replace('\\', '/')
    new File(backup, 'node.before.xml').setText(new File(ci.rootDir, 'nodes/' + nodeName + '/config.xml').getText('UTF-8'), 'UTF-8')
}
agentRoot.mkdirs()
assert new File(agentRoot, '.owner-only').isFile() : 'Run start-local-agent.ps1 -PrepareOnly before creating the local agent secret.'
workspace.mkdirs()

def node = existingNode ?: new DumbSlave(nodeName, agentRoot.path, new JNLPLauncher())
node.setNumExecutors(1)
node.setMode(Node.Mode.EXCLUSIVE)
node.setLabelString('doorhandle-local-ci doorhandle-local-build windows')
node.setNodeDescription('Local build and SSH orchestration only. Application tests and runtime execute on ECS. ECS lifecycle is external.')
node.setRetentionStrategy(new RetentionStrategy.Always())
def variables = [
    'JAVA_HOME': settings.javaHome,
    'MAVEN_CMD': settings.maven,
    'LOCAL_PYTHON_EXE': settings.python,
    'PYTHON_EXE': settings.python,
    'DOORHANDLE_ECS_INSTANCE_ID': settings.instanceId,
    'DOORHANDLE_ECS_MACHINE_ID': settings.machineId,
    'DOORHANDLE_COMPACT_RELEASE_READY': 'false',
    'DOORHANDLE_COMPACT_REHEARSAL_READY': 'false',
    'CANDIDATE_BUILD_INPUT_CACHE_ROOT': new File(project, 'work/jenkins/build-deps').path,
    'PATH+DOORHANDLE': settings.extraPath
]
// Compact release/rehearsal readiness is deliberately not a user-editable job parameter.
def entries = variables.collect { key, value -> new EnvironmentVariablesNodeProperty.Entry(key, value.toString()) }
node.getNodeProperties().replace(new EnvironmentVariablesNodeProperty(entries))
if (existingNode == null) ci.addNode(node) else node.save()

def parameters = [
    new ChoiceParameterDefinition('ACTION', ['verify', 'verify-controls', 'verify-embedding', 'verify-runtime', 'verify-deploy', 'rehearse', 'rollback', 'compact-cutover', 'reclaim-build-outputs'] as String[], 'verify-controls runs only ECS control checks without building Java or preparing databases. Compact cutover requires complete source, database and runtime evidence.'),
    new ChoiceParameterDefinition('NATIVE_RETENTION_POLICY', ['FailedNative', 'RetiredCopies194', 'RetiredCopies203', 'PublicCaches221224235'] as String[], 'Maintenance only: select one native retention policy; default follows failed runtime builds.'),
    new StringParameterDefinition('FAILED_NATIVE_BUILD_NUMBER', '', 'FailedNative maintenance only: optional exact old build number; blank keeps the strict complete batch.').with { setTrim(true); it },
    new StringParameterDefinition('TRUSTED_COMMIT', '', 'Optional expected complete java-cloud commit; blank pins this SCM checkout.'),
    new ChoiceParameterDefinition('DOORHANDLE_CI_SCOPE', ['source', 'mysql'] as String[], 'source is ordinary verification; mysql requires explicit ECS fixtures.'),
    new StringParameterDefinition('DOORHANDLE_CI_FIXTURE_MANIFEST', '', 'mysql only: absolute private manifest inside the current ECS checkout/work.'),
    new BooleanParameterDefinition('DOORHANDLE_CI_AUTO_COMPACT_FIXTURES', false, 'mysql only: prepare independent owned ECS fixtures using this fixed source build.'),
    new StringParameterDefinition('DOORHANDLE_CI_FIXTURE_SETTINGS', '', 'Automatic fixture preparation: reviewed private ECS source identity, offsets and existing Java settings.'),
    new BooleanParameterDefinition('PRODUCTION_RELEASE_ENABLED', false, 'Keep false until compact schema and release compatibility are accepted.'),
    new StringParameterDefinition('COMPACT_CUTOVER_SETTINGS', '', 'Reuse reviewed fixture settings: version, sourceMysqlContainerId, sourceSchema, sourceOffsets, java; no passwords.'),
    new StringParameterDefinition('CANDIDATE_BUILD_TOOLS_ARCHIVE', '', 'Runtime/cutover public BuildKit OCI tar; blank prepares the pinned global D project cache. Raw tar is never archived.'),
    new StringParameterDefinition('LEGACY_SOURCE_SNAPSHOT', '', 'Optional sealed project snapshot directory; restoration occurs only on ECS after fixed-source verification.'),
    new StringParameterDefinition('LEGACY_SOURCE_ECS_SNAPSHOT', '', 'Reuse an independently restored ECS legacy snapshot; mutually exclusive with the local input.'),
    new StringParameterDefinition('LOCAL_ARTIFACTS_SNAPSHOT', '', 'Initial sealed local historical artifacts; transfer and recovery occur only after fixed-source verification.'),
    new StringParameterDefinition('LOCAL_ARTIFACTS_ECS_SNAPSHOT', '', 'Reuse independently restored ECS historical artifacts without returning private source bytes locally.'),
    new ChoiceParameterDefinition('LOCAL_ARTIFACTS_PROFILE', ['additional-local-artifacts-v1', 'residual-project-originals-v1', 'legacy-partial-transports-v1', 'remaining-business-records-v1'] as String[], 'Fixed artifact inventory: original 36 items, residual project files, early transport packets or the 250 reviewed business records and historical receipts.'),
    new StringParameterDefinition('COLD_STORES_SNAPSHOT', '', 'Optional sealed historical test stores; recover every store independently on ECS after fixed-source verification.'),
    new StringParameterDefinition('COLD_STORES_ECS_SNAPSHOT', '', 'Reuse an ECS-verified historical cold-store archive; mutually exclusive with its local input.'),
    new ChoiceParameterDefinition('COLD_STORES_PROFILE', ['cold-store-originals-v1', 'cold-store-history-v2'] as String[], 'Fixed archive inventory: original 70 storage roots or additional 4041 historical test/receipt roots.'),
    new StringParameterDefinition('COLD_HISTORY_SNAPSHOT', '', 'Additionally preserve the fixed v2 historical test/receipt packet in the same verified build.'),
    new StringParameterDefinition('COLD_HISTORY_ECS_SNAPSHOT', '', 'Reuse an independently verified v2 history packet on ECS; mutually exclusive with its local input.'),
    new StringParameterDefinition('LOCAL_MYSQL_SNAPSHOT', '', 'Approved local 45-table export packet; two independent recoveries run only on ECS after source verification.'),
    new StringParameterDefinition('LOCAL_MYSQL_ECS_SNAPSHOT', '', 'Reuse an ECS-verified 45-table export packet; mutually exclusive with its local input, with two new independent ECS recoveries.'),
    new StringParameterDefinition('LOCAL_MYSQL_FIXTURE_SETTINGS', '', 'Existing private ECS fixture JSON; only the reviewed MySQL image identity is used for local export recovery.'),
    new StringParameterDefinition('PROJECT_MYSQL_SNAPSHOT', '', 'Optional approved v2 three-schema packet; archive and double restore only after complete MySQL verification.'),
    new StringParameterDefinition('PROJECT_MYSQL_MANIFEST_SHA256', '', 'Explicit SHA-256 of its custody.json; all three project packet inputs are supplied together or left blank.'),
    new StringParameterDefinition('PROJECT_MYSQL_ARCHIVE_SHA256', '', 'Explicit SHA-256 of its originals.tar.gz; no production merge or local retirement.'),
    new StringParameterDefinition('REMAINING_SYSTEM_DATA_SNAPSHOT', '', 'Sealed fixed 86-file supplemental data packet; restore only on ECS after verification.'),
    new StringParameterDefinition('REMAINING_SYSTEM_DATA_ECS_SNAPSHOT', '', 'Reuse an already verified supplemental ECS packet; mutually exclusive with local input.'),
    new BooleanParameterDefinition('RECLAIM_OLD_BUILD_OUTPUTS', true, 'After complete source verification, reclaim only proven terminal reproducible build output; retain business data and evidence.'),
    new StringParameterDefinition('DEPLOY_HOST', '', 'Start ECS outside Jenkins, then configure its current verified SSH address.'),
    new StringParameterDefinition('DEPLOY_PORT', '22', 'Verified SSH port.'),
    new ChoiceParameterDefinition('SSH_TRANSPORT', ['direct', 'tls'] as String[], 'Preserve SSH host-key checking; TLS also verifies the existing server certificate.'),
    new StringParameterDefinition('SSH_TLS_CA_FILE', new File(project, 'work/cloud/ssh-tls/server.crt').path, 'Existing public TLS certificate; tls only.'),
    new StringParameterDefinition('OPENSSL_EXE', 'D:/ruanjian/Git/usr/bin/openssl.exe', 'Existing OpenSSL; tls only.'),
    new StringParameterDefinition('REMOTE_ROOT', '/home/ecs-user/doorhandle-ci', 'Isolated CI versions and evidence on ECS.'),
    new StringParameterDefinition('REMOTE_RUNTIME', '/home/ecs-user/doorhandle-release-20261014', 'Existing deployment runtime, not read by ordinary source verification.'),
    new StringParameterDefinition('PYTHON_EXE', settings.python.toString(), 'Existing local Python for evidence validation; never runs project tests locally.'),
    new ChoiceParameterDefinition('BUILD_NPM_REGISTRY', ['https://registry.npmjs.org', 'https://registry.npmmirror.com'] as String[], 'Remote image build registry only.'),
    new BooleanParameterDefinition('REHEARSAL_KEEP', false, 'Only retain an accepted isolated rehearsal.'),
    new StringParameterDefinition('COMPATIBLE_BACKEND_IMAGE', '', 'Independently accepted compatible backend image, if needed.'),
    new StringParameterDefinition('COMPATIBLE_RUNNER_IMAGE', '', 'Independently accepted compatible runner image, if needed.'),
    new StringParameterDefinition('REHEARSAL_MEMORY_EXTRACTION_MODEL', '', 'Explicit isolated rehearsal model, if needed.')
]
job.setDisabled(true)
def definition = new CpsScmFlowDefinition(job.getDefinition().getScm(), 'Jenkinsfile.ecs-monolith')
definition.setLightweight(true)
job.setDefinition(definition)
// Job.addProperty appends; remove all old instances so repeated configuration is idempotent.
while (job.getProperty(ParametersDefinitionProperty) != null) {
    job.removeProperty(ParametersDefinitionProperty)
}
while (job.getProperty(DisableConcurrentBuildsJobProperty) != null) {
    job.removeProperty(DisableConcurrentBuildsJobProperty)
}
while (job.getProperty(PipelineTriggersJobProperty) != null) {
    job.getProperty(PipelineTriggersJobProperty).getTriggers().each { it.stop() }
    job.removeProperty(PipelineTriggersJobProperty)
}
job.addProperty(new ParametersDefinitionProperty(parameters))
job.addProperty(new DisableConcurrentBuildsJobProperty())
job.addProperty(new PipelineTriggersJobProperty([new SCMTrigger('H/5 * * * *')]))
job.setBuildDiscarder(new LogRotator(-1, 15, -1, 5))
job.setDescription('Local Jenkins -> SSH -> already-started ECS 172.29.146.74. All tests/data/runtime on ECS. ECS lifecycle is outside CI/CD. Compact production release is disabled pending acceptance.')
job.save()
ci.getQueue().getItems().findAll { it.task == job }.each { ci.getQueue().cancel(it) }
ci.setNumExecutors(0)
ci.save()
def location = JenkinsLocationConfiguration.get()
location.setUrl('http://127.0.0.1:8080/')
location.save()

// This file is consumed as @file by Remoting; never print the connection secret.
def secretFile = new File(agentRoot, 'secret')
secretFile.setText(ci.getComputer(nodeName).getJnlpMac(), 'UTF-8')
if (settings.activate) {
    assert ci.getComputer(nodeName).isOnline() : 'Connect the dedicated local agent before enabling the project.'
    job.setDisabled(false)
    job.save()
    ci.doCancelQuietDown()
}
def result = [
    job: job.fullName, scriptPath: 'Jenkinsfile.ecs-monolith', disabled: job.isDisabled(),
    node: nodeName, nodeOnline: ci.getComputer(nodeName).isOnline(), controllerExecutors: ci.getNumExecutors(),
    quietingDown: ci.isQuietingDown(), workspace: workspace.path, backupDirectory: backup.path,
    instanceId: settings.instanceId, machineIdSource: settings.machineIdSource,
    lifecycle: 'external-to-jenkins', productionReleaseReady: false, rehearsalReady: false
]
new File(project, 'work/jenkins/configuration-receipt.json').setText(JsonOutput.prettyPrint(JsonOutput.toJson(result)), 'UTF-8')
println(JsonOutput.toJson(result))
