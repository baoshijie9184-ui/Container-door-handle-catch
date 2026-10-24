package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.regex.Pattern;

@Service
@ConditionalOnProperty(prefix="agentscope.context-store",name="enabled",havingValue="true")
public class AgentContextDataBridge implements AgentContextDataApi {
    private static final Pattern FILE=Pattern.compile("@file:([a-f0-9-]{36})");
    private final AgentWorkspaceService workspace;private final JdbcTemplate jdbc;private final ObjectMapper json;
    private final ObjectProvider<DetectionAgentReadApi> tasks;private final ObjectProvider<QualityReportAgentApi> reports;
    private final ObjectProvider<ResourceAgentReadApi> resources;private final ObjectProvider<ModelAgentReadApi> models;
    @org.springframework.beans.factory.annotation.Autowired private ObjectProvider<AgentBusinessFilesApi> businessFiles;
    public AgentContextDataBridge(AgentWorkspaceService workspace,JdbcTemplate jdbc,ObjectMapper json,ObjectProvider<DetectionAgentReadApi> tasks,
            ObjectProvider<QualityReportAgentApi> reports,ObjectProvider<ResourceAgentReadApi> resources,ObjectProvider<ModelAgentReadApi> models){
        this.workspace=workspace;this.jdbc=jdbc;this.json=json;this.tasks=tasks;this.reports=reports;this.resources=resources;this.models=models;
    }
    @Override public History history(AgentActor actor,String session,long after,long through,int limit){
        workspace.assertOwned(actor,session);if(after<0||through<0||limit<1||limit>200)throw new IllegalArgumentException("上下文历史范围无效");
        long end=through==0?jdbc.queryForObject("SELECT COALESCE(MAX(id),0) FROM chat_message WHERE session_id=?",Long.class,session):through;
        var rows=jdbc.queryForList("SELECT id,role,message_type,content FROM chat_message WHERE session_id=? AND id>? AND id<=? ORDER BY id LIMIT ?",session,after,end,limit+1);
        boolean more=rows.size()>limit;var result=new ArrayList<Message>();
        for(var row:rows.subList(0,Math.min(rows.size(),limit))){
            String role=(String)row.get("role");if(!Set.of("user","assistant").contains(role))throw new IllegalStateException("历史中存在不支持的消息类型，不能跳过后压缩");
            String text=Objects.toString(row.get("content"),"");var sources=new ArrayList<Source>();
            if(AgentCards.MESSAGE_TYPE.equals(row.get("message_type")))try{
                var envelope=json.readValue(text,AgentCards.Envelope.class);text=envelope.text();
                for(var ref:envelope.cards())for(String id:ref.ids()){
                    String kind=switch(ref.type()){case "TASKS"->"TASK";case "REPORTS"->"REPORT";case "DEVICES"->"DEVICE";case "DEVICE_ALERTS"->"ALERT";case "MODELS","MODEL_OPERATIONS"->"MODEL";default->null;};
                    if(kind!=null)sources.add(new Source(kind,id,""));
                }
            }catch(Exception invalid){throw new IllegalStateException("历史卡片不可读取，不能省略后继续");}
            var matcher=FILE.matcher(text);while(matcher.find()){
                String id=matcher.group(1);sources.add(new Source("FILE",id,""));
            }
            try{authorize(actor,session,sources);for(int i=0;i<sources.size();i++){var ref=sources.get(i);if(ref.kind().equals("FILE"))sources.set(i,new Source("FILE",ref.resourceId(),workspace.requireFile(actor,session,ref.resourceId()).sha256()));}}catch(SecurityException|com.ruanzhu.doorhandle.common.BusinessException|org.springframework.web.server.ResponseStatusException revoked){
                text="[历史资料的访问范围已变化，此段原文保留在聊天记录，本轮不将其作为上下文依据]";sources.clear();
            }
            result.add(new Message(((Number)row.get("id")).longValue(),role,text,List.copyOf(sources)));
        }
        return new History(end,List.copyOf(result),more);
    }
    @Override public String historyDigest(AgentActor actor,String session,long through){
        workspace.assertOwned(actor,session);if(through<0)throw new IllegalArgumentException("历史切点无效");
        try{
            var digest=MessageDigest.getInstance("SHA-256");
            jdbc.query("SELECT id,role,message_type,content FROM chat_message WHERE session_id=? AND id<=? ORDER BY id",rs->{
                for(String value:List.of(Long.toString(rs.getLong("id")),Objects.toString(rs.getString("role"),""),Objects.toString(rs.getString("message_type"),""),Objects.toString(rs.getString("content"),""))){
                    byte[] bytes=value.getBytes(StandardCharsets.UTF_8);digest.update(java.nio.ByteBuffer.allocate(4).putInt(bytes.length).array());digest.update(bytes);
                }
            },session,through);
            return HexFormat.of().formatHex(digest.digest());
        }catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}
    }
    @Override public void authorize(AgentActor actor,String session,List<Source> sources){
        workspace.assertOwned(actor,session);if(sources==null||sources.size()>2000)throw new IllegalArgumentException("上下文来源数量无效");
        for(var source:sources)switch(source.kind()){
            case "ROLE"->{if(!actor.role().name().equals(source.resourceId()))throw new SecurityException("上下文角色已变化");}
            case "FILE"->{var file=workspace.requireFile(actor,session,source.resourceId());if(source.version()!=null&&!source.version().isEmpty()&&!source.version().equals(file.sha256()))throw new SecurityException("上下文文件已变化");workspace.bytesForContextValidation(actor,session,file.id());}
            case "BUSINESS_FILE","BUSINESS_IMAGE"->authorizeBusinessFile(actor,session,source);
            case "TASK"->tasks.getObject().task(actor,source.resourceId());
            case "REPORT"->reports.getObject().get(actor,source.resourceId());
            case "DEVICE"->resources.getObject().device(actor,Long.parseLong(source.resourceId()));
            case "ALERT"->resources.getObject().alert(actor,Long.parseLong(source.resourceId()));
            case "MODEL"->models.getObject().operations(actor,Integer.parseInt(source.resourceId()));
            default->throw new SecurityException("上下文来源类型未登记");
        }
    }
    private void authorizeBusinessFile(AgentActor actor,String session,Source source){
        String[] parts=source.resourceId().split("/",-1);
        if(parts.length!=3||!Set.of("DETECTION","REPORT").contains(parts[0])||!parts[1].matches("[A-Za-z0-9_-]{1,128}")||!parts[2].matches("[A-Za-z0-9_-]{1,64}")||source.version()==null||source.version().isBlank()||source.version().length()>256)throw new SecurityException("业务文件上下文引用无效");
        workspace.requireBusinessReference(actor,session,parts[0],parts[1]);
        if(businessFiles==null||businessFiles.getIfAvailable()==null)throw new IllegalStateException("业务文件来源核对服务不可用");
        if(source.kind().equals("BUSINESS_IMAGE")){
            if(!parts[0].equals("DETECTION")||!parts[2].matches("[a-f0-9-]{36}"))throw new SecurityException("上下文只允许已关联的业务原图");
            try{businessFiles.getObject().assertOriginal(actor,parts[1],parts[2],source.version());}catch(DetectionExecutionApi.ResourceChanged changed){throw new SecurityException("业务原图快照已变化",changed);}
        }else{
            var matching=businessFiles.getObject().list(actor,parts[0],parts[1]).stream().filter(file->file.kind().equals(parts[0])&&file.resourceId().equals(parts[1])&&file.fileId().equals(parts[2])).toList();
            if(matching.size()!=1||!source.version().equals(AgentBusinessFilesApi.contextVersion(matching.get(0))))throw new SecurityException("业务文件目录或授权已变化");
        }
    }
    @Override public WorkbenchSessionApi.File saveContextFile(AgentActor actor,String session,String request,String text){
        workspace.assertOwned(actor,session);if(text==null||text.getBytes(StandardCharsets.UTF_8).length>2097152)throw new IllegalArgumentException("上下文文件超出 2 MiB 上限");
        return workspace.upload(actor,session,request,"context-"+request+".md",text.getBytes(StandardCharsets.UTF_8),"context");
    }
    @Override public List<Source> pin(AgentActor actor,String session,List<Source> sources){authorize(actor,session,sources);return sources.stream().map(source->source.kind().equals("FILE")?new Source("FILE",source.resourceId(),workspace.requireFile(actor,session,source.resourceId()).sha256()):source).toList();}
    @Override public Slice readContextFile(AgentActor actor,String session,String id,String expected,int offset,int limit){
        workspace.assertOwned(actor,session);var file=workspace.requireFile(actor,session,id);
        if(!"context".equals(file.folder())||!file.sha256().equals(expected)||offset<0||limit<1||limit>16000||file.bytes()>2097152)throw new SecurityException("上下文文件编号、摘要或读取范围无效");
        String text=new String(workspace.bytes(actor,session,id),StandardCharsets.UTF_8);int count=text.codePointCount(0,text.length());if(offset>count)throw new IllegalArgumentException("读取位置超出文件范围");
        int end=(int)Math.min(count,(long)offset+limit),beginChar=text.offsetByCodePoints(0,offset),endChar=text.offsetByCodePoints(0,end);
        return new Slice(text.substring(beginChar,endChar),offset,end,end==count,file.sha256());
    }
    @Override public List<ForkMessage> forkMessages(AgentActor actor,String source,String target,long through){
        workspace.assertOwned(actor,source);workspace.assertOwned(actor,target);
        Long proof=jdbc.queryForObject("SELECT COUNT(*) FROM agent_session_fork WHERE user_id=? AND source_session_id=? AND fork_session_id=? AND through_message_id=?",Long.class,actor.userId(),source,target,through);if(proof!=1)throw new SecurityException("分支来源或切点不匹配");
        var before=jdbc.queryForList("SELECT id,role,message_type,content FROM chat_message WHERE session_id=? AND id<=? ORDER BY id LIMIT 5001",source,through);
        if(before.size()>5000)throw new IllegalStateException("分支历史映射超出本次上限");
        var after=jdbc.queryForList("SELECT id,role,message_type,content FROM chat_message WHERE session_id=? ORDER BY id LIMIT ?",target,before.size());if(before.size()!=after.size())throw new IllegalStateException("分支历史前缀不完整");
        var result=new ArrayList<ForkMessage>();for(int i=0;i<before.size();i++){
            var a=before.get(i);var b=after.get(i);String text=Objects.toString(a.get("content"),"");
            if(AgentCards.MESSAGE_TYPE.equals(a.get("message_type")))try{text=json.readValue(text,AgentCards.Envelope.class).text();}catch(Exception invalid){throw new IllegalStateException("分支卡片历史不可读取");}
            if(!Objects.equals(a.get("role"),b.get("role"))||!text.equals(Objects.toString(b.get("content"),"")))throw new IllegalStateException("分支历史内容不匹配");
            result.add(new ForkMessage(((Number)a.get("id")).longValue(),((Number)b.get("id")).longValue()));
        }return List.copyOf(result);
    }
}
