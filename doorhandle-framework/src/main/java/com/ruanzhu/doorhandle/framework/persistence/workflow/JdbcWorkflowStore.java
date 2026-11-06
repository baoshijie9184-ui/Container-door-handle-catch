package com.ruanzhu.doorhandle.framework.persistence.workflow;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.*;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;

/** Shared operation protocol: typed payloads, durable identities, state transitions and fenced claims. */
public final class JdbcWorkflowStore {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final WorkflowProtocols protocols;

    public JdbcWorkflowStore(JdbcTemplate jdbc, ObjectMapper json) { this(jdbc, json, WorkflowProtocols.defaults()); }
    public JdbcWorkflowStore(JdbcTemplate jdbc, ObjectMapper json, WorkflowProtocols protocols) {
        this.jdbc = Objects.requireNonNull(jdbc); this.json = Objects.requireNonNull(json);
        this.protocols = Objects.requireNonNull(protocols);
    }
    public void validateSchema() {
        jdbc.queryForList("SELECT workflow_id,kind,idempotency_scope,request_id,request_sha256,parent_workflow_id,"
                + "status,revision,fence,claim_token,report_request_id,report_consumed_id,model_probe_id,file_delivery_scope,file_delivery_domain,requested_tokens,decider_user_id,result_sha256,payload_version,payload_json FROM workflow_instance WHERE 1=0");
    }
    public LocalDateTime now() { return jdbc.queryForObject("SELECT UTC_TIMESTAMP(6)", LocalDateTime.class); }
    public <P> P payload(WorkflowRecord record, Class<P> type) {
        var protocol = protocols.require(record.kind());
        if (protocol.payloadType() != type) throw new IllegalArgumentException("Payload type differs from registered workflow protocol");
        try {
            P value = json.readValue(record.payloadJson(), type);
            protocol.validatePayload(value, record.payloadVersion()); return value;
        } catch (JsonProcessingException error) { throw new IllegalStateException("Stored workflow payload is invalid", error); }
    }
    public Optional<WorkflowRecord> find(WorkflowKind kind, String workflowId) {
        return first(jdbc.query("SELECT * FROM workflow_instance WHERE kind=? AND "+workflowColumn(kind)+"=?", this::map, kind.name(), workflowId));
    }
    public Optional<WorkflowRecord> findLocked(WorkflowKind kind,String workflowId) {
        JdbcTransactions.requireActive(jdbc);
        return first(jdbc.query("SELECT * FROM workflow_instance WHERE kind=? AND "+workflowColumn(kind)+"=? FOR UPDATE",this::map,kind.name(),workflowId));
    }
    public Optional<WorkflowRecord> findReceipt(WorkflowKind kind, long actorId, String requestId, String digest) {
        var value = findByRequest(kind, ownerScope(actorId), requestId);
        value.ifPresent(existing -> sameRequest(existing, digest)); return value;
    }
    public Optional<WorkflowRecord> findByRequest(WorkflowKind kind, String scope, String requestId) {
        return first(jdbc.query("SELECT * FROM workflow_instance WHERE kind=? AND " + scopeColumn(kind) + "=? AND " + requestColumn(kind) + "=?",
                this::map, kind.name(), scope, requestId));
    }
    public Optional<WorkflowRecord> findByRequestLocked(WorkflowKind kind,String scope,String requestId) {
        JdbcTransactions.requireActive(jdbc);
        return first(jdbc.query("SELECT * FROM workflow_instance WHERE kind=? AND "+scopeColumn(kind)+"=? AND "+requestColumn(kind)+"=? FOR UPDATE",
                this::map,kind.name(),scope,requestId));
    }
    public WorkflowRecord saveReceipt(WorkflowKind kind, long actorId, String requestId, String digest,
                                      String resourceId, long resourceRevision, Object typedPayload) {
        return create(new WorkflowDraft(UUID.randomUUID().toString(), kind, ownerScope(actorId), requestId,
                digest, actorId, actorId, null, kind == WorkflowKind.KNOWLEDGE_COMMAND ? "KNOWLEDGE" : "SESSION",
                resourceId, resourceRevision, null, null, "COMPLETED", null, 1, typedPayload));
    }
    public WorkflowRecord create(WorkflowDraft draft) {
        return create(draft, new WorkflowTiming(null,null));
    }
    public WorkflowRecord create(WorkflowDraft draft, WorkflowTiming timing) {
        JdbcTransactions.requireActive(jdbc);
        validateDraft(draft);
        var previous = findByRequest(draft.kind(), draft.idempotencyScope(), draft.requestId());
        if (previous.isPresent()) { sameRequest(previous.get(), draft.requestSha256()); return previous.get(); }
        String payload = encode(draft.payload());
        try {
            jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,
                  owner_user_id,actor_user_id,parent_workflow_id,resource_type,resource_id,resource_revision,
                  session_id,run_id,status,expires_at,payload_version,payload_json,effective_date,scheduled_for,created_at,updated_at,finished_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),
                  CASE WHEN ? THEN UTC_TIMESTAMP(6) ELSE NULL END)
                """, draft.workflowId(), draft.kind().name(), draft.idempotencyScope(), draft.requestId(),
                    draft.requestSha256(), draft.ownerUserId(), draft.actorUserId(), draft.parentWorkflowId(),
                    draft.resourceType(), draft.resourceId(), draft.resourceRevision(), draft.sessionId(), draft.runId(),
                    draft.initialState(), draft.expiresAt(), draft.payloadVersion(), payload,timing.effectiveDate(),timing.scheduledFor(),
                    protocols.require(draft.kind()).terminalStates().contains(draft.initialState()));
        } catch (DuplicateKeyException duplicate) {
            // Resolve only the intended idempotency key. Other unique conflicts remain errors.
            var winner = first(jdbc.query("SELECT * FROM workflow_instance WHERE kind=? AND "+scopeColumn(draft.kind())+"=? AND "+requestColumn(draft.kind())+"=? FOR UPDATE",
                    this::map,draft.kind().name(),draft.idempotencyScope(),draft.requestId()));
            if (winner.isEmpty()) throw duplicate;
            sameRequest(winner.get(), draft.requestSha256()); return winner.get();
        }
        return find(draft.kind(), draft.workflowId()).orElseThrow();
    }
    /** Compare-and-swap before a worker claim. A claimed operation requires its fencing token. */
    public WorkflowRecord transition(WorkflowRecord before, String state, Object payload, String runId,
                                     Integer activeSlot, LocalDateTime expiresAt) {
        JdbcTransactions.requireActive(jdbc);
        if (before.claimToken() != null) throw new WorkflowConflictException("Claimed workflow requires its fencing token");
        validateTransition(before, state, payload);
        int changed = jdbc.update("""
                UPDATE workflow_instance SET status=?,payload_json=?,run_id=?,active_slot=?,expires_at=?,
                  revision=revision+1,updated_at=UTC_TIMESTAMP(6),
                  finished_at=CASE WHEN ? THEN UTC_TIMESTAMP(6) ELSE NULL END
                WHERE id=? AND revision=? AND fence=? AND status=? AND claim_token IS NULL
                """, state, encode(payload), runId, activeSlot, expiresAt,
                protocols.require(before.kind()).terminalStates().contains(state), before.id(), before.revision(), before.fence(), before.status());
        return changed(before, changed);
    }
    public WorkflowRecord claim(WorkflowRecord before, String state, Object payload, String runId,
                                LocalDateTime expiresAt, Duration lease) {
        JdbcTransactions.requireActive(jdbc); validateTransition(before, state, payload);
        if (before.claimToken() != null || lease == null || lease.isNegative() || lease.isZero())
            throw new WorkflowConflictException("Workflow is already claimed or lease is invalid");
        String token = UUID.randomUUID().toString();
        int changed = jdbc.update("""
                UPDATE workflow_instance SET status=?,payload_json=?,run_id=?,active_slot=?,expires_at=?,
                  claim_token=?,lease_expires_at=?,fence=fence+1,attempts=attempts+1,
                  revision=revision+1,updated_at=UTC_TIMESTAMP(6)
                WHERE id=? AND revision=? AND fence=? AND status=? AND claim_token IS NULL
                  AND (expires_at IS NULL OR expires_at>UTC_TIMESTAMP(6))
                """, state, encode(payload), runId, before.kind() == WorkflowKind.CONVERSATION_INPUT ? 1 : null,
                expiresAt, token, now().plus(lease), before.id(), before.revision(), before.fence(), before.status());
        return changed(before, changed);
    }
    /** A stale worker cannot confirm a newer claim, even after reading the newest record. */
    public WorkflowRecord finishClaim(WorkflowRecord claimed, String state, Object payload, Object result) {
        String body=result==null?null:encode(result);
        return finishClaimJson(claimed,state,payload,body==null?null:1,body,body==null?null:sha(body),null);
    }
    public WorkflowRecord finishClaimJson(WorkflowRecord claimed,String state,Object payload,Integer resultVersion,
                                          String resultJson,String resultSha256,String errorCode) {
        JdbcTransactions.requireActive(jdbc); validateTransition(claimed, state, payload);
        if (claimed.claimToken() == null) throw new WorkflowConflictException("Missing workflow claim");
        if (!protocols.require(claimed.kind()).terminalStates().contains(state))
            throw new IllegalArgumentException("Claim completion requires a terminal state");
        if((resultJson==null)!=(resultVersion==null)||(resultJson==null)!=(resultSha256==null))
            throw new IllegalArgumentException("Incomplete workflow result receipt");
        if(resultJson!=null) {
            if(resultVersion!=1||!Objects.equals(sha(resultJson),resultSha256))
                throw new IllegalArgumentException("Invalid workflow result version or digest");
            try { if(json.readTree(resultJson)==null)throw new IllegalArgumentException("Empty workflow result"); }
            catch(JsonProcessingException error){throw new IllegalArgumentException("Invalid workflow result JSON",error);}
        }
        if(errorCode!=null&&(errorCode.isBlank()||errorCode.length()>80))throw new IllegalArgumentException("Invalid workflow error code");
        int changed = jdbc.update("""
                UPDATE workflow_instance SET status=?,payload_json=?,result_version=?,result_json=?,result_sha256=?,error_code=?,
                  active_slot=NULL,claim_token=NULL,lease_expires_at=NULL,revision=revision+1,
                  updated_at=UTC_TIMESTAMP(6),finished_at=UTC_TIMESTAMP(6)
                WHERE id=? AND revision=? AND fence=? AND claim_token=? AND status=?
                  AND lease_expires_at>UTC_TIMESTAMP(6)
                  AND (expires_at IS NULL OR expires_at>UTC_TIMESTAMP(6))
                """, state, encode(payload), resultVersion,resultJson,resultSha256,errorCode,
                claimed.id(), claimed.revision(), claimed.fence(), claimed.claimToken(), claimed.status());
        return changed(claimed, changed);
    }
    /** Release a live claim into a registered retry or terminal state without weakening fencing. */
    public WorkflowRecord releaseClaim(WorkflowRecord claimed,String state,Object payload,String errorCode,
                                       LocalDateTime nextAttemptAt) {
        JdbcTransactions.requireActive(jdbc); validateTransition(claimed,state,payload);
        if(claimed.claimToken()==null)throw new WorkflowConflictException("Missing workflow claim");
        if(errorCode!=null&&(errorCode.isBlank()||errorCode.length()>80))throw new IllegalArgumentException("Invalid workflow error code");
        boolean terminal=protocols.require(claimed.kind()).terminalStates().contains(state);
        if(terminal&&nextAttemptAt!=null)throw new IllegalArgumentException("Terminal workflow cannot be rescheduled");
        int count=jdbc.update("""
                UPDATE workflow_instance SET status=?,payload_json=?,error_code=?,next_attempt_at=?,active_slot=NULL,
                  claim_token=NULL,lease_expires_at=NULL,revision=revision+1,updated_at=UTC_TIMESTAMP(6),
                  finished_at=CASE WHEN ? THEN UTC_TIMESTAMP(6) ELSE NULL END
                WHERE id=? AND revision=? AND fence=? AND claim_token=? AND status=?
                  AND lease_expires_at>UTC_TIMESTAMP(6) AND (expires_at IS NULL OR expires_at>UTC_TIMESTAMP(6))
                """,state,encode(payload),errorCode,nextAttemptAt,terminal,
                claimed.id(),claimed.revision(),claimed.fence(),claimed.claimToken(),claimed.status());
        return changed(claimed,count);
    }
    /** Only protocols declaring replay safety may reclaim an expired lease. */
    public WorkflowRecord reclaim(WorkflowRecord before,String state,Object payload,String runId,
                                   LocalDateTime expiresAt,Duration lease) {
        JdbcTransactions.requireActive(jdbc);validateTransition(before,state,payload);
        if(!protocols.require(before.kind()).reclaimable()||before.claimToken()==null||lease==null||lease.isZero()||lease.isNegative())
            throw new WorkflowConflictException("This workflow cannot be reclaimed");
        int count=jdbc.update("""
                UPDATE workflow_instance SET status=?,payload_json=?,run_id=?,expires_at=?,claim_token=?,lease_expires_at=?,
                  fence=fence+1,attempts=attempts+1,revision=revision+1,updated_at=UTC_TIMESTAMP(6)
                WHERE id=? AND revision=? AND fence=? AND claim_token=? AND status=? AND lease_expires_at<=UTC_TIMESTAMP(6)
                  AND (expires_at IS NULL OR expires_at>UTC_TIMESTAMP(6))
                """,state,encode(payload),runId,expiresAt,UUID.randomUUID().toString(),now().plus(lease),
                before.id(),before.revision(),before.fence(),before.claimToken(),before.status());
        return changed(before,count);
    }
    /** Inbox expiry invalidates a claim; it does not release unverified external-process capacity. */
    public WorkflowRecord expireConversationInput(WorkflowRecord before, WorkflowPayloads.ConversationInputV1 payload) {
        JdbcTransactions.requireActive(jdbc);
        if (before.kind() != WorkflowKind.CONVERSATION_INPUT) throw new IllegalArgumentException("Not an inbox operation");
        validateTransition(before, "EXPIRED", payload);
        int changed = jdbc.update("""
                UPDATE workflow_instance SET status='EXPIRED',payload_json=?,active_slot=NULL,claim_token=NULL,
                  lease_expires_at=NULL,fence=fence+1,revision=revision+1,updated_at=UTC_TIMESTAMP(6),finished_at=UTC_TIMESTAMP(6)
                WHERE id=? AND revision=? AND fence=? AND status=? AND expires_at<=UTC_TIMESTAMP(6)
                """, encode(payload), before.id(), before.revision(), before.fence(), before.status());
        return changed(before, changed);
    }
    public List<WorkflowRecord> list(WorkflowKind kind, Long owner, String session, String run,
                                     Set<String> states, boolean unexpired, int limit, boolean oldestFirst) {
        if (limit < 1 || limit > 1000) throw new IllegalArgumentException("Invalid workflow page size");
        var args = new ArrayList<Object>(); var where = filters(kind, owner, session, run, states, args);
        if (unexpired) where += " AND (expires_at IS NULL OR expires_at>UTC_TIMESTAMP(6))";
        args.add(limit);
        return jdbc.query("SELECT * FROM workflow_instance WHERE " + where + " ORDER BY id "
                + (oldestFirst ? "ASC" : "DESC") + " LIMIT ?", this::map, args.toArray());
    }
    public long count(WorkflowKind kind, Long owner, String session, String run, Set<String> states) {
        var args = new ArrayList<Object>(); String where = filters(kind, owner, session, run, states, args);
        return jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE " + where, Long.class, args.toArray());
    }
    public long maxOwner(WorkflowKind kind, String state) {
        return jdbc.queryForObject("SELECT COALESCE(MAX(owner_user_id),0) FROM workflow_instance WHERE kind=? AND status=?",
                Long.class, kind.name(), state);
    }
    public List<Long> ownersAfter(WorkflowKind kind, String state, long after, long maximum, int limit) {
        if (limit < 1 || limit > 1000) throw new IllegalArgumentException("Invalid owner page size");
        return jdbc.queryForList("SELECT DISTINCT owner_user_id FROM workflow_instance WHERE kind=? AND status=? "
                + "AND owner_user_id>? AND owner_user_id<=? ORDER BY owner_user_id LIMIT ?",
                Long.class, kind.name(), state, after, maximum, limit);
    }
    public List<WorkflowRecord> expired(WorkflowKind kind, Set<String> states, int limit) {
        if (limit < 1 || limit > 1000) throw new IllegalArgumentException("Invalid expiry page size");
        var args = new ArrayList<Object>(); String where = filters(kind, null, null, null, states, args); args.add(limit);
        return jdbc.query("SELECT * FROM workflow_instance WHERE " + where
                + " AND expires_at<=UTC_TIMESTAMP(6) ORDER BY id LIMIT ?", this::map, args.toArray());
    }
    private String filters(WorkflowKind kind, Long owner, String session, String run, Set<String> states, List<Object> args) {
        StringBuilder sql = new StringBuilder("kind=?"); args.add(kind.name());
        if (owner != null) { sql.append(" AND owner_user_id=?"); args.add(owner); }
        if (session != null) { sql.append(" AND session_id=?"); args.add(session); }
        if (run != null) { sql.append(" AND run_id=?"); args.add(run); }
        if (states != null && !states.isEmpty()) {
            sql.append(" AND status IN (").append(String.join(",", Collections.nCopies(states.size(), "?"))).append(")");
            args.addAll(states);
        }
        return sql.toString();
    }
    private static String scopeColumn(WorkflowKind kind) {
        return switch (kind) {
            case DIGEST_COMMAND, DIGEST_RUN -> "digest_scope";
            default -> "idempotency_scope";
        };
    }
    private static String workflowColumn(WorkflowKind kind) {
        return kind == WorkflowKind.DIGEST_RUN ? "digest_workflow_id" : "workflow_id";
    }
    private static String requestColumn(WorkflowKind kind) {
        return switch(kind) {
            case DIGEST_COMMAND, DIGEST_RUN -> "digest_request_id";
            case KNOWLEDGE_COMMAND -> "knowledge_request_id";
            case REPORT_COMMAND,REPORT_CONFIRMATION,REPORT_DELIVERY,REPORT_CONSUMPTION,REPORT_AGENT_ORIGIN -> "report_request_id";
            default -> "request_id";
        };
    }
    private void validateDraft(WorkflowDraft value) {
        Objects.requireNonNull(value); WorkflowPayloads.text(value.workflowId(), 64, "workflowId");
        WorkflowPayloads.text(value.idempotencyScope(), 160, "idempotencyScope");
        WorkflowPayloads.text(value.requestId(), 128, "requestId");
        if (value.ownerUserId() <= 0 || value.requestSha256() == null || !value.requestSha256().matches("[a-f0-9]{64}"))
            throw new IllegalArgumentException("Invalid workflow owner/request digest");
        if(Set.of(WorkflowKind.KNOWLEDGE_COMMAND,WorkflowKind.SKILL_DOWNLOAD,WorkflowKind.SKILL_STORAGE_COMMAND).contains(value.kind())&&value.requestId().length()>64)
            throw new IllegalArgumentException("Workflow request ID exceeds its original limit");
        var protocol = protocols.require(value.kind()); protocol.requireInitial(value.initialState());
        protocol.validatePayload(value.payload(), value.payloadVersion());
        if (value.kind() == WorkflowKind.CONVERSATION_INPUT) {
            WorkflowPayloads.text(value.sessionId(), 128, "sessionId");
            if (value.expiresAt() == null || ((WorkflowPayloads.ConversationInputV1)value.payload()).content().isBlank())
                throw new IllegalArgumentException("Conversation input requires content and deadline");
        }
    }
    private void validateTransition(WorkflowRecord before, String state, Object payload) {
        var protocol = protocols.require(before.kind()); protocol.requireTransition(before.status(), state);
        protocol.validatePayload(payload, before.payloadVersion());
    }
    private WorkflowRecord changed(WorkflowRecord before, int changed) {
        if (changed != 1) throw new WorkflowConflictException("Workflow revision, claim or deadline changed");
        return find(before.kind(), before.workflowId()).orElseThrow();
    }
    private void sameRequest(WorkflowRecord record, String digest) {
        if (digest == null || !Objects.equals(record.requestSha256(), digest))
            throw new WorkflowConflictException("Request identity was already used for different content");
    }
    private String encode(Object value) {
        try { return json.writeValueAsString(value); }
        catch (JsonProcessingException error) { throw new IllegalArgumentException("Cannot encode workflow payload", error); }
    }
    public static String ownerScope(long owner) {
        if (owner <= 0) throw new IllegalArgumentException("Workflow owner must be positive"); return "OWNER:" + owner;
    }
    private static <T> Optional<T> first(List<T> values) { return values.isEmpty() ? Optional.empty() : Optional.of(values.get(0)); }
    private WorkflowRecord map(ResultSet r, int ignored) throws SQLException {
        return new WorkflowRecord(r.getLong("id"),r.getString("workflow_id"),WorkflowKind.valueOf(r.getString("kind")),
                r.getString("idempotency_scope"),r.getString("request_id"),r.getString("request_sha256"),r.getLong("owner_user_id"),
                nullableLong(r,"actor_user_id"),nullableLong(r,"parent_workflow_id"),r.getString("resource_type"),r.getString("resource_id"),
                nullableLong(r,"resource_revision"),r.getString("session_id"),r.getString("run_id"),r.getString("status"),r.getLong("revision"),
                r.getLong("fence"),r.getObject("active_slot") == null ? null : r.getInt("active_slot"),r.getString("claim_token"),
                time(r,"lease_expires_at"),time(r,"expires_at"),r.getInt("payload_version"),r.getString("payload_json"),r.getString("result_json"),
                time(r,"created_at"),time(r,"updated_at"),time(r,"finished_at"),r.getString("result_sha256"),r.getString("error_code"),
                r.getObject("effective_date",java.time.LocalDate.class),time(r,"scheduled_for"));
    }
    private static String sha(String value) {
        try{return HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));}
        catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}
    }
    private static Long nullableLong(ResultSet r,String column) throws SQLException { long value=r.getLong(column); return r.wasNull()?null:value; }
    private static LocalDateTime time(ResultSet r,String column) throws SQLException { return r.getObject(column,LocalDateTime.class); }
}
