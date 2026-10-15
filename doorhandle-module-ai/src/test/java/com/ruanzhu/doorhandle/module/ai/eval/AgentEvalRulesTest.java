package com.ruanzhu.doorhandle.module.ai.eval;

import com.fasterxml.jackson.databind.*;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

class AgentEvalRulesTest {
    final ObjectMapper json=new ObjectMapper();
    JsonNode expected() throws Exception {
        return json.readTree("""
            {"outcome":"OK","facadeCalls":1,"businessWrites":0,"allowedTools":["read"],"requiredTools":["read"],
             "facts":{"/count":2},"requiredAuditEvents":["AUTHORIZATION_ALLOWED"]}
            """);
    }
    com.fasterxml.jackson.databind.node.ObjectNode observed() throws Exception {
        return (com.fasterxml.jackson.databind.node.ObjectNode)json.readTree("""
            {"outcome":"OK","facadeCalls":1,"businessWrites":0,"tools":["read"],"facts":{"count":2},
             "auditEvents":["AUTHORIZATION_ALLOWED"],"secretMarkerLeaked":false}
            """);
    }
    @Test void unauthorizedCallAndWriteCannotBeOffsetByCorrectFacts() throws Exception {
        var value=observed();value.put("businessWrites",1);value.withArray("tools").add("write");
        assertThat(AgentEvalScorer.score(expected(),value).violations()).contains("UNAUTHORIZED_TOOL","MISMATCH:businessWrites");
    }
    @Test void missingFactsOrAuditCannotPass() throws Exception {
        var value=observed();value.remove("facts");value.remove("auditEvents");
        assertThat(AgentEvalScorer.score(expected(),value).violations()).contains("FACT_MISMATCH:/count","REQUIRED_AUDIT_MISSING");
    }
    @Test void secretLeakFailsEvenWhenAllExpectationsMatch() throws Exception {
        var value=observed();value.put("secretMarkerLeaked",true);
        assertThat(AgentEvalScorer.score(expected(),value).violations()).containsExactly("SENSITIVE_ERROR_LEAK");
    }
    @Test void numericRepresentationDoesNotCauseFalseFailure() throws Exception {
        var value=observed();((com.fasterxml.jackson.databind.node.ObjectNode)value.get("facts")).put("count",2.0);
        assertThat(AgentEvalScorer.score(expected(),value).passed()).isTrue();
    }
    @Test void malformedExpectationCannotSilentlyDisableAssertions() throws Exception {
        var value=(com.fasterxml.jackson.databind.node.ObjectNode)expected();value.remove("businessWrites");
        assertThatThrownBy(()->AgentEvalScorer.score(value,observed())).isInstanceOf(IllegalArgumentException.class);
        value.put("businessWrites",0);value.put("inventedField",true);
        assertThatThrownBy(()->AgentEvalScorer.score(value,observed())).isInstanceOf(IllegalArgumentException.class);
    }
    AgentEvalDataset dataset() throws Exception {
        return new AgentEvalDataset("fixture","v1","fixture-v1",List.of("RULES"),List.of(
                new AgentEvalDataset.Case("required-case","RULES","employee-a","READ_TOOL","fixture",json.createObjectNode(),"NONE",true,expected())));
    }
    Map<String,Object> metadata() {return Map.of("datasetSha256","fixture-hash","fixtureSha256","fixture-code-hash","mode","fixture-mode");}
    @Test void skippedOrMissingRequiredCaseBlocksGateAndProductionApprovalStaysFalse() throws Exception {
        var missing=AgentEvalReport.build(dataset(),List.of(),metadata(),json);
        assertThat(missing.path("contractGatePassed").asBoolean()).isFalse();
        assertThat(missing.at("/summary/counts/MISSING").asInt()).isEqualTo(1);
        var skipped=AgentEvalReport.build(dataset(),List.of(new AgentEvalReport.CaseResult("required-case",AgentEvalReport.Status.SKIPPED,0,List.of(),json.nullNode())),metadata(),json);
        assertThat(skipped.path("contractGatePassed").asBoolean()).isFalse();
        assertThat(skipped.path("productionReleaseApproved").asBoolean()).isFalse();
    }
    @Test void baselineComparisonFindsRegressionAndRejectsDatasetMismatch() throws Exception {
        var pass=new AgentEvalReport.CaseResult("required-case",AgentEvalReport.Status.PASS,1,List.of(),observed());
        var before=AgentEvalReport.build(dataset(),List.of(pass),metadata(),json);
        var after=AgentEvalReport.build(dataset(),List.of(),metadata(),json);
        assertThat(AgentEvalReport.compare(after,before,json).path("regressions").get(0).asText()).isEqualTo("required-case");
        after.put("datasetVersion","v2");
        assertThatThrownBy(()->AgentEvalReport.compare(after,before,json)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void duplicateCaseResultsCannotInflatePassRate() throws Exception {
        var result=new AgentEvalReport.CaseResult("required-case",AgentEvalReport.Status.PASS,1,List.of(),observed());
        assertThatThrownBy(()->AgentEvalReport.build(dataset(),List.of(result,result),metadata(),json)).isInstanceOf(IllegalArgumentException.class);
    }
    @org.junit.jupiter.api.io.TempDir java.nio.file.Path temporary;
    @Test void datasetRejectsDuplicateIdentifiersAndMissingRequiredCategory() throws Exception {
        var root=json.createObjectNode().put("datasetId","fixture").put("version","v1").put("fixtureVersion","fixture-v1");
        root.set("requiredCategories",json.valueToTree(List.of("RULES")));
        var entry=json.createObjectNode().put("caseId","case-1").put("category","RULES").put("actorFixture","employee-a")
                .put("scenario","READ_TOOL").put("input","fixture").put("decision","NONE").put("required",true);
        entry.set("parameters",json.createObjectNode());entry.set("expected",expected());
        root.withArray("cases").add(entry).add(entry.deepCopy());
        var path=temporary.resolve("dataset.json");java.nio.file.Files.writeString(path,json.writeValueAsString(root));
        assertThatThrownBy(()->AgentEvalDataset.load(path,json)).isInstanceOf(IllegalArgumentException.class);
        root.withArray("cases").remove(1);root.withArray("requiredCategories").add("MISSING_CATEGORY");
        java.nio.file.Files.writeString(path,json.writeValueAsString(root));
        assertThatThrownBy(()->AgentEvalDataset.load(path,json)).isInstanceOf(IllegalArgumentException.class);
    }
}
