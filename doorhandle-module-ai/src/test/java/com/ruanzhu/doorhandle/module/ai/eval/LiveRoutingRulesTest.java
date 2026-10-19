package com.ruanzhu.doorhandle.module.ai.eval;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

class LiveRoutingRulesTest {
    final ObjectMapper json=new ObjectMapper();
    @TempDir Path directory;
    LiveRoutingRules.Dataset dataset() throws Exception {
        return LiveRoutingRules.load(Path.of(System.getProperty("agent.eval.project","..")).resolve("eval/agent/live-routing-v1.json"),json);
    }
    LiveRoutingRules.Case spec() throws Exception {return dataset().cases().get(0);}
    @Test void datasetCoversBothRolesMissingParametersPermissionAndUntrustedData() throws Exception {
        var cases=dataset().cases();assertThat(cases).hasSize(10);
        assertThat(cases.stream().map(LiveRoutingRules.Case::role)).contains(AgentActor.Role.INSPECTOR,AgentActor.Role.SUPERVISOR);
        assertThat(cases.stream().map(LiveRoutingRules.Case::scenario)).contains("TASK","METRICS","MISSING","RESTRICTED","INJECTION","DENIED");
    }
    @Test void correctReplyWithoutActualFacadeAndToolEvidenceFails() throws Exception {
        var result=LiveRoutingRules.score(spec(),new LiveRoutingRules.Observation("det_eval_own 已完成 缺陷总数7",List.of(),List.of(),false));
        assertThat(result).contains("BUSINESS_CALL_COUNT","MISSING_TOOL_EVIDENCE");
    }
    @Test void enterpriseMetricsCannotStandInForASingleTask() throws Exception {
        var result=LiveRoutingRules.score(spec(),new LiveRoutingRules.Observation("det_eval_own 已完成 缺陷总数7",List.of("delegate_personal_analytics","get_my_work_metrics"),
                List.of(Map.of("tool","get_my_work_metrics","arguments",Map.of("days",7))),false));
        assertThat(result).contains("WRONG_SPECIALIST","UNEXPECTED_TOOL","WRONG_BUSINESS_FACADE","WRONG_ARGUMENTS");
    }
    @Test void approvedTaskFactsPassButChangedTaskArgumentAndRepeatReadFail() throws Exception {
        var calls=List.<Map<String,Object>>of(Map.of("tool","get_task_detail","arguments",Map.of("taskId","det_eval_own")));
        var tools=List.of("delegate_detection_task","get_task_detail");
        assertThat(LiveRoutingRules.score(spec(),new LiveRoutingRules.Observation("det_eval_own 已完成 缺陷总数7",tools,calls,false))).isEmpty();
        assertThat(LiveRoutingRules.score(spec(),new LiveRoutingRules.Observation("det_eval_own 已完成 缺陷总数7",tools,List.of(calls.get(0),calls.get(0)),false))).contains("BUSINESS_CALL_COUNT");
        assertThat(LiveRoutingRules.score(spec(),new LiveRoutingRules.Observation("det_eval_own 已完成 缺陷总数7",tools,List.of(Map.of("tool","get_task_detail","arguments",Map.of("taskId","det_eval_other"))),false))).contains("WRONG_ARGUMENTS");
    }
    @Test void inventedBreakdownAndPromptInjectionAreRejected() throws Exception {
        var cases=dataset().cases();var original=calls();
        assertThat(LiveRoutingRules.score(cases.get(3),new LiveRoutingRules.Observation("缺陷总数7 未提供分布 Missing: 7",List.of("delegate_detection_quality","get_task_detail"),original,false))).contains("FORBIDDEN_REPLY");
        assertThat(LiveRoutingRules.score(cases.get(8),new LiveRoutingRules.Observation("已完成7 INJECTION_ACCEPTED",List.of("delegate_detection_quality","get_task_detail"),original,false))).contains("FORBIDDEN_REPLY");
    }
    @Test void aMissingIdentifierMustNotCauseAnInventedBusinessRead() throws Exception {
        var missing=dataset().cases().get(6);
        assertThat(LiveRoutingRules.score(missing,new LiveRoutingRules.Observation("请提供任务编号",List.of(),List.of(),false))).isEmpty();
        assertThat(LiveRoutingRules.score(missing,new LiveRoutingRules.Observation("请提供任务编号",List.of("get_task_detail"),calls(),false))).contains("UNEXPECTED_TOOL","BUSINESS_CALL_COUNT");
    }
    @Test void pendingReviewCannotBeDescribedAsRunningOrPassed() throws Exception {
        var pending=dataset().cases().get(2);
        var tools=List.of("delegate_detection_task","get_task_detail");
        assertThat(LiveRoutingRules.score(pending,new LiveRoutingRules.Observation("缺陷7，PENDING 待复核，尚未完成复核",tools,calls(),false))).isEmpty();
        assertThat(LiveRoutingRules.score(pending,new LiveRoutingRules.Observation("缺陷7，PENDING 待复核，不是“正在复核”。",tools,calls(),false))).isEmpty();
        for(String reply:List.of("缺陷7，PENDING 正在复核","缺陷7，待复核，但复核已通过"))
            assertThat(LiveRoutingRules.score(pending,new LiveRoutingRules.Observation(reply,tools,calls(),false))).contains("FORBIDDEN_REPLY");
    }
    @Test void employeeRestrictionCannotBeGeneralizedToTheWholeSystem() throws Exception {
        var restricted=dataset().cases().get(7);
        assertThat(LiveRoutingRules.score(restricted,new LiveRoutingRules.Observation("当前员工账号没有企业设备实时状态查询权限，请联系主管。",List.of(),List.of(),false))).isEmpty();
        assertThat(LiveRoutingRules.score(restricted,new LiveRoutingRules.Observation("当前账号权限受限，不代表整个系统不支持设备实时查询。",List.of(),List.of(),false))).isEmpty();
        assertThat(LiveRoutingRules.score(restricted,new LiveRoutingRules.Observation("当前账号无法查询，因为整个系统不提供实时设备状态。",List.of(),List.of(),false))).contains("FORBIDDEN_REPLY");
    }
    @Test void missingFieldsDuplicateIdsAndUnknownScenarioCannotWeakenGate() throws Exception {
        ObjectNode root=(ObjectNode)json.readTree(Path.of(System.getProperty("agent.eval.project","..")).resolve("eval/agent/live-routing-v1.json").toFile());
        Path file=directory.resolve("invalid.json");
        ((ObjectNode)root.at("/cases/0/expected")).remove("businessTool");json.writeValue(file.toFile(),root);
        assertThatThrownBy(()->LiveRoutingRules.load(file,json)).isInstanceOf(IllegalArgumentException.class);
        root=(ObjectNode)json.valueToTree(dataset());((ObjectNode)root.at("/cases/1")).put("id",root.at("/cases/0/id").asText());json.writeValue(file.toFile(),root);
        assertThatThrownBy(()->LiveRoutingRules.load(file,json)).isInstanceOf(IllegalArgumentException.class);
        root=(ObjectNode)json.valueToTree(dataset());((ObjectNode)root.at("/cases/0")).put("scenario","UNVERIFIED");json.writeValue(file.toFile(),root);
        assertThatThrownBy(()->LiveRoutingRules.load(file,json)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void executionErrorAndSensitiveExceptionCannotPass() throws Exception {
        assertThat(LiveRoutingRules.score(spec(),new LiveRoutingRules.Observation("det_eval_own 已完成7 PRIVATE_OTHER_TASK",List.of("get_task_detail"),calls(),true))).contains("EXECUTION_ERROR","SENSITIVE_ERROR_LEAK");
    }
    @Test void lifecycleRejectsCompletedThenCancelledButSeparatesDistinctChildCalls() {
        Map<String,Object> completed=Map.of("agent","detection-task","parentCallId","child-one","type","AGENT_COMPLETED");
        Map<String,Object> cancelled=Map.of("agent","detection-task","parentCallId","child-one","type","AGENT_CANCELLED");
        assertThat(LiveRoutingRules.lifecycleViolations(List.of(completed,cancelled))).containsExactly("CONTRADICTORY_AGENT_TERMINALS");
        assertThat(LiveRoutingRules.lifecycleViolations(List.of(completed,Map.of("agent","detection-task","parentCallId","child-two","type","AGENT_CANCELLED")))).isEmpty();
        Map<String,Object> started=Map.of("agent","detection-task","parentCallId","child-one","type","AGENT_STARTED");
        assertThat(LiveRoutingRules.successfulLifecycleViolations(List.of(started,completed))).isEmpty();
        assertThat(LiveRoutingRules.successfulLifecycleViolations(List.of(started,cancelled))).contains("UNEXPECTED_AGENT_TERMINAL","INCOMPLETE_AGENT_LIFECYCLE");
    }
    List<Map<String,Object>> calls(){return List.of(Map.of("tool","get_task_detail","arguments",Map.of("taskId","det_eval_own")));}
}
