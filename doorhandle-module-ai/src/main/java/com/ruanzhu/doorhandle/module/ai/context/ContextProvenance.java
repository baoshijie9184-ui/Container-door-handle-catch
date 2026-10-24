package com.ruanzhu.doorhandle.module.ai.context;

import com.fasterxml.jackson.databind.*;
import com.ruanzhu.doorhandle.contracts.agent.AgentBusinessFilesApi;
import com.ruanzhu.doorhandle.contracts.agent.AgentContextDataApi.Source;
import io.agentscope.core.message.*;
import java.util.*;
import java.util.regex.Pattern;

/** Tool identity comes from the actual SDK call, never from a JSON field in fetched text. */
final class ContextProvenance {
    private static final Pattern FILE=Pattern.compile("@file:([a-f0-9-]{36})");
    private static final Pattern SOURCE=Pattern.compile("src-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}");
    private static final Set<String> BUSINESS=Set.of("get_task_detail","get_my_detection_tasks","search_detection_tasks","get_my_quality_records","get_quality_records","get_quality_report","create_report_draft","edit_report_draft","list_quality_reports","list_devices","get_device_alert","list_device_alerts","list_models","get_model_operations");
    private final ObjectMapper json;
    ContextProvenance(ObjectMapper json){this.json=json;}
    List<Source> collect(List<Msg> messages){
        var result=new LinkedHashSet<Source>();
        for(var message:messages)for(var block:message.getContent()){
            lexical(result,text(block));
            if(block instanceof ToolUseBlock call)inputs(result,call.getName(),call.getInput());
            // Business schemas are interpreted once at recordResult, before any offload replaces
            // the result with a plain-text excerpt. Later compaction uses durable origin receipts.
        }
        return List.copyOf(result);
    }
    List<Source> tool(String tool,Map<String,Object> input,ToolResultBlock output){
        if(output.getState()!=null&&Set.of("ERROR","FAILED").contains(output.getState().name()))return List.of();
        var result=new LinkedHashSet<Source>();inputs(result,tool,input);String text=text(output);lexical(result,text);
        boolean proposal=Set.of("propose_quality_assignment","propose_detection_retry","propose_detection_creation").contains(tool);
        boolean child=tool.equals("start_background_task")||tool.equals("get_background_task")||tool.startsWith("delegate_");
        if(!BUSINESS.contains(tool)&&!proposal&&!child&&!Set.of("list_workspace_files","create_artifact").contains(tool))return List.copyOf(result);
        try{
            var root=json.readTree(text);if(root==null||!root.isObject())throw new IllegalStateException("工具来源结构缺失");
            if(child){
                if(!"CHILD".equals(root.path("kind").asText())||!root.path("id").isTextual())throw new IllegalStateException("专业任务来源缺失");
                add(result,"CHILD",root,"id");
            }else if(proposal){
                var action=root.path("action");String expected=switch(tool){case "propose_quality_assignment"->"ASSIGN_QUALITY_TASK";case "propose_detection_retry"->"RETRY_DETECTION";default->"CREATE_DETECTION";};
                if(!action.isObject()||!expected.equals(action.path("operation").asText()))throw new IllegalStateException("提议来源与实际工具不一致");
                if(expected.equals("ASSIGN_QUALITY_TASK"))add(result,"TASK",action.path("command"),"taskId");
                else if(expected.equals("RETRY_DETECTION"))add(result,"TASK",action.path("retry"),"taskId");
                else{
                    var images=action.path("creation").path("images");if(!images.isArray()||images.isEmpty())throw new IllegalStateException("检测提议缺少图片来源");
                    for(var image:images){var origin=image.path("origin");
                        if(origin.isObject()){
                            String task=required(origin,"taskId"),file=required(origin,"fileId"),version=required(origin,"resourceVersion");
                            if(!task.matches("[A-Za-z0-9_-]{1,128}")||!file.matches("[a-f0-9-]{36}")||version.length()>256)throw new IllegalStateException("业务原图来源格式无效");
                            result.add(new Source("BUSINESS_IMAGE","DETECTION/"+task+"/"+file,version));
                        }else add(result,"FILE",image,"fileId");
                    }
                }
            }else if(tool.equals("list_workspace_files")){
                if(!root.path("files").isArray()||!root.path("businessFiles").isArray())throw new IllegalStateException("文件目录来源缺失");
                for(var file:root.path("files"))result.add(new Source("FILE",required(file,"id"),required(file,"sha256")));
                for(var file:root.path("businessFiles")){
                    var resource=new AgentBusinessFilesApi.Resource(required(file,"kind"),required(file,"resourceId"),required(file,"fileId"),file.path("name").asText(""),file.path("contentType").asText(""),file.path("previewPath").asText(""));
                    result.add(new Source("BUSINESS_FILE",resource.kind()+"/"+resource.resourceId()+"/"+resource.fileId(),AgentBusinessFilesApi.contextVersion(resource)));
                }
            }else if(tool.equals("create_artifact"))result.add(new Source("FILE",required(root,"id"),required(root,"sha256")));
            else{
                if(!"OK".equals(root.path("status").asText())||!tool.equals(root.path("source").asText()))throw new IllegalStateException("业务结果来源与实际工具不一致");
                var data=root.path("data");
                switch(tool){
                    case "get_task_detail"->add(result,"TASK",data,"taskId");
                    case "get_my_detection_tasks","search_detection_tasks","get_my_quality_records","get_quality_records"->{for(var item:data.path("items"))add(result,"TASK",item,"taskId");}
                    case "get_quality_report","create_report_draft","edit_report_draft"->add(result,"REPORT",data.path("report"),"reportId");
                    case "list_quality_reports"->{for(var item:data.path("records"))add(result,"REPORT",item,"reportId");}
                    case "list_devices"->{for(var item:data)add(result,"DEVICE",item,"deviceId");}
                    case "get_device_alert"->add(result,"ALERT",data,"alertId");
                    case "list_device_alerts"->{for(var item:data.path("items"))add(result,"ALERT",item,"alertId");}
                    case "list_models"->{for(var item:data)add(result,"MODEL",item,"modelId");}
                    case "get_model_operations"->add(result,"MODEL",data.path("model"),"modelId");
                    default->throw new IllegalStateException("业务工具来源未登记");
                }
            }
        }catch(com.fasterxml.jackson.core.JsonProcessingException invalid){throw new IllegalStateException("受控工具来源不可解析",invalid);}
        if(result.size()>2000)throw new IllegalStateException("工具来源超过本轮上限，未保存残缺来源");return List.copyOf(result);
    }
    private static void inputs(Set<Source> result,String tool,Map<String,Object> input){if(input!=null&&Set.of("read_workspace_file","read_context_file").contains(tool)&&input.get("fileId") instanceof String id)result.add(new Source("FILE",id,""));}
    private static void lexical(Set<Source> result,String text){var files=FILE.matcher(text);while(files.find()){result.add(new Source("FILE",files.group(1),""));if(result.size()>2000)throw new IllegalStateException("上下文来源超过本轮上限");}var sources=SOURCE.matcher(text);while(sources.find()){result.add(new Source("RESEARCH",sources.group(),""));if(result.size()>2000)throw new IllegalStateException("上下文来源超过本轮上限");}}
    private static String required(JsonNode value,String field){if(!value.path(field).isTextual()||value.path(field).asText().isBlank())throw new IllegalStateException("工具来源编号缺失");return value.path(field).asText();}
    private static void add(Set<Source> result,String kind,JsonNode value,String field){if(!value.path(field).isValueNode()||value.path(field).asText().isBlank())throw new IllegalStateException("工具来源编号缺失");result.add(new Source(kind,value.path(field).asText(),""));}
    static String text(ContentBlock block){if(block instanceof TextBlock text)return Objects.toString(text.getText(),"");if(block instanceof ToolUseBlock call)return Objects.toString(call.getContent(),"");if(block instanceof ToolResultBlock result){var text=new StringBuilder();for(var item:result.getOutput())text.append(text(item));return text.toString();}return "";}
}
