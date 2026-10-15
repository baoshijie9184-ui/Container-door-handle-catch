package com.ruanzhu.doorhandle.module.ai.eval;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.*;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;
import java.util.stream.Stream;
import static org.assertj.core.api.Assertions.*;

/** 固定数据集驱动的规则实验。模型和业务门面合成；不会读取 .env 或访问网络。 */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class AgentContractEvalTest {
    @TempDir Path workspace;
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    final List<AgentEvalReport.CaseResult> results=new ArrayList<>();
    AgentEvalDataset dataset;Path datasetPath;Path project;Instant began;
    @BeforeAll void load() throws Exception {
        began=Instant.now();project=Path.of(System.getProperty("agent.eval.project","..")).toAbsolutePath().normalize();
        datasetPath=project.resolve("eval/agent/dataset-v2.json");dataset=AgentEvalDataset.load(datasetPath,json);
        assertThat(dataset.fixtureVersion()).isEqualTo(AgentEvalFixture.VERSION);
    }
    @TestFactory Stream<DynamicTest> evaluate() {
        return dataset.cases().stream().map(spec->DynamicTest.dynamicTest(spec.caseId(),()->{
            long start=System.nanoTime();AgentEvalReport.CaseResult result;
            try(var fixture=new AgentEvalFixture()) {
                String outcome=fixture.execute(spec,workspace.resolve(spec.caseId()));
                var observed=fixture.observation(outcome);var score=AgentEvalScorer.score(spec.expected(),observed);
                result=new AgentEvalReport.CaseResult(spec.caseId(),score.passed()?AgentEvalReport.Status.PASS:AgentEvalReport.Status.FAIL,
                        elapsed(start),score.violations(),observed);
            } catch(Exception failure) {
                // 报告只输出固定失败标记，不输出数据库、异常正文或凭证。
                result=new AgentEvalReport.CaseResult(spec.caseId(),AgentEvalReport.Status.ERROR,elapsed(start),List.of("SCENARIO_EXECUTION_ERROR"),json.nullNode());
            }
            results.add(result);
            assertThat(result.status()).as(spec.caseId()+" "+result.violations()).isEqualTo(AgentEvalReport.Status.PASS);
        }));
    }
    @AfterAll void report() throws Exception {
        if(dataset==null)return;
        var metadata=new LinkedHashMap<String,Object>();
        metadata.put("mode","SCRIPTED_MODEL_SYNTHETIC_FACADES_H2");metadata.put("startedAt",began.toString());metadata.put("endedAt",Instant.now().toString());
        metadata.put("datasetSha256",hash(Files.readAllBytes(datasetPath)));metadata.put("fixtureVersion",AgentEvalFixture.VERSION);
        metadata.put("fixtureSha256",hash(Files.readAllBytes(project.resolve("doorhandle-module-ai/src/test/java/com/ruanzhu/doorhandle/module/ai/eval/AgentEvalFixture.java"))));
        metadata.put("agentPromptSourceSha256",hash(Files.readAllBytes(project.resolve("doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/agent/RoleAgentFactory.java"))));
        metadata.put("toolCatalogSha256",hash(Files.readAllBytes(project.resolve("doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/agent/RoleAgentCatalog.java"))));
        var sdkVersion=java.util.regex.Pattern.compile("<agentscope.version>([^<]+)</agentscope.version>").matcher(Files.readString(project.resolve("pom.xml")));
        metadata.put("agentscopeVersion",sdkVersion.find()?sdkVersion.group(1):"UNKNOWN");metadata.put("jdkVersion",System.getProperty("java.version"));
        metadata.put("codeCommit",System.getProperty("agent.eval.commit","UNKNOWN"));metadata.put("workingTreeDirty",System.getProperty("agent.eval.dirty","UNKNOWN"));
        metadata.put("sourceSha256",sourceHash());metadata.put("model","scripted-eval-model");metadata.put("businessSnapshot","synthetic-fixed-values-v1");
        metadata.put("actionPolicy",com.ruanzhu.doorhandle.module.ai.action.AgentActionService.POLICY);
        var report=AgentEvalReport.build(dataset,results,metadata,json);
        String baseline=System.getProperty("agent.eval.baseline");boolean comparisonPassed=true;
        if(baseline!=null) {
            try {
                var comparison=AgentEvalReport.compare(report,json.readTree(Files.readString(Path.of(baseline))),json);
                report.set("baselineComparison",comparison);comparisonPassed=comparison.path("noRegressions").asBoolean();
            } catch(Exception invalid) {
                report.set("baselineComparison",json.createObjectNode().put("compatible",false).put("reason","BASELINE_INVALID_OR_INCOMPATIBLE"));comparisonPassed=false;
            }
        }
        report.put("experimentGatePassed",report.path("contractGatePassed").asBoolean()&&comparisonPassed);
        Path output=Path.of(System.getProperty("agent.eval.output","target/agent-eval")).toAbsolutePath();Files.createDirectories(output);
        // 整份报告含合成观测，不包含 Prompt、模型思考或真实用户资料。
        Path temporary=output.resolve("report.json.tmp");Files.writeString(temporary,json.writerWithDefaultPrettyPrinter().writeValueAsString(report));
        Files.move(temporary,output.resolve("report.json"),StandardCopyOption.REPLACE_EXISTING);
        var markdown=new StringBuilder("# Agent 离线规则评测\n\n模式：SCRIPTED_MODEL_SYNTHETIC_FACADES_H2\n\n");
        markdown.append("数据集：").append(dataset.version()).append("；评分器：").append(AgentEvalScorer.VERSION).append("\n\n");
        markdown.append("规则门槛：").append(report.path("contractGatePassed").asBoolean()?"通过":"未通过").append("。本报告不批准生产发布，不评估真实模型回答质量。\n\n");
        markdown.append("| 用例 | 分类 | 状态 | 规则失败 |\n| --- | --- | --- | --- |\n");
        for(var item:report.path("cases"))markdown.append("| ").append(item.path("caseId").asText()).append(" | ").append(item.path("category").asText()).append(" | ").append(item.path("status").asText()).append(" | ").append(markdownCell(item.path("violations").toString())).append(" |\n");
        if(report.has("baselineComparison"))markdown.append("\n基线比较：").append(comparisonPassed?"兼容且无退化":"不兼容或存在退化").append("\n");
        Files.writeString(output.resolve("report.md"),markdown.toString());
        assertThat(report.path("contractGatePassed").asBoolean()).as("完整必测规则门槛").isTrue();
        assertThat(comparisonPassed).as("基线兼容性与逐例退化").isTrue();
    }
    private long elapsed(long start){return (System.nanoTime()-start)/1_000_000;}
    private String markdownCell(String value){return value.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("|","&#124;").replace("\n"," ").replace("\r"," ");}
    private String sourceHash() throws Exception {
        var digest=MessageDigest.getInstance("SHA-256");
        for(String folder:List.of("doorhandle-module-ai/src","doorhandle-contracts/src")) {
            try(var paths=Files.walk(project.resolve(folder))) {
                for(Path path:paths.filter(Files::isRegularFile).sorted().toList()) {
                    digest.update(project.relativize(path).toString().replace('\\','/').getBytes(java.nio.charset.StandardCharsets.UTF_8));
                    digest.update((byte)0);digest.update(Files.readAllBytes(path));digest.update((byte)0);
                }
            }
        }
        for(String name:List.of("pom.xml","doorhandle-module-ai/pom.xml","eval/agent/dataset-v2.json","script/shell/run-agent-eval.ps1"))digest.update(Files.readAllBytes(project.resolve(name)));
        return HexFormat.of().formatHex(digest.digest());
    }
    private String hash(byte[] value)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value));}
}
