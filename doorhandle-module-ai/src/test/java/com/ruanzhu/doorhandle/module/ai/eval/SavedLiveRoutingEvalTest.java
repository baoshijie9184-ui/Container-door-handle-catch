package com.ruanzhu.doorhandle.module.ai.eval;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import java.nio.file.*;
import java.security.MessageDigest;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

/** Re-score immutable observations after a rubric fix; never construct an SDK or provider. */
@EnabledIfSystemProperty(named="agent.eval.saved",matches=".+")
class SavedLiveRoutingEvalTest {
    @Test void rescoreSavedProviderObservationsWithoutAnotherPaidRequest() throws Exception {
        Path project=Path.of(System.getProperty("agent.eval.project","..")).toRealPath();
        Path input=Path.of(System.getProperty("agent.eval.saved")).toRealPath();
        Path output=Path.of(System.getProperty("agent.eval.rescored")).toAbsolutePath().normalize();
        assertThat(input.startsWith(project.resolve("work"))).isTrue();
        assertThat(output.startsWith(project.resolve("work"))).isTrue();
        assertThat(Files.exists(output)).isFalse();
        assertThat(Files.size(input)).isLessThan(8L*1024*1024);
        var json=new ObjectMapper();var original=json.readTree(input.toFile());
        assertThat(original.path("providerMode").asText()).isEqualTo("REAL_PROVIDER_SYNTHETIC_BUSINESS");
        assertThat(original.path("fallbackEnabled").asBoolean()).isFalse();
        assertThat(original.path("modelRequests").asInt()).isBetween(1,48);
        var paths=Set.of("agent/RoleAgentFactory.java","agent/RoleAgentCatalog.java","tool/BusinessToolkitFactory.java",
                "journal/AgentJournalMiddleware.java","model/AgentModelService.java");
        var hashes=original.path("sourceHashes");assertThat(hashes.size()).isEqualTo(paths.size());
        for(String path:paths)assertThat(hash(project.resolve("doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/"+path)))
                .as("Saved observation must match current production source: "+path).isEqualTo(hashes.path(path).asText());
        assertThat(hash(project.resolve("doorhandle-module-ai/src/test/java/com/ruanzhu/doorhandle/module/ai/eval/LiveRoutingRules.java")))
                .as("Scoring implementation must be unchanged; this replay only corrects dataset patterns")
                .isEqualTo(original.path("scorerSha256").asText());
        var datasetPath=project.resolve("eval/agent/live-routing-v1.json");
        var cases=LiveRoutingRules.load(datasetPath,json).cases();var observations=original.path("results");
        assertThat(observations.size()).isEqualTo(cases.size());
        var results=new ArrayList<Map<String,Object>>();var seen=new HashSet<String>();
        for(var row:observations){
            String id=row.path("caseId").asText();assertThat(seen.add(id)).isTrue();
            var spec=cases.stream().filter(c->c.id().equals(id)).findFirst().orElseThrow();
            assertThat(row.path("role").asText()).isEqualTo(spec.role().name());
            assertThat(row.path("input").asText()).isEqualTo(spec.question());
            assertThat(row.has("reply")&&row.path("tools").isArray()&&row.path("facadeCalls").isArray()&&row.path("events").isArray()).isTrue();
            List<String> tools=json.convertValue(row.path("tools"),new TypeReference<>(){});
            List<Map<String,Object>> calls=json.convertValue(row.path("facadeCalls"),new TypeReference<>(){});
            List<Map<String,Object>> events=json.convertValue(row.path("events"),new TypeReference<>(){});
            var violations=new ArrayList<>(LiveRoutingRules.score(spec,new LiveRoutingRules.Observation(row.path("reply").asText(),tools,calls,row.has("errorType"))));
            violations.addAll(LiveRoutingRules.successfulLifecycleViolations(events));
            results.add(Map.of("caseId",id,"status",violations.isEmpty()?"PASS":"FAIL","violations",violations));
        }
        boolean passed=results.stream().allMatch(row->row.get("status").equals("PASS"));
        var report=new LinkedHashMap<String,Object>();
        report.put("at",OffsetDateTime.now(ZoneOffset.ofHours(8)).toString());
        report.put("mode","SAVED_OBSERVATIONS_RUBRIC_REVIEW");report.put("modelId",original.path("modelId").asText());
        report.put("originalReportSha256",hash(input));report.put("originalDatasetSha256",original.path("datasetSha256").asText());
        report.put("datasetSha256",hash(datasetPath));report.put("scorerVersion","live-routing-rules-v3");
        report.put("sourceHashes",hashes);report.put("originalFixtureSha256",original.path("fixtureSha256").asText());
        report.put("additionalModelRequests",0);report.put("results",results);report.put("gatePassed",passed);
        report.put("productionReleaseApproved",false);
        Files.createDirectories(output.getParent());
        Files.writeString(output,json.writerWithDefaultPrettyPrinter().writeValueAsString(report),StandardOpenOption.CREATE_NEW);
        assertThat(passed).as("All saved observations must pass the corrected rubric; original evidence remains unchanged").isTrue();
    }
    private String hash(Path path) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)));
    }
}
