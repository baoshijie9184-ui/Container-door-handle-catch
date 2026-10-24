package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.*;
import com.ruanzhu.doorhandle.contracts.agent.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.function.Supplier;

/** Short transactions only. SDK snapshots are private and never part of an HTTP projection. */
@Repository
@ConditionalOnProperty(prefix="agentscope.workbench",name="enabled",havingValue="true")
public class WorkbenchStore {
    record Row(String id,long user,String session,String kind,String status,long revision,Map<String,Object> data,String updated) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ObjectMapper json;
    public WorkbenchStore(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json){
        this.jdbc=jdbc;this.json=json.copy().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).disable(SerializationFeature.INDENT_OUTPUT);tx=new TransactionTemplate(manager);tx.setTimeout(5);
    }
    /** Access through a method so Spring repository proxies delegate to the initialized target. */
    public JdbcTemplate jdbc(){return jdbc;}
    public <T>T locked(long user,Supplier<T> work){return tx.execute(status->{
        jdbc.update("INSERT INTO agent_workbench_owner(user_id) VALUES(?) ON DUPLICATE KEY UPDATE user_id=VALUES(user_id)",user);
        jdbc.queryForObject("SELECT user_id FROM agent_workbench_owner WHERE user_id=? FOR UPDATE",Long.class,user);return work.get();
    });}
    String encode(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalArgumentException("工作区内容格式无效");}}
    Map<String,Object> decode(String value){try{return json.readValue(value,new TypeReference<LinkedHashMap<String,Object>>(){});}catch(Exception error){throw new IllegalStateException("工作区状态无法读取");}}
    static String hash(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
    static String stable(long user,String session,String kind){return UUID.nameUUIDFromBytes((user+":"+session+":"+kind).getBytes(StandardCharsets.UTF_8)).toString();}
    Row find(long user,String session,String id){return jdbc.query("SELECT * FROM agent_workbench_item WHERE user_id=? AND session_id=? AND item_id=?",(rs,n)->new Row(rs.getString("item_id"),rs.getLong("user_id"),rs.getString("session_id"),rs.getString("kind"),rs.getString("status"),rs.getLong("revision"),decode(rs.getString("payload")),rs.getString("updated_at")),user,session,id).stream().findFirst().orElse(null);}
    Row require(long user,String session,String id){var row=find(user,session,id);if(row==null)throw fail(404,"工作项不存在或无权限");return row;}
    List<Row> list(long user,String session){return jdbc.query("SELECT * FROM agent_workbench_item WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT 200",(rs,n)->new Row(rs.getString("item_id"),rs.getLong("user_id"),rs.getString("session_id"),rs.getString("kind"),rs.getString("status"),rs.getLong("revision"),decode(rs.getString("payload")),rs.getString("updated_at")),user,session);}
    List<Row> publicRows(long user,String session){return jdbc.query("SELECT * FROM agent_workbench_item WHERE user_id=? AND session_id=? AND kind NOT IN ('TOOL','CHECKPOINT','TURN','MODEL_SELECTION') ORDER BY id DESC LIMIT 180",(rs,n)->new Row(rs.getString("item_id"),rs.getLong("user_id"),rs.getString("session_id"),rs.getString("kind"),rs.getString("status"),rs.getLong("revision"),decode(rs.getString("payload")),rs.getString("updated_at")),user,session);}
    List<Row> childRows(long user,String session,String parent,Object task){return jdbc.query("SELECT * FROM agent_workbench_item WHERE user_id=? AND session_id=? AND kind='CHILD' ORDER BY id DESC",(rs,n)->new Row(rs.getString("item_id"),rs.getLong("user_id"),rs.getString("session_id"),rs.getString("kind"),rs.getString("status"),rs.getLong("revision"),decode(rs.getString("payload")),rs.getString("updated_at")),user,session).stream().filter(row->parent.equals(row.data().get("parentId"))&&Objects.equals(task,row.data().get("parentTaskId"))).toList();}
    Row create(long user,String session,String id,String kind,String status,Map<String,Object> data){return locked(user,()->{
        var existing=find(user,session,id);if(existing!=null)return existing;
        jdbc.update("INSERT INTO agent_workbench_item(item_id,user_id,session_id,kind,status,payload) VALUES(?,?,?,?,?,?)",id,user,session,kind,status,encode(data));var row=require(user,session,id);audit(row,"CREATED");return row;
    });}
    Row update(Row previous,String status,Map<String,Object> data,String action){return locked(previous.user(),()->{
        if(jdbc.update("UPDATE agent_workbench_item SET status=?,payload=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP(6) WHERE user_id=? AND item_id=? AND revision=?",status,encode(data),previous.user(),previous.id(),previous.revision())!=1)throw fail(409,"工作项已变化，请刷新核对");
        var row=require(previous.user(),previous.session(),previous.id());audit(row,action);return row;
    });}
    <T>T request(long user,String request,String signature,Class<T> type,Supplier<T> action){
        if(request==null||!request.matches("[A-Za-z0-9_-]{1,128}"))throw fail(400,"请求编号无效");
        return locked(user,()->{
            var previous=jdbc.queryForList("SELECT request_sha256,result_json FROM agent_workbench_request WHERE user_id=? AND request_id=?",user,request);
            if(!previous.isEmpty()){
                if(!hash(signature).equals(previous.get(0).get("request_sha256")))throw fail(409,"请求编号已用于其他操作");
                try{return json.readValue((String)previous.get(0).get("result_json"),type);}catch(Exception error){throw new IllegalStateException("操作回执不可读");}
            }
            T result=action.get();jdbc.update("INSERT INTO agent_workbench_request(user_id,request_id,request_sha256,result_json) VALUES(?,?,?,?)",user,request,hash(signature),encode(result));return result;
        });
    }
    private void audit(Row row,String action){jdbc.update("INSERT INTO agent_workbench_audit(user_id,session_id,item_id,action,revision,payload_sha256) VALUES(?,?,?,?,?,?)",row.user(),row.session(),row.id(),action,row.revision(),hash(encode(row.data())));}
    AgentWorkbenchApi.Item view(Row row){
        var safe=new LinkedHashMap<String,Object>();
        for(String key:List.of("title","text","tasks","options","answer","questionType","feedback","parentId","specialist","childSessionId","result","progress","phase","runId","logicalTaskId","inputTokens","outputTokens","cachedTokens","durationMs","firstContentMs","systemTokens","toolsTokens","messageTokens","beforeChars","afterChars","basis","modelId","provider","purpose","fileId","filename","throughMessageId","forkSessionId","sourceSessionId","evidenceRunId","evidenceCallId"))if(row.data().containsKey(key))safe.put(key,row.data().get(key));
        for(String key:List.of("modelConfigVersion","modelDefault"))if(row.data().containsKey(key))safe.put(key,row.data().get(key));
        return new AgentWorkbenchApi.Item(row.id(),row.kind(),row.status(),row.revision(),safe,row.updated());
    }
    static ResponseStatusException fail(int status,String message){return new ResponseStatusException(HttpStatus.valueOf(status),message);}
}
