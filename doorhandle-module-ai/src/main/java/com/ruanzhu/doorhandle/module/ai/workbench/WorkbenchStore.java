package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.*;
import com.ruanzhu.doorhandle.framework.persistence.JdbcOwnerLock;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.context.ChildProvenanceReader;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.function.Supplier;

/** Closed workbench protocols on the compact operation store. No legacy fallback. */
@Repository
@ConditionalOnProperty(prefix="agentscope.workbench",name="enabled",havingValue="true")
public class WorkbenchStore {
    private static final String ITEMS="'WORKBENCH_EXECUTION','WORKBENCH_CHILD','WORKBENCH_PLAN','WORKBENCH_QUESTION','WORKBENCH_TASKS','WORKBENCH_TOOL','WORKBENCH_CHECKPOINT','WORKBENCH_MODEL_SELECTION','WORKBENCH_TURN','WORKBENCH_FORK_SNAPSHOT','WORKBENCH_ARTIFACT','WORKBENCH_USAGE','WORKBENCH_CONTEXT','WORKBENCH_TOOL_TIMING'";
    private static final String COLUMNS="id,workflow_id,resource_id,owner_user_id,session_id,kind,status,revision,payload_version,payload_json,updated_at,claim_token,fence,lease_expires_at";
    private static final DateTimeFormatter DISPLAY=DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS");
    record Row(String id,long user,String session,String kind,String status,long revision,Map<String,Object> data,String updated,
               long cursor,String workflowId,String claimToken,long fence,LocalDateTime lease,WorkbenchProtocol.LegacyItemV1 legacy) {}
    record Attempt(long user,String session,String itemId,String taskId,String runId,String claimToken,long fence) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ObjectMapper json;
    private final WorkbenchProtocol protocol;
    public WorkbenchStore(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper mapper){
        this.jdbc=jdbc;this.json=mapper.copy().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).disable(SerializationFeature.INDENT_OUTPUT);
        protocol=new WorkbenchProtocol(mapper);tx=new TransactionTemplate(manager);tx.setTimeout(5);
        tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
    }
    public JdbcTemplate jdbc(){return jdbc;}
    void validate(){jdbc.queryForList("SELECT "+COLUMNS+",workbench_parent_item_id,workbench_parent_task_id,workbench_logical_task_id,workbench_specialist,workbench_role,workbench_yield_ready FROM workflow_instance WHERE 1=0");}
    public <T>T locked(long user,Supplier<T> work){return tx.execute(status->{JdbcOwnerLock.lock(jdbc,JdbcOwnerLock.Scope.WORKBENCH,user);return work.get();});}
    String encode(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalArgumentException("工作区内容格式无效",error);}}
    Map<String,Object> decode(String value){try{return json.readValue(value,new TypeReference<LinkedHashMap<String,Object>>(){});}catch(Exception error){throw new IllegalStateException("工作区状态无法读取",error);}}
    static String hash(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
    static String stable(long user,String session,String kind){return UUID.nameUUIDFromBytes((user+":"+session+":"+kind).getBytes(StandardCharsets.UTF_8)).toString();}
    private RowMapper<Row> mapper(){return (rs,n)->{
        String type=WorkbenchProtocol.type(rs.getString("kind"));var payload=protocol.read(type,rs.getInt("payload_version"),rs.getString("payload_json"));
        LocalDateTime updated=rs.getObject("updated_at",LocalDateTime.class);
        return new Row(rs.getString("resource_id"),rs.getLong("owner_user_id"),rs.getString("session_id"),type,rs.getString("status"),rs.getLong("revision"),protocol.data(payload),
            updated==null?null:updated.plusHours(8).format(DISPLAY),rs.getLong("id"),rs.getString("workflow_id"),rs.getString("claim_token"),rs.getLong("fence"),rs.getObject("lease_expires_at",LocalDateTime.class),payload.legacy());
    };}
    private static String currentRead(){return org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()?" FOR SHARE":"";}
    Row find(long user,String session,String id){return jdbc.query("SELECT "+COLUMNS+" FROM workflow_instance WHERE kind IN ("+ITEMS+") AND owner_user_id=? AND session_id=? AND workbench_item_id=?"+currentRead(),mapper(),user,session,id).stream().findFirst().orElse(null);}
    Row require(long user,String session,String id){var row=find(user,session,id);if(row==null)throw fail(404,"工作项不存在或无权限");return row;}
    List<Row> list(long user,String session){return jdbc.query("SELECT "+COLUMNS+" FROM workflow_instance WHERE kind IN ("+ITEMS+") AND owner_user_id=? AND session_id=? ORDER BY id DESC LIMIT 200",mapper(),user,session);}
    List<Row> publicRows(long user,String session){return jdbc.query("SELECT "+COLUMNS+" FROM workflow_instance WHERE kind IN ("+ITEMS+") AND owner_user_id=? AND session_id=? AND kind NOT IN ('WORKBENCH_TOOL','WORKBENCH_CHECKPOINT','WORKBENCH_TURN','WORKBENCH_MODEL_SELECTION') ORDER BY id DESC LIMIT 180",mapper(),user,session);}
    List<Row> rows(long user,String session,String type,String status){
        String kind=WorkbenchProtocol.kind(type).name();return jdbc.query("SELECT "+COLUMNS+" FROM workflow_instance WHERE kind=? AND owner_user_id=? AND session_id=?"+(status==null?"":" AND status=?")+" ORDER BY id",mapper(),status==null?new Object[]{kind,user,session}:new Object[]{kind,user,session,status});
    }
    List<Row> childRows(long user,String session,String parent,Object task){return jdbc.query("SELECT "+COLUMNS+" FROM workflow_instance WHERE kind='WORKBENCH_CHILD' AND owner_user_id=? AND session_id=? AND workbench_parent_item_id=? AND workbench_parent_task_id<=>? ORDER BY id DESC",mapper(),user,session,parent,task);}
    List<Row> pendingInteractions(long user,String session,String parent,Object task){return jdbc.query("SELECT "+COLUMNS+" FROM workflow_instance WHERE kind IN ('WORKBENCH_PLAN','WORKBENCH_QUESTION') AND owner_user_id=? AND session_id=? AND workbench_parent_item_id=? AND workbench_logical_task_id<=>? AND status='PENDING' ORDER BY id",mapper(),user,session,parent,task);}
    long pendingChildCount(long user){return jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='WORKBENCH_CHILD' AND owner_user_id=? AND status IN ('QUEUED','RUNNING','WAITING_INPUT','WAITING_PLAN','WAITING_CHILD','NEEDS_REVIEW')",Long.class,user);}
    boolean permitsSpecialist(long user,String run,String specialist,String role){return jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='WORKBENCH_CHILD' AND owner_user_id=? AND run_id=? AND workbench_specialist=? AND workbench_role=? AND status='RUNNING' AND claim_token IS NOT NULL AND lease_expires_at>UTC_TIMESTAMP(6)",Long.class,user,run,specialist,role)>0;}
    List<Row> dispatch(long after){return jdbc.query("SELECT "+COLUMNS+" FROM workflow_instance WHERE ((kind='WORKBENCH_CHILD' AND status='QUEUED' AND (workbench_yield_ready IS NULL OR workbench_yield_ready=TRUE)) OR (kind='WORKBENCH_EXECUTION' AND status='READY')) AND id>? ORDER BY id LIMIT 12",mapper(),after);}
    Optional<ChildProvenanceReader.ChildProvenance> childProvenance(long user,String session,String item){return jdbc.query("SELECT resource_id,owner_user_id,session_id,status,revision FROM workflow_instance WHERE kind='WORKBENCH_CHILD' AND owner_user_id=? AND session_id=? AND workbench_item_id=?",(rs,n)->new ChildProvenanceReader.ChildProvenance(rs.getString(1),rs.getLong(2),rs.getString(3),rs.getString(4),rs.getLong(5)),user,session,item).stream().findFirst();}
    Row create(long user,String session,String id,String kind,String status,Map<String,Object> data){return locked(user,()->{
        var existing=find(user,session,id);if(existing!=null){if(!existing.kind().equals(kind))throw fail(409,"工作项编号已用于其他类型");return existing;}
        identity(user,session,id);protocol.state(kind,status);var body=protocol.payload(kind,data,null);String token=WorkbenchProtocol.execution(kind)&&status.equals("RUNNING")?UUID.randomUUID().toString():null;
        jdbc.update("""
            INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,resource_type,resource_id,session_id,run_id,status,payload_version,payload_json,claim_token,fence,attempts,lease_expires_at,finished_at)
            VALUES(?,?,'WORKBENCH_ITEM',?,?,?,?,'WORKBENCH_ITEM',?,?,?,?,1,?,?,?, ?,IF(? IS NULL,NULL,TIMESTAMPADD(SECOND,90,UTC_TIMESTAMP(6))),IF(?,UTC_TIMESTAMP(6),NULL))
            """,UUID.randomUUID().toString(),WorkbenchProtocol.kind(kind).name(),id,hash(encode(List.of(user,session,id,kind))),user,user,id,session,data.get("runId"),status,protocol.write(body),token,token==null?0:1,token==null?0:1,token,WorkbenchProtocol.closed(kind,status));
        var row=require(user,session,id);logicalTask(row);audit(row,"CREATED");return row;
    });}
    Row update(Row previous,String status,Map<String,Object> data,String action){return locked(previous.user(),()->{
        var current=require(previous.user(),previous.session(),previous.id());if(current.revision()!=previous.revision())throw fail(409,"工作项已变化，请刷新核对");
        protocol.transition(previous.kind(),previous.status(),status);var body=protocol.payload(previous.kind(),data,previous.legacy());
        boolean execution=WorkbenchProtocol.execution(previous.kind()),start=execution&&status.equals("RUNNING")&&!previous.status().equals("RUNNING");
        boolean release=execution&&(Set.of("COMPLETED","CANCELLED","NEEDS_REVIEW").contains(status)||Boolean.TRUE.equals(data.get("yieldReady")));
        String claim=start?UUID.randomUUID().toString():release?null:previous.claimToken();long fence=previous.fence()+(start||release&&previous.claimToken()!=null?1:0);
        if(jdbc.update("""
            UPDATE workflow_instance SET status=?,payload_json=?,run_id=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6),claim_token=?,fence=?,
              lease_expires_at=IF(? IS NULL,NULL,IF(?,TIMESTAMPADD(SECOND,90,UTC_TIMESTAMP(6)),lease_expires_at)),attempts=attempts+?,finished_at=IF(?,UTC_TIMESTAMP(6),NULL)
            WHERE owner_user_id=? AND session_id=? AND workflow_id=? AND revision=? AND fence=? AND claim_token<=>?
            """,status,protocol.write(body),data.get("runId"),claim,fence,claim,start,start?1:0,WorkbenchProtocol.closed(previous.kind(),status),previous.user(),previous.session(),previous.workflowId(),previous.revision(),previous.fence(),previous.claimToken())!=1)throw fail(409,"工作项执行权已变化，请刷新核对");
        var row=require(previous.user(),previous.session(),previous.id());logicalTask(row);audit(row,action);return row;
    });}
    private void logicalTask(Row item){
        if(!WorkbenchProtocol.execution(item.kind()))return;
        Object raw=item.data().get("logicalTaskId");if(!(raw instanceof String task)||task.isBlank()||task.codePointCount(0,task.length())>128)throw new IllegalArgumentException("Execution requires a logical task identity");
        String scope=hash(encode(List.of(item.user(),item.session(),item.id())));
        var existing=jdbc.queryForList("SELECT id,parent_workflow_id,owner_user_id,session_id,status FROM workflow_instance WHERE kind='WORKBENCH_LOGICAL_TASK' AND idempotency_scope=? AND request_id=? FOR SHARE",scope,task);
        if(existing.isEmpty()){
            var version=item.data().get("modelConfigVersion");String body=protocol.write(new WorkbenchProtocol.LogicalTaskV1(item.id(),Objects.toString(item.data().get("runId"),null),Objects.toString(item.data().get("role"),null),Objects.toString(item.data().get("modelId"),null),version instanceof Number n?n.longValue():null,Objects.toString(item.data().get("modelDefault"),null),false));
            jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,parent_workflow_id,resource_type,resource_id,session_id,run_id,status,payload_version,payload_json,finished_at)
                VALUES(?,'WORKBENCH_LOGICAL_TASK',?,?,?,?,?,?,'WORKBENCH_TASK',?,?,?,?,1,?,IF(?,UTC_TIMESTAMP(6),NULL))
                """,UUID.randomUUID().toString(),scope,task,hash(encode(List.of(item.user(),item.session(),item.id(),task))),item.user(),item.user(),item.cursor(),task,item.session(),item.data().get("runId"),item.status(),body,WorkbenchProtocol.closed(item.kind(),item.status()));
        }else{
            var row=existing.get(0);if(((Number)row.get("parent_workflow_id")).longValue()!=item.cursor()||((Number)row.get("owner_user_id")).longValue()!=item.user()||!Objects.equals(row.get("session_id"),item.session()))throw fail(409,"逻辑任务身份冲突");
            jdbc.update("UPDATE workflow_instance SET status=?,run_id=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6),finished_at=IF(?,UTC_TIMESTAMP(6),NULL) WHERE id=?",item.status(),item.data().get("runId"),WorkbenchProtocol.closed(item.kind(),item.status()),row.get("id"));
        }
    }
    Attempt attempt(Row row){if(!WorkbenchProtocol.execution(row.kind())||row.claimToken()==null)throw fail(409,"工作项没有当前执行权");return new Attempt(row.user(),row.session(),row.id(),Objects.toString(row.data().get("logicalTaskId"),null),Objects.toString(row.data().get("runId"),null),row.claimToken(),row.fence());}
    void assertAttempt(Attempt attempt){var row=require(attempt.user(),attempt.session(),attempt.itemId());var now=jdbc.queryForObject("SELECT UTC_TIMESTAMP(6)",LocalDateTime.class);
        if(!Objects.equals(attempt.claimToken(),row.claimToken())||attempt.fence()!=row.fence()||!Objects.equals(attempt.taskId(),row.data().get("logicalTaskId"))||!Objects.equals(attempt.runId(),row.data().get("runId"))||row.lease()==null||!row.lease().isAfter(now)||Set.of("COMPLETED","CANCELLED","NEEDS_REVIEW","READY").contains(row.status())||Boolean.TRUE.equals(row.data().get("yieldReady")))throw fail(409,"执行租约已结束或被替换");
    }
    <T>T withAttempt(Attempt attempt,Supplier<T> work){return locked(attempt.user(),()->{assertAttempt(attempt);return work.get();});}
    boolean renew(Attempt attempt){return jdbc.update("""
        UPDATE workflow_instance SET lease_expires_at=TIMESTAMPADD(SECOND,90,UTC_TIMESTAMP(6))
        WHERE owner_user_id=? AND session_id=? AND workbench_item_id=? AND claim_token=? AND fence=? AND run_id<=>? AND workbench_logical_task_id<=>?
          AND lease_expires_at>UTC_TIMESTAMP(6) AND status IN ('RUNNING','WAITING_PLAN','WAITING_INPUT','WAITING_CHILD','QUEUED') AND (workbench_yield_ready IS NULL OR workbench_yield_ready=FALSE)
        """,attempt.user(),attempt.session(),attempt.itemId(),attempt.claimToken(),attempt.fence(),attempt.runId(),attempt.taskId())==1;}
    List<Row> stale(){return jdbc.query("SELECT "+COLUMNS+" FROM workflow_instance WHERE kind IN ('WORKBENCH_EXECUTION','WORKBENCH_CHILD') AND (status='RUNNING' OR (status IN ('WAITING_PLAN','WAITING_INPUT','WAITING_CHILD','QUEUED') AND workbench_yield_ready=FALSE)) AND (claim_token IS NULL OR lease_expires_at<=UTC_TIMESTAMP(6)) ORDER BY id LIMIT 50",mapper());}
    boolean committedWait(Row row){
        var checkpoint=find(row.user(),row.session(),stable(row.user(),row.session(),"checkpoint:"+row.id()));
        if(checkpoint==null||!checkpoint.kind().equals("CHECKPOINT")||!Objects.equals(checkpoint.data().get("runId"),row.data().get("runId"))||!Objects.equals(checkpoint.data().get("logicalTaskId"),row.data().get("logicalTaskId"))||!(checkpoint.data().get("sdkRevision") instanceof Number version)||version.longValue()<1)return false;
        String sdk="wb:"+row.data().get("logicalTaskId")+":"+(row.kind().equals("CHILD")?row.id():"main");
        var revisions=jdbc.queryForList("SELECT revision FROM runtime_state WHERE namespace='SDK_CHECKPOINT' AND owner_id=? AND session_id=? AND state_key='agent_state'",Long.class,row.user(),sdk);
        return !revisions.isEmpty()&&revisions.get(0)>=version.longValue();
    }
    void recover(Row candidate){locked(candidate.user(),()->{
        var current=require(candidate.user(),candidate.session(),candidate.id());var now=jdbc.queryForObject("SELECT UTC_TIMESTAMP(6)",LocalDateTime.class);
        if(current.revision()!=candidate.revision()||current.lease()!=null&&current.lease().isAfter(now))return null;
        if(current.status().startsWith("WAITING_")&&Boolean.FALSE.equals(current.data().get("yieldReady"))&&committedWait(current)){
            var values=new LinkedHashMap<>(current.data());values.put("yieldReady",true);update(current,current.status(),values,"WAIT_RECOVERED");
        }else if(current.status().equals("RUNNING")||Set.of("QUEUED","WAITING_PLAN","WAITING_INPUT","WAITING_CHILD").contains(current.status())&&Boolean.FALSE.equals(current.data().get("yieldReady")))update(current,"NEEDS_REVIEW",current.data(),"PROCESS_INTERRUPTED");
        return null;
    });}
    <T>T request(long user,String request,String signature,Class<T> type,Supplier<T> action){
        if(request==null||!request.matches("[A-Za-z0-9_-]{1,128}"))throw fail(400,"请求编号无效");String responseType=protocol.commandType(type);
        return locked(user,()->{var previous=jdbc.queryForList("SELECT request_sha256,result_version,result_json,result_sha256 FROM workflow_instance WHERE kind='WORKBENCH_COMMAND' AND owner_user_id=? AND idempotency_scope=? AND request_id=? FOR SHARE",user,"OWNER:"+user,request);
            if(!previous.isEmpty()){var row=previous.get(0);if(!hash(signature).equals(row.get("request_sha256")))throw fail(409,"请求编号已用于其他操作");String body=(String)row.get("result_json");if(!(row.get("result_version") instanceof Number version)||version.intValue()!=1||body==null||!hash(body).equals(row.get("result_sha256")))throw new IllegalStateException("工作台回执校验失败");return protocol.result(body,responseType,type);}
            T result=action.get();String body=protocol.write(new WorkbenchProtocol.CommandResultV1(responseType,encode(result)));
            jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,resource_type,resource_id,status,payload_version,payload_json,result_version,result_json,result_sha256,finished_at)
                VALUES(?,'WORKBENCH_COMMAND',?,?,?,?,?,'WORKBENCH_COMMAND',?,'COMPLETED',1,?,1,?,?,UTC_TIMESTAMP(6))
                """,UUID.randomUUID().toString(),"OWNER:"+user,request,hash(signature),user,user,request,protocol.write(new WorkbenchProtocol.CommandV1(responseType)),body,hash(body));return result;});
    }
    private void audit(Row row,String action){jdbc.update("""
        INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,session_id,action,revision,content_sha256,payload_version,payload_json)
        VALUES(?,'WORKBENCH',?,?,'WORKBENCH_ITEM',?,?,?,?,?,1,?)
        """,UUID.randomUUID().toString(),row.user(),row.user(),row.id(),row.session(),action,row.revision(),hash(encode(row.data())),protocol.write(new WorkbenchProtocol.AuditV1(row.kind(),row.status(),null,null,null)));}
    private static void identity(long user,String session,String id){if(user<=0||session==null||session.codePointCount(0,session.length())>128||id==null||id.isBlank()||id.codePointCount(0,id.length())>64)throw new IllegalArgumentException("Invalid workbench identity");}
    AgentWorkbenchApi.Item view(Row row){var safe=new LinkedHashMap<String,Object>();
        for(String key:List.of("title","text","tasks","options","answer","questionType","feedback","parentId","specialist","childSessionId","result","progress","phase","runId","logicalTaskId","inputTokens","outputTokens","cachedTokens","durationMs","firstContentMs","systemTokens","toolsTokens","messageTokens","beforeChars","afterChars","basis","modelId","provider","purpose","fileId","filename","throughMessageId","forkSessionId","sourceSessionId","evidenceRunId","evidenceCallId","modelConfigVersion","modelDefault"))if(row.data().containsKey(key))safe.put(key,row.data().get(key));
        return new AgentWorkbenchApi.Item(row.id(),row.kind(),row.status(),row.revision(),safe,row.updated());}
    static ResponseStatusException fail(int status,String message){return new ResponseStatusException(HttpStatus.valueOf(status),message);}
}
