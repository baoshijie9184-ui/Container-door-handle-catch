package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.annotation.*;
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ruanzhu.doorhandle.contracts.agent.AgentWorkbenchApi;
import com.ruanzhu.doorhandle.common.time.LegacyClockEvidence;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import java.lang.reflect.RecordComponent;
import java.util.*;

/** Closed, versioned workbench vocabulary. The original map presence is explicit, never a free-form bag. */
final class WorkbenchProtocol {
    @JsonTypeInfo(use=JsonTypeInfo.Id.NAME,include=JsonTypeInfo.As.PROPERTY,property="type")
    @JsonSubTypes({
        @JsonSubTypes.Type(value=ExecutionV1.class,name="EXECUTION"),@JsonSubTypes.Type(value=ChildV1.class,name="CHILD"),
        @JsonSubTypes.Type(value=PlanV1.class,name="PLAN"),@JsonSubTypes.Type(value=QuestionV1.class,name="QUESTION"),
        @JsonSubTypes.Type(value=TasksV1.class,name="TASKS"),@JsonSubTypes.Type(value=ToolV1.class,name="TOOL"),
        @JsonSubTypes.Type(value=CheckpointV1.class,name="CHECKPOINT"),@JsonSubTypes.Type(value=SelectionV1.class,name="MODEL_SELECTION"),
        @JsonSubTypes.Type(value=TurnV1.class,name="TURN"),@JsonSubTypes.Type(value=ForkV1.class,name="FORK_SNAPSHOT"),
        @JsonSubTypes.Type(value=ArtifactV1.class,name="ARTIFACT"),@JsonSubTypes.Type(value=UsageV1.class,name="USAGE"),
        @JsonSubTypes.Type(value=ContextV1.class,name="CONTEXT"),@JsonSubTypes.Type(value=TimingV1.class,name="TOOL_TIMING")})
    sealed interface ItemData permits ExecutionV1,ChildV1,PlanV1,QuestionV1,TasksV1,ToolV1,CheckpointV1,SelectionV1,TurnV1,ForkV1,ArtifactV1,UsageV1,ContextV1,TimingV1 {}
    record ModelChangeV1(Long fromVersion,String fromModel,Long toVersion,String toModel,String previousRunId) {}
    record TaskV1(String title,String status,String evidenceCallId,String evidenceRunId) {}
    record ExecutionV1(String username,String role,String runId,String instance,Boolean yieldReady,String title,
            String logicalTaskId,Boolean planRequired,String modelId,Long modelConfigVersion,String modelDefault,
            String approvedPlan,String continuation,String result,List<ModelChangeV1> modelConfigurationHistory) implements ItemData {}
    record ChildV1(String parentId,String parentTaskId,String specialist,String question,String title,String username,
            String role,String logicalTaskId,String modelId,Long modelConfigVersion,String modelDefault,
            List<ModelChangeV1> modelConfigurationHistory,String runId,String instance,Boolean yieldReady,
            List<String> followups,String result,String continuation,String approvedPlan,Boolean planRequired) implements ItemData {}
    record PlanV1(String parentId,String runId,String logicalTaskId,String title,String text,List<TaskV1> tasks,String feedback) implements ItemData {}
    record QuestionV1(String parentId,String runId,String logicalTaskId,String text,String questionType,List<String> options,Object answer) implements ItemData {}
    record TasksV1(String parentId,String runId,String logicalTaskId,List<TaskV1> tasks) implements ItemData {}
    record ToolV1(String parentId,String runId,String callId,String logicalTaskId,String tool,String inputHash,
            Boolean readOnly,Boolean idempotentMetadata,String resultState) implements ItemData {}
    record CheckpointV1(String parentId,String phase,String runId,String logicalTaskId,Long sdkRevision) implements ItemData {}
    record SelectionV1(String modelId) implements ItemData {}
    record TurnV1(Long throughMessageId,List<AgentWorkbenchApi.Item> snapshot) implements ItemData {}
    record ForkV1(String text,String sourceSessionId,Long throughMessageId) implements ItemData {}
    record ArtifactV1(String parentId,String runId,String logicalTaskId,String fileId,String filename) implements ItemData {}
    record UsageV1(String parentId,String runId,Long systemTokens,Long messageTokens,Long toolsTokens,String modelId,
            String provider,String model,Integer attempt,String status,String basis,Long inputTokens,Long outputTokens,
            Long cachedTokens,Long durationMs,Long firstContentMs,String purpose) implements ItemData {}
    record ContextV1(String parentId,String runId,String phase,String basis,String agent,String modelRequestId,
            String purpose,String policyVersion,Long durationMs,Long beforeMessages,Long beforeChars,String result,
            Long afterMessages,Long afterChars) implements ItemData {}
    record TimingV1(String parentId,String runId,Long durationMs,String basis) implements ItemData {}
    record LegacyItemV1(String payloadJson,String createdAt,String updatedAt,String sourceUtcOffset) {}
    record ItemV1(int schemaVersion,ItemData data,Set<String> presentFields,LegacyItemV1 legacy) {
        ItemV1 {if(presentFields!=null)presentFields=Collections.unmodifiableSet(new TreeSet<>(presentFields));}
    }
    record CommandV1(String responseType) {}
    record CommandResultV1(String responseType,String responseJson) {}
    record AuditV1(String itemType,String status,String legacyId,String legacyCreatedAt,String sourceUtcOffset) {}
    record LogicalTaskV1(String parentItemId,String initialRunId,String role,String modelId,Long modelConfigVersion,String modelDefault,boolean importedCurrentSnapshot) {}

    static final List<String> TYPES=List.of("EXECUTION","CHILD","PLAN","QUESTION","TASKS","TOOL","CHECKPOINT","MODEL_SELECTION","TURN","FORK_SNAPSHOT","ARTIFACT","USAGE","CONTEXT","TOOL_TIMING");
    private static final Map<String,Class<? extends ItemData>> CLASSES=Map.ofEntries(
        Map.entry("EXECUTION",ExecutionV1.class),Map.entry("CHILD",ChildV1.class),Map.entry("PLAN",PlanV1.class),Map.entry("QUESTION",QuestionV1.class),
        Map.entry("TASKS",TasksV1.class),Map.entry("TOOL",ToolV1.class),Map.entry("CHECKPOINT",CheckpointV1.class),Map.entry("MODEL_SELECTION",SelectionV1.class),
        Map.entry("TURN",TurnV1.class),Map.entry("FORK_SNAPSHOT",ForkV1.class),Map.entry("ARTIFACT",ArtifactV1.class),Map.entry("USAGE",UsageV1.class),
        Map.entry("CONTEXT",ContextV1.class),Map.entry("TOOL_TIMING",TimingV1.class));
    private static final Set<String> EXECUTION_STATES=Set.of("RUNNING","READY","QUEUED","WAITING_PLAN","WAITING_INPUT","WAITING_CHILD","NEEDS_REVIEW","COMPLETED","CANCELLED","UNKNOWN");
    private final ObjectMapper json;
    private final Map<String,WorkflowProtocol<ItemV1>> protocols=new HashMap<>();

    WorkbenchProtocol(ObjectMapper mapper){
        json=mapper.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS)
            .enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).disable(SerializationFeature.INDENT_OUTPUT)
            .disable(MapperFeature.ALLOW_COERCION_OF_SCALARS).disable(DeserializationFeature.ACCEPT_FLOAT_AS_INT)
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES,DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
        var registry=WorkflowProtocols.defaults();
        for(String type:TYPES){
            var protocol=new WorkflowProtocol<>(kind(type),1,ItemV1.class,states(type),Set.of(),transitions(type),p->validate(type,p),false);
            protocols.put(type,protocol);registry=registry.with(protocol);
        }
        registry.with(new WorkflowProtocol<>(WorkflowKind.WORKBENCH_COMMAND,1,CommandV1.class,Set.of("COMPLETED"),Set.of("COMPLETED"),Map.of(),c->{responseType(c.responseType());},false));
    }
    static WorkflowKind kind(String type){if(!TYPES.contains(type))throw new IllegalArgumentException("Unknown workbench kind");return WorkflowKind.valueOf("WORKBENCH_"+type);}
    static String type(String kind){if(kind==null||!kind.startsWith("WORKBENCH_")||!TYPES.contains(kind.substring(10)))throw new IllegalStateException("Unknown persisted workbench kind");return kind.substring(10);}
    static boolean execution(String type){return type.equals("EXECUTION")||type.equals("CHILD");}
    static boolean closed(String type,String state){return execution(type)?Set.of("COMPLETED","CANCELLED").contains(state):switch(type){case "PLAN"->!state.equals("PENDING");case "QUESTION"->!state.equals("PENDING");case "TASKS","CHECKPOINT","MODEL_SELECTION"->false;case "TOOL"->state.equals("COMPLETED");default->true;};}
    static Set<String> states(String type){return switch(type){
        case "EXECUTION","CHILD","TURN"->EXECUTION_STATES;
        case "PLAN"->Set.of("PENDING","APPROVED","CHANGES_REQUESTED","CANCELLED");
        case "QUESTION"->Set.of("PENDING","ANSWERED","CANCELLED");
        case "TASKS","MODEL_SELECTION"->Set.of("ACTIVE");case "CHECKPOINT"->Set.of("SAVED");
        case "TOOL"->Set.of("UNKNOWN","COMPLETED");case "FORK_SNAPSHOT"->Set.of("REFERENCE_ONLY");
        case "USAGE"->Set.of("COMPLETED","FAILED","CANCELLED");
        case "CONTEXT"->Set.of("CONTEXT_STARTED","CONTEXT_COMPLETED","CONTEXT_FAILED","CONTEXT_CANCELLED");
        case "ARTIFACT","TOOL_TIMING"->Set.of("COMPLETED");default->throw new IllegalArgumentException("Unknown workbench kind");};}
    private static Map<String,Set<String>> transitions(String type){
        if(execution(type)){
            var result=new HashMap<String,Set<String>>();
            result.put("RUNNING",Set.of("RUNNING","WAITING_PLAN","WAITING_INPUT","WAITING_CHILD","NEEDS_REVIEW","COMPLETED","CANCELLED","QUEUED"));
            for(String waiting:List.of("WAITING_PLAN","WAITING_INPUT","WAITING_CHILD"))result.put(waiting,Set.of(waiting,"READY","QUEUED","CANCELLED","NEEDS_REVIEW"));
            result.put("READY",Set.of("READY","RUNNING","CANCELLED","NEEDS_REVIEW"));result.put("QUEUED",Set.of("QUEUED","RUNNING","CANCELLED","NEEDS_REVIEW"));
            result.put("NEEDS_REVIEW",Set.of("NEEDS_REVIEW","READY","QUEUED","CANCELLED"));result.put("UNKNOWN",Set.of("NEEDS_REVIEW","CANCELLED"));
            result.put("COMPLETED",type.equals("CHILD")?Set.of("COMPLETED","QUEUED"):Set.of("COMPLETED","RUNNING"));
            result.put("CANCELLED",type.equals("EXECUTION")?Set.of("RUNNING"):Set.of());return result;
        }
        return switch(type){case "PLAN"->Map.of("PENDING",Set.of("APPROVED","CHANGES_REQUESTED","CANCELLED"));case "QUESTION"->Map.of("PENDING",Set.of("ANSWERED","CANCELLED"));
            case "TASKS","MODEL_SELECTION"->Map.of("ACTIVE",Set.of("ACTIVE"));case "CHECKPOINT"->Map.of("SAVED",Set.of("SAVED"));case "TOOL"->Map.of("UNKNOWN",Set.of("COMPLETED"));default->Map.of();};
    }
    void transition(String type,String before,String after){protocols.get(type).requireTransition(before,after);}
    void state(String type,String state){if(!states(type).contains(state))throw new IllegalArgumentException("Unsupported workbench state");}
    ItemV1 payload(String type,Map<String,Object> values,LegacyItemV1 legacy){
        return payload(type,values,legacy,false);
    }
    ItemV1 payload(String type,Map<String,Object> values,LegacyItemV1 legacy,boolean unresolved){
        Class<? extends ItemData> bodyType=CLASSES.get(type);if(bodyType==null)throw new IllegalArgumentException("Unknown workbench kind");
        ObjectNode body=json.createObjectNode();body.put("type",type);for(var component:bodyType.getRecordComponents())body.putNull(component.getName());
        values.forEach((key,value)->body.set(key,json.valueToTree(value)));
        if(body.get("tasks") instanceof com.fasterxml.jackson.databind.node.ArrayNode tasks)for(var entry:tasks){
            if(!(entry instanceof ObjectNode task))throw new IllegalArgumentException("Invalid task entry");
            Set<String> names=Set.of("title","status","evidenceCallId","evidenceRunId");
            var keys=task.fieldNames();while(keys.hasNext())if(!names.contains(keys.next()))throw new IllegalArgumentException("Unknown task field");
            for(String key:names)if(!task.has(key))task.putNull(key);
        }
        ItemV1 result=new ItemV1(unresolved?2:1,json.convertValue(body,ItemData.class),Set.copyOf(values.keySet()),legacy);validate(type,result);return result;
    }
    ItemV1 read(String type,int version,String value){return read(type,version,value,null);}
    ItemV1 read(String type,int version,String value,LegacyClockEvidence clock){try{
        var payload=json.readValue(value,ItemV1.class);protocols.get(type).validatePayload(payload,version);
        if((payload.schemaVersion()==2)!=(clock!=null))throw new IllegalStateException("Workbench legacy clock provenance is incomplete");
        if(clock!=null){clock.requireWallTime("created_at",payload.legacy().createdAt());clock.requireWallTime("updated_at",payload.legacy().updatedAt());}
        return payload;
    }catch(Exception error){throw new IllegalStateException("工作台记录格式不正确",error);}}
    String write(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalArgumentException("工作台记录不能编码",error);}}
    Map<String,Object> data(ItemV1 payload){
        var tree=(ObjectNode)json.valueToTree(payload.data());var result=new LinkedHashMap<String,Object>();
        for(String key:new TreeSet<>(payload.presentFields()))result.put(key,json.convertValue(tree.get(key),Object.class));return result;
    }
    String commandType(Class<?> type){if(type==AgentWorkbenchApi.Item.class)return "ITEM";if(type==AgentWorkbenchService.ModelSelection.class)return "MODEL_SELECTION";throw new IllegalArgumentException("Unsupported workbench command result");}
    <T>T result(String body,String expected,Class<T> type){try{
        var result=json.readValue(body,CommandResultV1.class);responseType(result.responseType());if(!expected.equals(result.responseType()))throw new IllegalStateException("工作台回执类型冲突");
        var tree=json.readTree(result.responseJson());Set<String> required=expected.equals("ITEM")?Set.of("id","kind","status","revision","data"):Set.of("modelId","revision");
        if(tree==null||!tree.isObject()||!required.stream().allMatch(tree::has))throw new IllegalStateException("工作台回执字段不完整");
        // Historical Web JSON may omit the nullable updatedAt field; its exact bytes remain in responseJson.
        return json.readerFor(type).without(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES).readValue(result.responseJson());
    }catch(Exception error){throw new IllegalStateException("工作台命令回执不可读",error);}}
    private static void responseType(String type){if(!Set.of("ITEM","MODEL_SELECTION").contains(type))throw new IllegalArgumentException("Unsupported command response type");}
    private void validate(String type,ItemV1 payload){
        if(payload==null||!Set.of(1,2).contains(payload.schemaVersion())||payload.data()==null||!CLASSES.get(type).isInstance(payload.data())||payload.presentFields()==null)throw new IllegalArgumentException("Invalid workbench typed payload");
        Set<String> fields=new HashSet<>();for(RecordComponent component:payload.data().getClass().getRecordComponents())fields.add(component.getName());
        if(!fields.containsAll(payload.presentFields()))throw new IllegalArgumentException("Unknown workbench payload field");
        var values=data(payload);
        for(var bound:Map.ofEntries(Map.entry("parentId",64),Map.entry("parentTaskId",128),Map.entry("logicalTaskId",128),Map.entry("runId",128),Map.entry("instance",36),Map.entry("specialist",100),Map.entry("role",24),Map.entry("modelId",160),Map.entry("modelDefault",160),Map.entry("callId",160)).entrySet())
            if(values.get(bound.getKey()) instanceof String text&&text.codePointCount(0,text.length())>bound.getValue())throw new IllegalArgumentException("Workbench identity too long");
        for(String number:List.of("modelConfigVersion","durationMs","firstContentMs","inputTokens","outputTokens","cachedTokens","systemTokens","toolsTokens","messageTokens","beforeMessages","beforeChars","afterMessages","afterChars"))
            if(values.get(number) instanceof Number value&&value.longValue()<0)throw new IllegalArgumentException("Negative workbench measurement");
        if(payload.data() instanceof ChildV1 child&&child.followups()!=null&&(child.followups().size()>4||child.followups().stream().anyMatch(Objects::isNull)))throw new IllegalArgumentException("Invalid child followup queue");
        if(payload.data() instanceof QuestionV1 question){
            if(question.questionType()==null||!Set.of("TEXT","SINGLE","MULTIPLE").contains(question.questionType())||question.options()==null)throw new IllegalArgumentException("Invalid workbench question");
            if(question.answer()!=null&&!(question.answer() instanceof String)&&!(question.answer() instanceof List<?> list&&list.stream().allMatch(String.class::isInstance)))throw new IllegalArgumentException("Invalid workbench answer");
        }
        List<TaskV1> tasks=payload.data() instanceof PlanV1 plan?plan.tasks():payload.data() instanceof TasksV1 list?list.tasks():null;
        if(tasks!=null&&(tasks.size()>30||tasks.stream().anyMatch(task->task==null||task.title()==null||task.status()==null||!Set.of("pending","in_progress","completed","failed").contains(task.status()))))throw new IllegalArgumentException("Invalid task list");
        if(payload.data() instanceof TurnV1 turn){
            if(turn.throughMessageId()==null||turn.throughMessageId()<1||turn.snapshot()==null)throw new IllegalArgumentException("Invalid turn snapshot");
            for(var item:turn.snapshot()){if(item==null||!Set.of("PLAN","TASKS").contains(item.kind()))throw new IllegalArgumentException("Invalid snapshot kind");payload(item.kind(),item.data(),null);}
        }
        if(payload.legacy()!=null&&(payload.legacy().payloadJson()==null||payload.legacy().createdAt()==null||payload.legacy().updatedAt()==null||(payload.schemaVersion()==1)==(payload.legacy().sourceUtcOffset()==null)))throw new IllegalArgumentException("Incomplete legacy workbench evidence");
        if(payload.schemaVersion()==2&&payload.legacy()==null)throw new IllegalArgumentException("Unresolved workbench requires retained original wall clocks");
    }
}
