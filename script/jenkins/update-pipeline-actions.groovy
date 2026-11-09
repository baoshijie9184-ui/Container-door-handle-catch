// Update only the action choices after a committed pipeline change.
// Run from the authenticated local controller while this job is idle.
import groovy.json.JsonOutput
import hudson.model.ChoiceParameterDefinition
import hudson.model.ParametersDefinitionProperty
import jenkins.model.Jenkins
import org.jenkinsci.plugins.workflow.job.WorkflowJob

def ci = Jenkins.get()
def job = ci.getItem('doorhandle-java')
assert job instanceof WorkflowJob
assert !job.isBuilding() && !ci.getQueue().getItems().any { it.task == job }
def property = job.getProperty(ParametersDefinitionProperty)
assert property != null
assert property.getParameterDefinition('ACTION') instanceof ChoiceParameterDefinition
def choices = ['verify', 'verify-controls', 'verify-embedding', 'verify-runtime', 'verify-deploy',
               'rehearse', 'rollback', 'compact-cutover', 'reclaim-build-outputs']
def before = property.getParameterDefinition('ACTION').getChoices()
if (before == choices) {
    println(JsonOutput.toJson([status: 'NO_ACTION', job: job.fullName, actions: choices]))
    return
}
def directory = new File('D:/AI/lunwen1/DoorHandleCatch/work/jenkins/action-configuration-' + UUID.randomUUID())
assert directory.mkdirs()
new File(directory, 'job.before.xml').setText(job.getConfigFile().asString(), 'UTF-8')
def definitions = property.getParameterDefinitions().collect {
    it.name == 'ACTION' ? new ChoiceParameterDefinition('ACTION', choices as String[],
        'verify-controls: ECS control checks only; verify-runtime: full isolated acceptance.') : it
}
job.removeProperty(ParametersDefinitionProperty)
job.addProperty(new ParametersDefinitionProperty(definitions))
job.save()
println(JsonOutput.toJson([status: 'UPDATED', job: job.fullName, actions: choices,
    backupDirectory: directory.path, otherConfigurationPreserved: true]))
