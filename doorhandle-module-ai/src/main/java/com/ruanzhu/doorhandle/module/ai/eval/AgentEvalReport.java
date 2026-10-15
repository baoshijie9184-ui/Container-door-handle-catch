package com.ruanzhu.doorhandle.module.ai.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.*;

/** 完整性优先的报告：缺失必测、执行异常和任何失败均不能通过规则门槛。 */
public final class AgentEvalReport {
    private AgentEvalReport() { }
    public enum Status { PASS, FAIL, ERROR, SKIPPED, MISSING }
    public record CaseResult(String caseId,Status status,long durationMs,List<String> violations,JsonNode observed) { }
    public static ObjectNode build(AgentEvalDataset dataset,List<CaseResult> results,Map<String,Object> metadata,ObjectMapper json) {
        var declared=new HashSet<String>();dataset.cases().forEach(c->declared.add(c.caseId()));
        var actual=new LinkedHashMap<String,CaseResult>();
        for(var result:results)if(!declared.contains(result.caseId())||actual.put(result.caseId(),result)!=null)
            throw new IllegalArgumentException("报告包含未知或重复用例");
        var rows=new ArrayList<Map<String,Object>>();var counts=new EnumMap<Status,Integer>(Status.class);
        for(var status:Status.values())counts.put(status,0);
        boolean gate=true;int required=0;var categories=new LinkedHashMap<String,Map<String,Integer>>();
        for(var spec:dataset.cases()) {
            CaseResult result=actual.getOrDefault(spec.caseId(),new CaseResult(spec.caseId(),Status.MISSING,0,List.of("CASE_NOT_EXECUTED"),json.nullNode()));
            if(spec.required())required++;
            if((spec.required()&&result.status()!=Status.PASS)||result.status()==Status.FAIL||result.status()==Status.ERROR)gate=false;
            counts.compute(result.status(),(key,value)->value+1);
            var category=categories.computeIfAbsent(spec.category(),key->new LinkedHashMap<>());
            category.merge(result.status().name(),1,Integer::sum);
            var row=new LinkedHashMap<String,Object>();row.put("caseId",spec.caseId());row.put("category",spec.category());row.put("required",spec.required());
            row.put("status",result.status());row.put("durationMs",result.durationMs());row.put("violations",result.violations());row.put("observed",result.observed());rows.add(row);
        }
        var report=json.createObjectNode();report.put("schemaVersion","agent-eval-report-v1");
        report.set("metadata",json.valueToTree(metadata));report.put("datasetId",dataset.datasetId());report.put("datasetVersion",dataset.version());
        report.put("fixtureVersion",dataset.fixtureVersion());report.put("scorerVersion",AgentEvalScorer.VERSION);
        report.put("contractGatePassed",gate);report.put("productionReleaseApproved",false);
        report.set("summary",json.valueToTree(Map.of("total",dataset.cases().size(),"required",required,"executed",counts.get(Status.PASS)+counts.get(Status.FAIL)+counts.get(Status.ERROR),"counts",counts,"categories",categories)));
        report.set("cases",json.valueToTree(rows));
        report.set("notCovered",json.valueToTree(List.of("真实模型的语义路由与回答质量","真实 MySQL 数据范围与业务门面","RAG/记忆提示注入","跨进程与负载容量","模型 token 与供应商成本")));
        return report;
    }
    public static ObjectNode compare(JsonNode candidate,JsonNode baseline,ObjectMapper json) {
        for(String pointer:List.of("/schemaVersion","/datasetId","/datasetVersion","/fixtureVersion","/scorerVersion","/metadata/datasetSha256","/metadata/fixtureSha256","/metadata/mode")) {
            JsonNode left=candidate.at(pointer),right=baseline.at(pointer);
            if(left.isMissingNode()||right.isMissingNode()||!left.equals(right))throw new IllegalArgumentException("基线数据集、模式或评分器不兼容");
        }
        var before=statuses(baseline);var after=statuses(candidate);
        if(!before.keySet().equals(after.keySet()))throw new IllegalArgumentException("基线用例集合不完整");
        var regressions=new ArrayList<String>();var improvements=new ArrayList<String>();
        for(String id:before.keySet()) {
            if(before.get(id).equals("PASS")&&!after.get(id).equals("PASS"))regressions.add(id);
            if(!before.get(id).equals("PASS")&&after.get(id).equals("PASS"))improvements.add(id);
        }
        var comparison=json.createObjectNode();comparison.put("compatible",true);comparison.put("noRegressions",regressions.isEmpty());
        comparison.set("regressions",json.valueToTree(regressions));comparison.set("improvements",json.valueToTree(improvements));
        return comparison;
    }
    private static Map<String,String> statuses(JsonNode report) {
        if(!report.path("cases").isArray())throw new IllegalArgumentException("基线缺少逐例结果");
        var result=new LinkedHashMap<String,String>();
        for(var item:report.get("cases")) {
            String id=AgentEvalDataset.identifier(item,"caseId"),status=item.path("status").asText();
            try {Status.valueOf(status);}catch(IllegalArgumentException invalid){throw new IllegalArgumentException("无效基线状态");}
            if(result.put(id,status)!=null)throw new IllegalArgumentException("基线用例重复");
        }
        return result;
    }
}
