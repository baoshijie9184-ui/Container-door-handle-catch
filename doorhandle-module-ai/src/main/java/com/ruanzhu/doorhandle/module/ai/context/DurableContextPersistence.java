package com.ruanzhu.doorhandle.module.ai.context;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import com.ruanzhu.doorhandle.framework.persistence.workflow.AuditEvent;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcAuditStore;
import com.ruanzhu.doorhandle.module.ai.context.DurableContextProtocols.*;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.util.*;
import static com.ruanzhu.doorhandle.module.ai.context.DurableContextProtocols.*;

/** Domain-specific statements over runtime, content and audit. No legacy table fallback exists. */
public final class DurableContextPersistence {
    public record Boot(long owner,String session,String task,long through,boolean ready,long revision,ContextBootstrapV1 body) {}
    public record Reservation(Boot boot,boolean created) {}
    public record SummaryRow(long cursor,String id,long owner,String status,String summary,String digest,String sources,
            String run,LocalDateTime created,ContextSummaryV1 body) {}
    public record Origin(long owner,String session,String scope,String call,String task,String run,OriginEvidenceV1 body) {}
    public record Offload(long cursor,String id,long owner,String session,String scope,String call,String file,
            LocalDateTime created,OffloadEvidenceV1 body) {}
    private static final String SUMMARY_SELECT="SELECT r.*,a.identity_key AS summary_id,a.lifecycle AS summary_status,a.owner_user_id AS asset_owner "
            +"FROM content_revision r JOIN content_asset a ON a.asset_id=r.asset_id AND a.asset_kind=r.asset_kind ";
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final JdbcAuditStore audits;
    public DurableContextPersistence(JdbcTemplate jdbc,ObjectMapper json) {
        this.jdbc=jdbc;this.json=mapper(json);audits=new JdbcAuditStore(jdbc,this.json,Map.of("CONTEXT",ContextAuditV1.class));
    }
    public void validateSchema() {
        jdbc.queryForList("SELECT namespace,owner_id,session_id,state_key,scope_key,revision,current_ref,counter_value,state_code,payload_version,payload_json,created_at,updated_at FROM runtime_state WHERE 1=0");
        jdbc.queryForList("SELECT context_session_id,context_agent_scope,context_revision,context_covered_through,manifest_json FROM content_revision WHERE 1=0");
        jdbc.queryForList("SELECT evidence_version,evidence_json,context_gate,context_offload_id FROM content_link WHERE 1=0");
        audits.validateSchema();
    }
    public void requireSession(long owner,String session) {
        JdbcTransactions.requireActive(jdbc);
        if(owner<=0||jdbc.queryForList("SELECT session_id FROM chat_session WHERE user_id=? AND session_id=? FOR SHARE",owner,session).size()!=1)
            throw new SecurityException("上下文会话不存在或不属于当前账号");
    }
    private static String key(String session,String state) {
        // MySQL utf8mb4_bin is PAD SPACE. Retain original strings in the ordinary columns.
        String s=session.replaceFirst(" +$",""),k=state.replaceFirst(" +$","");
        return hash(s.getBytes(java.nio.charset.StandardCharsets.UTF_8).length+":"+s+":"+k.getBytes(java.nio.charset.StandardCharsets.UTF_8).length+":"+k);
    }
    public long lock(long owner,String session,String scope) {
        requireSession(owner,session);text(session,128,"session");text(scope,160,"scope");
        jdbc.update("""
                INSERT INTO runtime_state(namespace,owner_id,scope_key,session_id,state_key,revision,payload_version,payload_json,created_at,updated_at)
                VALUES('CONTEXT_HEAD',?,?,?,?,0,1,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE owner_id=VALUES(owner_id)
                """,owner,key(session,scope),session,scope,encode(json,new ContextHeadV1(null)));
        var values=jdbc.query("SELECT revision,payload_version,payload_json FROM runtime_state WHERE namespace='CONTEXT_HEAD' AND owner_id=? AND session_id=? AND state_key=? FOR UPDATE",(r,n)->{
            read(r,"payload_version","payload_json",ContextHeadV1.class);return r.getLong("revision");
        },owner,session,scope);
        if(values.size()!=1)throw new IllegalStateException("上下文状态身份冲突");return values.get(0);
    }
    public long revision(long owner,String session,String scope) {
        var values=jdbc.queryForList("SELECT revision FROM runtime_state WHERE namespace='CONTEXT_HEAD' AND owner_id=? AND session_id=? AND state_key=?",Long.class,owner,session,scope);
        return values.isEmpty()?0:values.get(0);
    }
    public Optional<Boot> bootstrap(long owner,String session,String task,boolean locked) {
        if(locked)JdbcTransactions.requireActive(jdbc);
        var rows=jdbc.query("SELECT * FROM runtime_state WHERE namespace='CONTEXT_BOOTSTRAP' AND owner_id=? AND session_id=? AND state_key=?"+(locked?" FOR UPDATE":""),this::boot,owner,session,task);
        return one(rows);
    }
    public Reservation reserve(long owner,String session,String task,long through,ContextBootstrapV1 body) {
        requireSession(owner,session);text(task,36,"task");DurableContextProtocols.bootstrap(body);
        if(through<0||!digest(ContextDigests.bootstrapHash(json,owner,session,body.agentScope(),task,through,body.initialState()),body.initialSha256()))
            throw new IllegalArgumentException("上下文启动资料摘要不匹配");
        boolean created=true;
        try {jdbc.update("""
                INSERT INTO runtime_state(namespace,owner_id,scope_key,session_id,state_key,revision,counter_value,state_code,payload_version,payload_json,created_at,updated_at)
                VALUES('CONTEXT_BOOTSTRAP',?,?,?,?,0,?,'RESERVED',1,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                """,owner,key(session,task),session,task,through,encode(json,body));}
        catch(DuplicateKeyException duplicate){created=false;}
        // A duplicate INSERT owns a shared record lock; use a current shared read, not an X lock upgrade.
        var rows=jdbc.query("SELECT * FROM runtime_state WHERE namespace='CONTEXT_BOOTSTRAP' AND owner_id=? AND session_id=? AND state_key=? FOR SHARE",this::boot,owner,session,task);
        return new Reservation(one(rows).orElseThrow(()->new IllegalStateException("上下文启动身份冲突")),created);
    }
    public void initialized(Boot boot) {
        JdbcTransactions.requireActive(jdbc);
        if(jdbc.update("UPDATE runtime_state SET state_code='INITIALIZED',revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE namespace='CONTEXT_BOOTSTRAP' AND owner_id=? AND session_id=? AND state_key=? AND revision=? AND state_code='RESERVED'",
                boot.owner(),boot.session(),boot.task(),boot.revision())!=1)throw new IllegalStateException("上下文初始化版本已变化");
    }
    private Boot boot(ResultSet r,int ignored)throws SQLException {
        var b=read(r,"payload_version","payload_json",ContextBootstrapV1.class);
        DurableContextProtocols.bootstrap(b);
        long owner=r.getLong("owner_id"),through=r.getLong("counter_value");String session=r.getString("session_id"),task=r.getString("state_key");
        if(!Set.of("RESERVED","INITIALIZED").contains(r.getString("state_code"))||!digest(ContextDigests.bootstrapHash(json,owner,session,b.agentScope(),task,through,b.initialState()),b.initialSha256()))
            throw new IllegalStateException("上下文启动资料损坏");
        return new Boot(owner,session,task,through,"INITIALIZED".equals(r.getString("state_code")),r.getLong("revision"),b);
    }
    public SummaryRow current(long owner,String session,String scope) {
        return one(jdbc.query(SUMMARY_SELECT+"JOIN runtime_state h ON h.namespace='CONTEXT_HEAD' AND h.owner_id=r.owner_user_id AND h.session_id=r.context_session_id AND h.state_key=r.context_agent_scope AND h.current_ref=a.identity_key WHERE r.asset_kind='CONTEXT_SUMMARY' AND h.owner_id=? AND h.session_id=? AND h.state_key=? AND a.lifecycle='ACTIVE'",this::summary,owner,session,scope)).orElse(null);
    }
    public SummaryRow activeSummary(long owner,String session,String id) {
        return one(jdbc.query(SUMMARY_SELECT+"WHERE r.asset_kind='CONTEXT_SUMMARY' AND r.owner_user_id=? AND r.context_session_id=? AND a.identity_key=? AND a.lifecycle='ACTIVE'",this::summary,owner,session,id)).orElse(null);
    }
    public SummaryRow forkCandidate(long owner,String session,long through) {
        return one(jdbc.query(SUMMARY_SELECT+"WHERE r.asset_kind='CONTEXT_SUMMARY' AND r.owner_user_id=? AND r.context_session_id=? AND r.context_agent_scope='main' AND a.lifecycle='ACTIVE' AND r.context_covered_through<=? ORDER BY r.context_covered_through DESC,r.context_revision DESC LIMIT 1",this::summary,owner,session,through)).orElse(null);
    }
    public List<SummaryRow> heads(long owner,String session) {
        return jdbc.query(SUMMARY_SELECT+"JOIN runtime_state h ON h.namespace='CONTEXT_HEAD' AND h.owner_id=r.owner_user_id AND h.session_id=r.context_session_id AND h.state_key=r.context_agent_scope AND h.current_ref=a.identity_key WHERE r.asset_kind='CONTEXT_SUMMARY' AND h.owner_id=? AND h.session_id=? ORDER BY r.id DESC LIMIT 20",this::summary,owner,session);
    }
    public void appendSummary(long owner,String id,String run,String summary,String summaryHash,String sources,ContextSummaryV1 body,long expected) {
        DurableContextProtocols.summary(body);text(id,36,"summary identity");text(run,128,"run");
        requireSession(owner,body.sessionId());String asset="context-summary:"+id;
        if(body.schemaVersion()!=1||body.contextRevision()!=Math.addExact(expected,1)||!digest(ContextDigests.summaryHash(json,summary,body.messageState(),sources,body.agentScope(),body.coveredThrough(),body.historySha256(),body.originalState()),summaryHash))
            throw new IllegalArgumentException("上下文摘要或修订号不匹配");
        jdbc.update("INSERT INTO content_asset(asset_id,asset_kind,owner_user_id,identity_key,title,visibility,lifecycle,current_version,created_at,updated_at) VALUES(?,'CONTEXT_SUMMARY',?,?,'持久上下文摘要','PRIVATE','PREPARING',NULL,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",asset,owner,id);
        jdbc.update("INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,content_text,content_sha256,sources_json,source_run_id,manifest_json,created_at) VALUES(?,'CONTEXT_SUMMARY',1,?,?,?,?,?,?,UTC_TIMESTAMP(6))",asset,owner,summary,summaryHash,sources,run,encode(json,body));
        jdbc.update("UPDATE content_asset SET lifecycle='ACTIVE',current_version=1 WHERE asset_id=? AND asset_kind='CONTEXT_SUMMARY'",asset);
        if(jdbc.update("UPDATE runtime_state SET revision=?,current_ref=?,updated_at=UTC_TIMESTAMP(6) WHERE namespace='CONTEXT_HEAD' AND owner_id=? AND session_id=? AND state_key=? AND revision=?",body.contextRevision(),id,owner,body.sessionId(),body.agentScope(),expected)!=1)
            throw new IllegalStateException("持久摘要版本已变化，停止应用压缩");
    }
    public boolean invalidate(long owner,String session,String scope,String id) {
        JdbcTransactions.requireActive(jdbc);
        int count=jdbc.update("UPDATE content_asset a JOIN content_revision r ON r.asset_id=a.asset_id AND r.asset_kind=a.asset_kind SET a.lifecycle='INVALIDATED',a.revision=a.revision+1,a.updated_at=UTC_TIMESTAMP(6) WHERE a.asset_kind='CONTEXT_SUMMARY' AND a.identity_key=? AND a.owner_user_id=? AND r.owner_user_id=? AND r.context_session_id=? AND r.context_agent_scope=? AND a.lifecycle='ACTIVE'",id,owner,owner,session,scope);
        if(count==1)jdbc.update("UPDATE runtime_state SET revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE namespace='CONTEXT_HEAD' AND owner_id=? AND session_id=? AND state_key=? AND current_ref=?",owner,session,scope,id);
        return count==1;
    }
    private SummaryRow summary(ResultSet r,int ignored)throws SQLException {
        var body=decode(r.getString("manifest_json"),ContextSummaryV1.class);String id=r.getString("summary_id");
        DurableContextProtocols.summary(body);
        long owner=r.getLong("owner_user_id");
        if(body.schemaVersion()!=1||r.getInt("version")!=1||owner!=r.getLong("asset_owner")||!("context-summary:"+id).equals(r.getString("asset_id"))
                ||!body.sessionId().equals(r.getString("context_session_id"))||!body.agentScope().equals(r.getString("context_agent_scope"))
                ||body.contextRevision()!=r.getLong("context_revision")||body.coveredThrough()!=r.getLong("context_covered_through")
                ||!digest(ContextDigests.summaryHash(json,r.getString("content_text"),body.messageState(),r.getString("sources_json"),body.agentScope(),body.coveredThrough(),body.historySha256(),body.originalState()),r.getString("content_sha256")))
            throw new IllegalStateException("持久摘要身份或内容损坏");
        return new SummaryRow(r.getLong("id"),id,owner,r.getString("summary_status"),r.getString("content_text"),r.getString("content_sha256"),r.getString("sources_json"),r.getString("source_run_id"),r.getObject("created_at",LocalDateTime.class),body);
    }
    public Origin origin(long owner,String session,String scope,String call) {
        return one(jdbc.query("SELECT * FROM content_link WHERE link_kind='TOOL_SOURCE' AND owner_user_id=? AND session_id=? AND agent_scope=? AND call_id=?",this::origin,owner,session,scope,call)).orElse(null);
    }
    public boolean appendOrigin(long owner,String session,String scope,String task,String run,String call,OriginEvidenceV1 body) {
        requireSession(owner,session);boolean created=true;
        try {jdbc.update("INSERT INTO content_link(link_kind,owner_user_id,session_id,agent_scope,call_id,logical_task_id,run_id,target_type,target_id,evidence_version,evidence_json,created_at) VALUES('TOOL_SOURCE',?,?,?,?,?,?,'CONTEXT_TASK',?,1,?,UTC_TIMESTAMP(6))",owner,session,scope,call,task,run,task,encode(json,body));}
        catch(DuplicateKeyException conflict){created=false;}
        var saved=one(jdbc.query("SELECT * FROM content_link WHERE link_kind='TOOL_SOURCE' AND owner_user_id=? AND session_id=? AND agent_scope=? AND call_id=? FOR SHARE",this::origin,owner,session,scope,call)).orElseThrow(()->new IllegalStateException("上下文来源身份冲突"));
        if(!saved.task().equals(task)||!digest(saved.body().sourcesSha256(),body.sourcesSha256())||!saved.body().sourcesJson().equals(body.sourcesJson()))throw new IllegalStateException("工具来源回执不一致");
        return created;
    }
    public List<Origin> origins(long owner,String session,String scope,String task) {
        String where="link_kind='TOOL_SOURCE' AND owner_user_id=? AND session_id=?";var args=new ArrayList<Object>(List.of(owner,session));
        if(scope!=null){where+=" AND agent_scope=?";args.add(scope);}if(task!=null){where+=" AND logical_task_id=?";args.add(task);}
        return jdbc.query("SELECT * FROM content_link WHERE "+where+" ORDER BY id LIMIT 513",this::origin,args.toArray());
    }
    private Origin origin(ResultSet r,int ignored)throws SQLException {
        var body=read(r,"evidence_version","evidence_json",OriginEvidenceV1.class);
        if(!digest(hash(body.sourcesJson()),body.sourcesSha256())||!"CONTEXT_TASK".equals(r.getString("target_type"))||!Objects.equals(r.getString("logical_task_id"),r.getString("target_id")))throw new IllegalStateException("工具来源回执损坏");
        return new Origin(r.getLong("owner_user_id"),r.getString("session_id"),r.getString("agent_scope"),r.getString("call_id"),r.getString("logical_task_id"),r.getString("run_id"),body);
    }
    public List<Offload> offloads(long owner,String session,String scope,String call,String file,int limit,boolean descending) {
        if(limit<1||limit>1001)throw new IllegalArgumentException("上下文回执读取上限无效");
        String where="link_kind='CONTEXT_SOURCE' AND owner_user_id=? AND session_id=?";var args=new ArrayList<Object>(List.of(owner,session));
        if(scope!=null){where+=" AND agent_scope=?";args.add(scope);}if(call!=null){where+=" AND call_id=?";args.add(call);}if(file!=null){where+=" AND target_id=?";args.add(file);}
        args.add(limit);return jdbc.query("SELECT * FROM content_link WHERE "+where+" ORDER BY id"+(descending?" DESC":"")+" LIMIT ?",this::offload,args.toArray());
    }
    public Offload appendOffload(long owner,String session,String scope,String call,String id,String file,OffloadEvidenceV1 body) {
        requireSession(owner,session);DurableContextProtocols.offload(body);text(scope,160,"scope");text(call,160,"call");text(id,36,"offload");text(file,36,"file");
        if(!digest(hash(body.sourcesJson()),body.sourcesSha256()))throw new IllegalArgumentException("卸载来源摘要不匹配");
        try {jdbc.update("INSERT INTO content_link(link_kind,owner_user_id,session_id,agent_scope,call_id,target_type,target_id,subject_type,subject_id,evidence_version,evidence_json,created_at) VALUES('CONTEXT_SOURCE',?,?,?,?,'WORKSPACE_FILE',?,'CONTEXT_OFFLOAD',?,1,?,UTC_TIMESTAMP(6))",owner,session,scope,call,file,id,encode(json,body));}
        catch(DuplicateKeyException conflict){/* Current shared read below preserves the first immutable receipt. */}
        var saved=one(jdbc.query("SELECT * FROM content_link WHERE link_kind='CONTEXT_SOURCE' AND owner_user_id=? AND session_id=? AND agent_scope=? AND call_id=? FOR SHARE",this::offload,owner,session,scope,call)).orElseThrow(()->new IllegalStateException("卸载资料身份冲突"));
        if(!saved.file().equals(file)||!digest(saved.body().contentSha256(),body.contentSha256())||saved.body().byteLength()!=body.byteLength()
                ||!saved.body().sourcesJson().equals(body.sourcesJson())||!digest(saved.body().sourcesSha256(),body.sourcesSha256()))throw new IllegalStateException("卸载资料回执冲突");
        if(!"LEGACY".equals(saved.body().lineageKind())&&!saved.body().equals(body))throw new IllegalStateException("卸载资料分支来源冲突");
        return saved;
    }
    private Offload offload(ResultSet r,int ignored)throws SQLException {
        var body=read(r,"evidence_version","evidence_json",OffloadEvidenceV1.class);
        DurableContextProtocols.offload(body);
        if(!digest(hash(body.sourcesJson()),body.sourcesSha256())||!"WORKSPACE_FILE".equals(r.getString("target_type"))||!"CONTEXT_OFFLOAD".equals(r.getString("subject_type"))||body.byteLength()<0)
            throw new IllegalStateException("卸载资料来源损坏");
        sha(body.contentSha256());return new Offload(r.getLong("id"),r.getString("subject_id"),r.getLong("owner_user_id"),r.getString("session_id"),r.getString("agent_scope"),r.getString("call_id"),r.getString("target_id"),r.getObject("created_at",LocalDateTime.class),body);
    }
    public void audit(long owner,String session,String scope,String id,String action,String digest) {
        JdbcTransactions.requireActive(jdbc);text(scope,160,"scope");text(id,36,"resource");sha(digest);
        audits.append(new AuditEvent("CONTEXT",owner,owner,"CONTEXT",id,session,null,null,null,action,null,digest,null,1,new ContextAuditV1(scope,null,null)));
    }
    private <T>T read(ResultSet row,String version,String payload,Class<T> type)throws SQLException {
        if(row.getInt(version)!=1)throw new IllegalStateException("上下文载荷版本不受支持");return decode(row.getString(payload),type);
    }
    private <T>T decode(String value,Class<T> type) {
        try{return json.readValue(value,type);}catch(Exception invalid){throw new IllegalStateException("上下文记录不可读取",invalid);}
    }
    private static <T>Optional<T> one(List<T> rows) {
        if(rows.size()>1)throw new IllegalStateException("上下文身份不唯一");return rows.stream().findFirst();
    }
}
