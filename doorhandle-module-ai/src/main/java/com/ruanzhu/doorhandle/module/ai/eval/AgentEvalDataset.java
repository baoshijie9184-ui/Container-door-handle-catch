package com.ruanzhu.doorhandle.module.ai.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.*;
import java.util.*;

/** 版本化的离线评测契约，不装配 Spring Bean，也不接受在线用户上传。 */
public record AgentEvalDataset(String datasetId, String version, String fixtureVersion,
                               List<String> requiredCategories, List<Case> cases) {
    public record Case(String caseId, String category, String actorFixture, String scenario,
                       String input, JsonNode parameters, String decision, boolean required, JsonNode expected) { }
    public static AgentEvalDataset load(Path path, ObjectMapper json) throws IOException {
        if (Files.size(path) > 2_000_000) throw new IllegalArgumentException("评测数据集过大");
        JsonNode root=json.readTree(Files.readString(path));
        fields(root,Set.of("datasetId","version","fixtureVersion","requiredCategories","cases"));
        String id=identifier(root,"datasetId"),version=identifier(root,"version"),fixture=identifier(root,"fixtureVersion");
        List<String> categories=strings(root.get("requiredCategories"));
        if(categories.isEmpty() || new HashSet<>(categories).size()!=categories.size()) throw new IllegalArgumentException("必测分类无效");
        var entries=root.get("cases");
        if(entries==null || !entries.isArray() || entries.isEmpty() || entries.size()>200) throw new IllegalArgumentException("评测用例数量无效");
        var cases=new ArrayList<Case>();var ids=new HashSet<String>();
        for(JsonNode entry:entries) {
            fields(entry,Set.of("caseId","category","actorFixture","scenario","input","parameters","decision","required","expected"));
            String caseId=identifier(entry,"caseId"),category=identifier(entry,"category");
            if(!ids.add(caseId)||!categories.contains(category)) throw new IllegalArgumentException("用例编号重复或分类未登记");
            if(!entry.path("required").isBoolean() || !entry.path("parameters").isObject()
                    || !entry.path("input").isTextual() || entry.path("input").asText().length()>4000) throw new IllegalArgumentException("用例契约不完整");
            JsonNode expected=entry.path("expected");
            AgentEvalScorer.validateExpectation(expected);
            cases.add(new Case(caseId,category,identifier(entry,"actorFixture"),identifier(entry,"scenario"),entry.get("input").asText(),
                    entry.get("parameters"),entry.path("decision").asText("NONE"),entry.get("required").asBoolean(),expected));
        }
        for(String category:categories) if(cases.stream().noneMatch(c->c.required()&&c.category().equals(category)))
            throw new IllegalArgumentException("必测分类没有必测用例");
        return new AgentEvalDataset(id,version,fixture,List.copyOf(categories),List.copyOf(cases));
    }
    static void fields(JsonNode value,Set<String> allowed) {
        if(value==null||!value.isObject())throw new IllegalArgumentException("评测契约必须为对象");
        value.fieldNames().forEachRemaining(key->{if(!allowed.contains(key))throw new IllegalArgumentException("未知评测字段："+key);});
    }
    static String identifier(JsonNode node,String field) {
        JsonNode value=node.get(field);
        if(value==null||!value.isTextual()||!value.asText().matches("[A-Za-z0-9_.-]{1,100}"))throw new IllegalArgumentException("无效评测标识："+field);
        return value.asText();
    }
    static List<String> strings(JsonNode value) {
        if(value==null||!value.isArray())throw new IllegalArgumentException("评测集合必须为数组");
        var result=new ArrayList<String>();
        for(var item:value) {
            if(!item.isTextual()||item.asText().isBlank())throw new IllegalArgumentException("评测集合包含无效值");
            result.add(item.asText());
        }
        return List.copyOf(result);
    }
}
