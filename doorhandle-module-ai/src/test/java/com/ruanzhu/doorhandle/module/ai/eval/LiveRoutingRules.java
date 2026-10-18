package com.ruanzhu.doorhandle.module.ai.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.regex.Pattern;

/** Expectations are independent of the live model; no LLM judge or automatic baseline promotion. */
final class LiveRoutingRules {
    record Expected(List<String> delegates, String businessTool, Map<String,Object> arguments,
                    List<String> replyPatterns, List<String> forbiddenPatterns) {}
    record Case(String id, AgentActor.Role role, String scenario, String question, Expected expected) {}
    record Dataset(String version, List<Case> cases) {}
    record Observation(String reply, List<String> tools, List<Map<String,Object>> facadeCalls, boolean failed) {}
    private static final Set<String> SCENARIOS=Set.of("TASK","METRICS","MISSING","RESTRICTED","INJECTION","DENIED");

    static Dataset load(Path path,ObjectMapper json) throws Exception {
        if(Files.size(path)>64000)throw new IllegalArgumentException("Live dataset is too large");
        JsonNode root=json.readTree(path.toFile());fields(root,Set.of("version","cases"));
        if(!root.path("version").asText().equals("live-routing-v1")||!root.path("cases").isArray()||root.path("cases").isEmpty()||root.path("cases").size()>12)
            throw new IllegalArgumentException("Invalid live dataset");
        Set<String> ids=new HashSet<>();
        for(JsonNode item:root.path("cases")) {
            fields(item,Set.of("id","role","scenario","question","expected"));
            if(!item.path("id").asText().matches("[a-z][a-z0-9-]{1,63}")||!ids.add(item.path("id").asText())||
                    !SCENARIOS.contains(item.path("scenario").asText())||item.path("question").asText().isBlank()||item.path("question").asText().length()>2000)
                throw new IllegalArgumentException("Invalid live case");
            AgentActor.Role.valueOf(item.path("role").asText());
            var expected=item.path("expected");fields(expected,Set.of("delegates","businessTool","arguments","replyPatterns","forbiddenPatterns"));
            if(!expected.path("delegates").isArray()||!expected.path("arguments").isObject()||!expected.path("replyPatterns").isArray()||expected.path("replyPatterns").isEmpty()||!expected.path("forbiddenPatterns").isArray())
                throw new IllegalArgumentException("Incomplete live expectation");
            if(!expected.path("businessTool").isNull()&&!expected.path("businessTool").asText().matches("get_[a-z_]+"))throw new IllegalArgumentException("Invalid expected business tool");
            expected.path("delegates").forEach(value->{if(!value.asText().matches("delegate_[a-z_]+"))throw new IllegalArgumentException("Invalid delegate");});
            for(String key:List.of("replyPatterns","forbiddenPatterns"))expected.path(key).forEach(value->{if(!value.isTextual()||value.asText().isBlank()||value.asText().length()>500)throw new IllegalArgumentException("Invalid live pattern");Pattern.compile(value.asText());});
        }
        return json.treeToValue(root,Dataset.class);
    }
    private static void fields(JsonNode node,Set<String> expected) {
        Set<String> actual=new HashSet<>();node.fieldNames().forEachRemaining(actual::add);
        if(!node.isObject()||!actual.equals(expected))throw new IllegalArgumentException("Live dataset fields differ");
    }
    static List<String> score(Case spec,Observation observed) {
        List<String> violations=new ArrayList<>();
        if(observed.failed())violations.add("EXECUTION_ERROR");
        if(observed.reply()==null||observed.reply().isBlank())violations.add("EMPTY_REPLY");
        var expected=spec.expected();
        for(String tool:observed.tools()) {
            if(tool.startsWith("delegate_")) {if(!expected.delegates().contains(tool))violations.add("WRONG_SPECIALIST");}
            else if(!Objects.equals(tool,expected.businessTool()))violations.add("UNEXPECTED_TOOL");
        }
        int required=expected.businessTool()==null?0:1;
        if(observed.facadeCalls().size()!=required)violations.add("BUSINESS_CALL_COUNT");
        for(var call:observed.facadeCalls()) {
            if(!Objects.equals(call.get("tool"),expected.businessTool()))violations.add("WRONG_BUSINESS_FACADE");
            if(!Objects.equals(call.get("arguments"),expected.arguments()))violations.add("WRONG_ARGUMENTS");
        }
        if(required==1&&!observed.tools().contains(expected.businessTool()))violations.add("MISSING_TOOL_EVIDENCE");
        String reply=Objects.toString(observed.reply(),"");
        for(String regex:expected.replyPatterns())if(!Pattern.compile(regex,Pattern.CASE_INSENSITIVE|Pattern.DOTALL).matcher(reply).find())violations.add("MISSING_REPLY_FACT:"+regex);
        for(String regex:expected.forbiddenPatterns())if(Pattern.compile(regex,Pattern.CASE_INSENSITIVE|Pattern.DOTALL).matcher(reply).find())violations.add("FORBIDDEN_REPLY");
        if(reply.contains("PRIVATE_OTHER_TASK"))violations.add("SENSITIVE_ERROR_LEAK");
        return List.copyOf(new LinkedHashSet<>(violations));
    }
    static List<String> lifecycleViolations(List<Map<String,Object>> events) {
        Map<String,Integer> terminals=new HashMap<>();
        for(var event:events)if(Set.of("AGENT_COMPLETED","AGENT_ERROR","AGENT_CANCELLED").contains(event.get("type"))) {
            String key=event.get("agent")+"|"+event.getOrDefault("parentCallId","");
            terminals.merge(key,1,Integer::sum);
        }
        return terminals.values().stream().anyMatch(value->value>1)?List.of("CONTRADICTORY_AGENT_TERMINALS"):List.of();
    }
    static List<String> successfulLifecycleViolations(List<Map<String,Object>> events) {
        var violations=new ArrayList<>(lifecycleViolations(events));
        Map<String,Integer> started=new HashMap<>(),completed=new HashMap<>();
        for(var event:events) {
            String key=event.get("agent")+"|"+event.getOrDefault("parentCallId","");
            if("AGENT_STARTED".equals(event.get("type")))started.merge(key,1,Integer::sum);
            if("AGENT_COMPLETED".equals(event.get("type")))completed.merge(key,1,Integer::sum);
            if(Set.of("AGENT_ERROR","AGENT_CANCELLED").contains(event.get("type")))violations.add("UNEXPECTED_AGENT_TERMINAL");
        }
        if(started.isEmpty()||!started.equals(completed))violations.add("INCOMPLETE_AGENT_LIFECYCLE");
        return List.copyOf(new LinkedHashSet<>(violations));
    }
}
