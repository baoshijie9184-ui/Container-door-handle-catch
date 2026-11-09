// Run through authenticated /scriptText after pushing the matching pipeline change.
// Replace only this choice parameter while its existing SCM job is idle.
import groovy.json.JsonOutput
import hudson.BulkChange
import hudson.model.ChoiceParameterDefinition
import hudson.model.ParametersDefinitionProperty
import hudson.model.Queue
import jenkins.model.Jenkins
import org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition
import org.jenkinsci.plugins.workflow.job.WorkflowJob

def ci = Jenkins.get()
def choices = ['additional-local-artifacts-v1', 'residual-project-originals-v1',
               'legacy-partial-transports-v1', 'remaining-business-records-v1']

Queue.withLock({ ->
    def job = ci.getItem('doorhandle-java')
    assert job instanceof WorkflowJob
    synchronized (job) {
        assert !job.isBuilding() && !ci.getQueue().getItems().any { it.task == job }
        def definition = job.getDefinition()
        assert definition instanceof CpsScmFlowDefinition
        assert definition.getScriptPath() == 'Jenkinsfile.ecs-monolith'
        def scm = definition.getScm()
        def property = job.getProperty(ParametersDefinitionProperty)
        assert property != null
        def parameters = new ArrayList(property.getParameterDefinitions())
        def names = parameters.collect { it.name }
        assert names.toSet().size() == names.size()
        def original = property.getParameterDefinition('LOCAL_ARTIFACTS_PROFILE')
        assert original instanceof ChoiceParameterDefinition
        assert original.getDefaultParameterValue().getValue() == choices[0]
        def otherProperties = job.getProperties().findAll { key, value -> !value.is(property) }

        if (original.getChoices() == choices) {
            println(JsonOutput.toJson([status: 'NO_ACTION', job: job.fullName, choices: choices]))
            return
        }

        def replacement = new ChoiceParameterDefinition('LOCAL_ARTIFACTS_PROFILE',
            choices as String[], original.getDescription())
        assert replacement.getDefaultParameterValue().getValue() == choices[0]
        def definitions = parameters.collect { it.is(original) ? replacement : it }
        assert definitions.collect { it.name } == names
        parameters.eachWithIndex { parameter, index ->
            assert definitions[index].is(parameter.is(original) ? replacement : parameter)
        }

        def change = new BulkChange(job)
        try {
            job.removeProperty(ParametersDefinitionProperty)
            job.addProperty(new ParametersDefinitionProperty(definitions))
            def after = job.getProperty(ParametersDefinitionProperty).getParameterDefinitions()
            assert after.collect { it.name } == names
            parameters.eachWithIndex { parameter, index ->
                assert after[index].is(parameter.is(original) ? replacement : parameter)
            }
            assert job.getProperty(ParametersDefinitionProperty)
                .getParameterDefinition('LOCAL_ARTIFACTS_PROFILE').getChoices() == choices
            def otherAfter = job.getProperties().findAll { key, value ->
                !(value instanceof ParametersDefinitionProperty)
            }
            assert otherAfter.keySet() == otherProperties.keySet()
            assert otherProperties.every { key, value -> otherAfter[key].is(value) }
            assert job.getDefinition().is(definition) && definition.getScm().is(scm)
            assert definition.getScriptPath() == 'Jenkinsfile.ecs-monolith'
            assert !job.isBuilding() && !ci.getQueue().getItems().any { it.task == job }
            change.commit()
        } catch (Throwable failure) {
            job.removeProperty(ParametersDefinitionProperty)
            job.addProperty(property)
            throw failure
        } finally {
            change.abort()
        }
        println(JsonOutput.toJson([status: 'UPDATED', job: job.fullName, choices: choices]))
    }
} as Runnable)
