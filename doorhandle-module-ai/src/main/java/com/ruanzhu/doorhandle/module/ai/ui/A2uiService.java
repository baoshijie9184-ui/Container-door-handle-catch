package com.ruanzhu.doorhandle.module.ai.ui;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.card.AgentCardService;
import org.springframework.stereotype.Service;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Server-owned A2UI catalog. Values always come from the permission-checked card facade. */
@Service
@org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(prefix="agentscope.ai",name="enabled",havingValue="true")
public class A2uiService {
    public static final String VERSION="v0.9.1", CATALOG="urn:doorhandle:a2ui:workspace:1", EVENT="doorhandle.a2ui.v1";
    private final AgentCardService cards;
    private final AgentChatSessionApi sessions;
    private final ObjectMapper json;
    public A2uiService(AgentCardService cards,AgentChatSessionApi sessions,ObjectMapper json){this.cards=cards;this.sessions=sessions;this.json=json;}
    public record Query(String sessionId,List<AgentCards.Reference> cards) {}
    public record Action(String name,String surfaceId,String sourceComponentId,String timestamp,Map<String,Object> context) {}
    public record Interaction(String sessionId,List<AgentCards.Reference> cards,Action action) {}
    private void validate(AgentActor actor,Query query){
        if(query==null||query.sessionId()==null||!query.sessionId().matches("[A-Za-z0-9_.-]{1,128}")||query.cards()==null||query.cards().isEmpty()||query.cards().size()>8||query.cards().stream().anyMatch(Objects::isNull))throw new IllegalArgumentException("动态界面请求无效");
        sessions.assertOwned(actor,query.sessionId());
    }
    public Map<String,Object> resolve(AgentActor actor,Query query){
        validate(actor,query);
        var views=cards.resolve(actor,query.cards());
        var messages=new ArrayList<Map<String,Object>>();
        for(int index=0;index<views.size();index++) messages.addAll(project(actor,query,index,views.get(index)));
        return Map.of("version",VERSION,"catalogId",CATALOG,"messages",messages);
    }
    public String followUp(AgentActor actor,Interaction input){
        if(input==null||input.action()==null)throw new IllegalArgumentException("缺少交互事件");
        var query=new Query(input.sessionId(),input.cards());validate(actor,query);
        var action=input.action();var context=action.context();
        if(!"FOLLOW_UP".equals(action.name())||context==null||!context.keySet().equals(Set.of("referenceIndex","question"))||!(context.get("referenceIndex") instanceof Number number)||number.doubleValue()!=number.intValue())throw new IllegalArgumentException("交互事件未登记");
        int index=number.intValue();
        if(index<0||index>=query.cards().size()||!surfaceId(actor,query,index).equals(action.surfaceId())||!("followup-"+index).equals(action.sourceComponentId()))throw new IllegalArgumentException("交互来源不匹配");
        try{java.time.Instant.parse(action.timestamp());}catch(Exception error){throw new IllegalArgumentException("交互时间无效");}
        if(!(context.get("question") instanceof String question)||question.isBlank()||question.length()>500)throw new IllegalArgumentException("请输入 1 到 500 字的后续问题");
        var view=cards.resolve(actor,List.of(query.cards().get(index))).get(0);
        if(!"OK".equals(view.status()))throw new org.springframework.security.access.AccessDeniedException("请先刷新并核对结果访问范围");
        var reference=query.cards().get(index);
        // Text becomes a new user request through the existing queue/AG-UI admission path.
        // It is never treated as a server instruction, tool call, approval, or model state.
        return "围绕刚才查询的"+title(reference.type())+"（资源编号："+String.join("、",reference.ids())+
                (reference.days()==null?"":"；统计天数："+reference.days())+"），继续处理以下用户问题：\n"+question;
    }
    public List<Map<String,Object>> project(AgentActor actor,Query query,int index,AgentCards.View view){
        String surface=surfaceId(actor,query,index),prefix="result-"+index;
        var nodes=new ArrayList<Map<String,Object>>();var children=new ArrayList<String>();var data=new LinkedHashMap<String,Object>();
        nodes.add(node("heading","Text","text",title(view.type()),"variant","h3"));children.add("heading");
        nodes.add(node("scope","Status","label","SINGLE_ENTERPRISE".equals(view.scope())?"企业授权范围":"本人或已分配范围","tone","info"));children.add("scope");
        if(!"OK".equals(view.status())) {nodes.add(node("unavailable","Status","label",view.message()==null?"数据暂不可用":view.message(),"tone","warning"));children.add("unavailable");}
        else if("METRICS".equals(view.type())) {
            var metrics=new ArrayList<String>();var points=new ArrayList<Map<String,Object>>();
            var labels=Map.of("taskCount","检测任务","imageCount","图片数量","processedImageCount","已处理图片","defectCount","缺陷目标");
            for(String key:List.of("taskCount","imageCount","processedImageCount","defectCount")){
                if(!(view.metrics().get(key) instanceof Number value))continue;
                String component="metric-"+key;metrics.add(component);data.put(key,value);
                nodes.add(node(component,"Metric","label",labels.get(key),"value",Map.of("path","/"+key)));
                points.add(Map.of("label",labels.get(key),"value",value));
            }
            nodes.add(node("metrics","Row","children",metrics));children.add("metrics");
            data.put("points",points);nodes.add(node("chart","BarChart","title","本次统计指标","points",Map.of("path","/points")));children.add("chart");
            if(view.metrics().get("processedImageCount") instanceof Number done&&view.metrics().get("imageCount") instanceof Number total&&total.doubleValue()>0){nodes.add(node("processed","Progress","label","图片处理情况","value",done,"total",total));children.add("processed");}
        } else {
            var columns=columns(view.type());var rows=new ArrayList<Map<String,Object>>();var points=new ArrayList<Map<String,Object>>();
            for(Object item:view.items()) {
                com.fasterxml.jackson.databind.JsonNode value=json.valueToTree(item);
                if("MODEL_OPERATIONS".equals(view.type()))value=value.path("model");
                var row=new LinkedHashMap<String,Object>();
                for(var column:columns){var field=value.path(column.get("key"));row.put(column.get("key"),field.isValueNode()&&!field.isNull()?field.asText():"未提供");}
                rows.add(row);
                if("TASKS".equals(view.type())&&value.path("defectCount").isNumber()&&value.path("defectCount").asDouble()>=0)points.add(Map.of("label",value.path("taskId").asText("任务"),"value",value.path("defectCount").numberValue()));
            }
            data.put("rows",rows);nodes.add(node("table","DataTable","columns",columns,"rows",Map.of("path","/rows")));
            if(!points.isEmpty()) {data.put("points",points);nodes.add(node("chart","BarChart","title","本次任务缺陷目标数","points",Map.of("path","/points")));nodes.add(node("tabs","Tabs","tabs",List.of(Map.of("title","记录明细","child","table"),Map.of("title","缺陷分布","child","chart"))));children.add("tabs");}
            else children.add("table");
        }
        nodes.add(node("note","Text","text",Objects.toString(view.message(),"仅展示当前授权数据"),"variant","caption"));children.add("note");
        nodes.add(node("updated","Text","text","读取时间 "+Objects.toString(view.updatedAt(),"未提供")+"（服务器时间）","variant","caption"));children.add("updated");
        nodes.add(node("refresh-"+index,"Button","label","刷新数据","action",Map.of("event",Map.of("name","REFRESH","context",Map.of("referenceIndex",index)))));children.add("refresh-"+index);
        if("OK".equals(view.status())){
            data.put("followup","");nodes.add(node("question","TextField","label","继续分析","value",Map.of("path","/followup"),"placeholder","例如：优先复核哪些任务","required",true));
            nodes.add(node("followup-"+index,"Button","label","发送给助手","action",Map.of("event",Map.of("name","FOLLOW_UP","context",Map.of("referenceIndex",index,"question",Map.of("path","/followup"))))));
            nodes.add(node("form","Form","children",List.of("question","followup-"+index)));children.add("form");
        }
        nodes.add(node("root","Column","children",children));
        return List.of(envelope("createSurface",Map.of("surfaceId",surface,"catalogId",CATALOG)),envelope("updateComponents",Map.of("surfaceId",surface,"components",nodes)),envelope("updateDataModel",Map.of("surfaceId",surface,"path","/","value",data)));
    }
    private String surfaceId(AgentActor actor,Query query,int index){
        try{var bytes=json.writeValueAsBytes(List.of(actor.userId(),query.sessionId(),query.cards()));return "surface-"+HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)).substring(0,20)+"-"+index;}catch(Exception error){throw new IllegalArgumentException("界面引用无效");}
    }
    private static Map<String,Object> envelope(String operation,Map<String,Object> value){return Map.of("version",VERSION,operation,value);}
    private static Map<String,Object> node(String id,String type,Object... fields){var value=new LinkedHashMap<String,Object>();value.put("id",id);value.put("component",type);for(int i=0;i<fields.length;i+=2)value.put((String)fields[i],fields[i+1]);return value;}
    private static String title(String type){return switch(type){case "METRICS"->"工作统计";case "TASKS"->"检测与质检任务";case "REPORTS"->"质检报告";case "DEVICES"->"设备资料";case "DEVICE_ALERTS"->"设备告警";case "MODELS","MODEL_OPERATIONS"->"检测模型";default->"业务结果";};}
    private static List<Map<String,String>> columns(String type){
        var values=switch(type){case "TASKS"->new String[]{"taskId","任务编号","deviceName","设备","status","执行状态","totalImages","图片","processedImages","已处理","defectCount","缺陷目标"};case "REPORTS"->new String[]{"reportId","报告编号","title","标题","status","状态"};case "DEVICES"->new String[]{"deviceId","设备编号","deviceCode","设备编码","status","状态","onlineStatus","连接状态"};case "DEVICE_ALERTS"->new String[]{"alertId","告警编号","deviceCode","设备编码","level","级别","status","状态"};default->new String[]{"modelId","模型编号","name","模型名称","status","状态"};};
        var result=new ArrayList<Map<String,String>>();for(int i=0;i<values.length;i+=2)result.add(Map.of("key",values[i],"label",values[i+1]));return result;
    }
}
