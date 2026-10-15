package com.ruanzhu.doorhandle.module.ai.journal;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.ai.config.AgentJournalProperties;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.dao.DuplicateKeyException;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** 运行事件追加和序号更新在同一短事务内完成，模型/工具调用在事务外。 */
@Service
@EnableConfigurationProperties(AgentJournalProperties.class)
public class JdbcAgentJournal implements AgentJournal {
    private static final String POLICY = "role-readonly-v1";
    private static final Set<String> TERMINAL = Set.of("COMPLETED", "ERROR", "CANCELLED", "INTERRUPTED");
    private static final Set<String> TYPES = Set.of("RUN_STARTED", "RUN_COMPLETED", "RUN_ERROR", "RUN_CANCELLED", "RUN_INTERRUPTED",
            "AGENT_STARTED", "AGENT_COMPLETED", "AGENT_ERROR", "AGENT_CANCELLED", "MODEL_STARTED", "MODEL_COMPLETED", "MODEL_ERROR", "MODEL_CANCELLED",
            "AUTHORIZATION_ALLOWED", "AUTHORIZATION_DENIED", "TOOL_STARTED", "TOOL_COMPLETED", "TOOL_ERROR", "TOOL_CANCELLED",
            "COMMAND_RECEIVED","COMMAND_REJECTED","SKILL_COMMAND_LOADED");
    private static final Set<String> PAYLOAD = Set.of("agent", "tool", "callId", "scope", "decision", "policyVersion", "result", "durationMs", "inputTokens", "outputTokens", "elapsedMs", "parentCallId","command","status","skillId","version","sha256");
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ObjectMapper json;
    private final AgentJournalProperties properties;
    private final String instance = UUID.randomUUID().toString();
    private final Map<String, Handle> active = new ConcurrentHashMap<>();
    public JdbcAgentJournal(JdbcTemplate jdbc, PlatformTransactionManager transactions, ObjectMapper json, AgentJournalProperties properties) {
        this.jdbc = jdbc; this.tx = new TransactionTemplate(transactions); this.json = json; this.properties = properties;
    }
    public boolean enabled() { return properties.isEnabled(); }
    @PostConstruct public void verifySchema() {
        if (enabled()) {
            try { jdbc.queryForObject("SELECT COUNT(*) FROM agent_run WHERE 1 = 0", Long.class);
                  jdbc.queryForObject("SELECT COUNT(*) FROM agent_run_event WHERE 1 = 0", Long.class); }
            catch (RuntimeException error) { throw new IllegalStateException("请先执行 migration-V16-agentscope-run-journal.sql 再启用运行日志"); }
        }
    }
    @Override public void checkRequest(AgentActor actor, String entry, String request) {
        if (!enabled()) return;
        if (actor == null || actor.userId() <= 0 || entry == null || !Set.of("CHAT", "AGUI").contains(entry)
                || request == null || !request.matches("[A-Za-z0-9_-]{1,128}")) throw badRequest("运行请求格式不正确");
        Long count = jdbc.queryForObject("SELECT COUNT(*) FROM agent_run WHERE user_id=? AND entry_point=? AND request_key=?", Long.class, actor.userId(), entry, request);
        if (count != null && count > 0) throw new ResponseStatusException(HttpStatus.CONFLICT,"此请求已提交，请读取已有运行记录");
    }
    public Run begin(AgentActor actor, String session, String main, String entry, String request, String model) {
        if (!enabled()) return AgentJournal.disabled().begin(actor, session, main, entry, request, model);
        if (actor == null || actor.userId() <= 0 || session == null || !session.matches("[A-Za-z0-9_.-]{1,128}")
                || !com.ruanzhu.doorhandle.module.ai.agent.RoleAgentCatalog.mainId(actor).equals(main) || !Set.of("CHAT", "AGUI").contains(entry)
                || request == null || !request.matches("[A-Za-z0-9_-]{1,128}")) throw badRequest("运行参数不正确");
        String id = UUID.randomUUID().toString();
        Handle handle = new Handle(id, actor.userId());
        try {
            tx.executeWithoutResult(status -> {
                jdbc.update("""
                    INSERT INTO agent_run(run_id,user_id,session_id,main_agent,entry_point,request_key,status,default_model,
                      policy_version,instance_id,active_slot,last_sequence,started_at,heartbeat_at,lease_expires_at)
                    VALUES (?,?,?,?,?,?,'RUNNING',?,?,?,1,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,?)
                    """, id, actor.userId(), session, main, entry, request, model, POLICY, instance, databaseNow().plusSeconds(90));
                handle.event("RUN_STARTED", Map.of("agent", main, "scope", actor.supervisor() ? "SINGLE_ENTERPRISE" : "OWNED_OR_ASSIGNED", "policyVersion", POLICY));
            });
        } catch (DuplicateKeyException error) { throw new ResponseStatusException(HttpStatus.CONFLICT, "同一会话仍在运行或此请求已提交，请读取已有运行记录"); }
        active.put(id, handle);
        return handle;
    }
    public List<RunView> list(AgentActor actor, String session, String before, int limit) {
        requireEnabled(); limit = bounded(limit); if (session != null && !session.matches("[A-Za-z0-9_.-]{1,128}")) throw badRequest("会话编号不正确");
        String sql = "SELECT * FROM agent_run WHERE user_id=?";
        var args = new ArrayList<Object>(); args.add(actor.userId());
        if (session != null) { sql += " AND session_id=?"; args.add(session); }
        if (before != null) { get(actor, before); sql += " AND id < (SELECT id FROM agent_run WHERE user_id=? AND run_id=?)"; args.add(actor.userId()); args.add(before); }
        sql += " ORDER BY id DESC LIMIT ?"; args.add(limit);
        return jdbc.query(sql, ROW, args.toArray());
    }
    public RunView get(AgentActor actor, String id) {
        requireEnabled(); validateId(id);
        var rows = jdbc.query("SELECT * FROM agent_run WHERE user_id=? AND run_id=?", ROW, actor.userId(), id);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "运行不存在");
        return rows.get(0);
    }
    public List<EventView> events(AgentActor actor, String id, long after, int limit) {
        get(actor,id); if (after < 0) throw badRequest("事件游标不正确");
        return jdbc.query("SELECT sequence_no,event_type,occurred_at,payload_json FROM agent_run_event WHERE user_id=? AND run_id=? AND sequence_no>? ORDER BY sequence_no LIMIT ?",
            (rs,n) -> new EventView(rs.getLong(1),rs.getString(2),rs.getTimestamp(3).toLocalDateTime(),readPayload(rs.getString(4))),actor.userId(),id,after,bounded(limit));
    }
    public RunView cancel(AgentActor actor, String id) {
        var view = get(actor,id); if (!"RUNNING".equals(view.status())) return view;
        Handle handle = active.get(id);
        if (handle == null) throw new ResponseStatusException(HttpStatus.CONFLICT, "当前运行不在此实例，无法确认取消，请稍后读取状态");
        // 只接受服务端保存的取消句柄；客户端不能提交工具结果或恢复参数。
        handle.cancel(); return get(actor,id);
    }
    @Scheduled(fixedDelay = 30000) public void maintainLeases() {
        if (!enabled()) return;
        for (var handle : active.values()) {
            try { if (jdbc.update("UPDATE agent_run SET heartbeat_at=CURRENT_TIMESTAMP,lease_expires_at=? WHERE user_id=? AND run_id=? AND instance_id=? AND status='RUNNING'",
                    databaseNow().plusSeconds(90),handle.userId,handle.id,instance) == 0) handle.cancel(); }
            catch (RuntimeException error) { handle.cancel(); }
        }
        var ids = jdbc.query("SELECT run_id,user_id FROM agent_run WHERE status='RUNNING' AND lease_expires_at<CURRENT_TIMESTAMP ORDER BY lease_expires_at LIMIT 100",
                (rs,n) -> Map.entry(rs.getString(1),rs.getLong(2)));
        for (var id : ids) new Handle(id.getKey(),id.getValue()).expire();
    }
    private class Handle implements Run {
        private final String id; private final long userId; private Runnable cancellation; private boolean closed; private String terminalStatus;
        Handle(String id,long userId) { this.id=id; this.userId=userId; }
        public String id() { return id; }
        public synchronized void event(String type,Map<String,Object> payload) {
            if (closed) throw new IllegalStateException("运行已经结束");
            if (!TYPES.contains(type)) throw badRequest("事件类型未登记");
            String safe = writePayload(payload);
            tx.executeWithoutResult(transaction -> {
                var rows=jdbc.queryForList("SELECT last_sequence,status FROM agent_run WHERE user_id=? AND run_id=? FOR UPDATE",userId,id);
                if (rows.isEmpty() || !"RUNNING".equals(rows.get(0).get("status"))) throw new IllegalStateException("运行已经结束");
                long seq=((Number)rows.get(0).get("last_sequence")).longValue()+1;
                if (seq>2000) throw new IllegalStateException("运行事件预算已耗尽");
                insert(seq,type,safe);
                jdbc.update("UPDATE agent_run SET last_sequence=? WHERE user_id=? AND run_id=?",seq,userId,id);
            });
        }
        private void insert(long seq,String type,String payload) {
            jdbc.update("INSERT INTO agent_run_event(run_id,user_id,sequence_no,event_type,occurred_at,payload_json) VALUES (?,?,?,?,CURRENT_TIMESTAMP,?)",id,userId,seq,type,payload);
        }
        public synchronized void finish(String status) { finishInternal(status,false); }
        private void finishInternal(String status,boolean expiredOnly) {
            if (!TERMINAL.contains(status)) throw new IllegalArgumentException("运行终态不正确");
            if (closed) {
                if ("COMPLETED".equals(status) && !"COMPLETED".equals(terminalStatus)) throw new IllegalStateException("运行已取消或中断");
                return;
            }
            String actual = tx.execute(transaction -> {
                var rows=jdbc.queryForList("SELECT last_sequence,status,lease_expires_at FROM agent_run WHERE user_id=? AND run_id=? FOR UPDATE",userId,id);
                if (rows.isEmpty()) throw new IllegalStateException("运行不存在");
                String current=rows.get(0).get("status").toString();
                if (!"RUNNING".equals(current)) return current;
                Object expiryValue=rows.get(0).get("lease_expires_at");
                LocalDateTime expiry=expiryValue instanceof LocalDateTime date ? date : ((java.sql.Timestamp)expiryValue).toLocalDateTime();
                if (expiredOnly && !expiry.isBefore(databaseNow())) return current;
                long seq=((Number)rows.get(0).get("last_sequence")).longValue()+1;
                insert(seq,"RUN_"+status,"{}");
                jdbc.update("UPDATE agent_run SET status=?,active_slot=NULL,last_sequence=?,ended_at=CURRENT_TIMESTAMP WHERE user_id=? AND run_id=? AND status='RUNNING'",status,seq,userId,id);
                return status;
            });
            if (!"RUNNING".equals(actual)) { closed=true; terminalStatus=actual; active.remove(id,this); }
            if ("COMPLETED".equals(status) && !"COMPLETED".equals(actual)) throw new IllegalStateException("运行已取消或中断");
        }
        synchronized void expire() { finishInternal("INTERRUPTED",true); }
        public synchronized void bindCancel(Runnable cancel) { cancellation=Objects.requireNonNull(cancel); if (closed) cancel.run(); }
        void cancel() {
            Runnable action; synchronized(this) { action=cancellation; }
            if (action == null) throw new ResponseStatusException(HttpStatus.CONFLICT,"运行尚在初始化，请稍后取消");
            action.run();
        }
    }
    private String writePayload(Map<String,Object> payload) {
        if (payload==null || !PAYLOAD.containsAll(payload.keySet())) throw badRequest("事件字段未登记");
        var safe=new LinkedHashMap<String,Object>();
        payload.forEach((key,value)->{
            if (value instanceof String s && s.matches("[A-Za-z0-9_:.-]{1,160}")) safe.put(key,s);
            else if (value instanceof Number n && n.longValue()>=0 && Double.isFinite(n.doubleValue())) safe.put(key,n.longValue());
            else throw badRequest("事件值不符合脱敏规范");
        });
        try { return json.writeValueAsString(safe); } catch (Exception error) { throw new IllegalStateException("事件序列化失败"); }
    }
    private Map<String,Object> readPayload(String value) {
        try { return json.readValue(value,new TypeReference<Map<String,Object>>(){}); }
        catch (Exception error) { throw new IllegalStateException("运行事件格式不正确"); }
    }
    private static final RowMapper<RunView> ROW=(rs,n)->new RunView(rs.getString("run_id"),rs.getString("session_id"),rs.getString("entry_point"),rs.getString("main_agent"),rs.getString("status"),
            rs.getString("default_model"),rs.getString("policy_version"),rs.getTimestamp("started_at").toLocalDateTime(),rs.getTimestamp("ended_at")==null?null:rs.getTimestamp("ended_at").toLocalDateTime(),rs.getLong("last_sequence"));
    private LocalDateTime databaseNow() { return jdbc.queryForObject("SELECT CURRENT_TIMESTAMP", java.sql.Timestamp.class).toLocalDateTime(); }
    private void requireEnabled() { if(!enabled()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"运行日志未启用，请先执行数据库迁移"); }
    private static int bounded(int limit) { if(limit<1||limit>100) throw badRequest("分页大小必须在 1 到 100 之间"); return limit; }
    private static void validateId(String id) { if(id==null||!id.matches("[A-Za-z0-9_-]{1,128}")) throw badRequest("运行编号不正确"); }
    private static ResponseStatusException badRequest(String value) { return new ResponseStatusException(HttpStatus.BAD_REQUEST,value); }
}
