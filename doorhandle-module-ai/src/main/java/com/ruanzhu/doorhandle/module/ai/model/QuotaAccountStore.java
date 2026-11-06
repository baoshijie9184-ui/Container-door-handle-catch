package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Atomic token accounting. The caller owns authentication, the provider protocol and
 * the transaction; these writes never perform network I/O. Lock order is request,
 * provider attempt, MODEL account, then its optional USER account.
 */
final class QuotaAccountStore {
    record Account(long id, String scope, Long owner, String model, String period, Long limit,
                   long reserved, long spent, long version, LocalDateTime expiresAt,long unreconciledLegacyAttempts) {
        Long remaining() { return limit == null ? null : Math.subtractExact(Math.subtractExact(limit, spent), reserved); }
    }
    record Reservation(boolean created, List<Account> accounts) { }
    record Settlement(boolean created, boolean exceedsCurrentLimit, List<Account> accounts) { }
    private record Reserved(Account account, long amount) { }
    private final JdbcTemplate jdbc;

    QuotaAccountStore(JdbcTemplate jdbc) { this.jdbc = Objects.requireNonNull(jdbc); }

    /** A replay returns the original account set; a newly granted personal quota is never charged retroactively. */
    Reservation reserve(long root, long attempt, long owner, String model, long ceiling) {
        if (ceiling <= 0) throw new IllegalArgumentException("A provider attempt needs a positive token ceiling");
        String state = lockOperation(root, attempt, owner, model);
        var previous = reservations(root, attempt, owner, model);
        if (!previous.isEmpty()) {
            for (var entry : previous) if (entry.amount() != ceiling) throw conflict();
            return new Reservation(false, previous.stream().map(Reserved::account).toList());
        }
        if (!"RESERVED".equals(state)) throw new IllegalStateException("Only an undispatched attempt can reserve tokens");
        Account enterprise = lockModel(model);
        var accounts = new ArrayList<Account>(); accounts.add(enterprise);
        var personal = jdbc.query("""
                SELECT * FROM llm_quota WHERE scope_type='USER' AND owner_user_id=?
                    AND model_id=? AND period_key='TOTAL' FOR UPDATE
                """, this::account, owner, enterprise.model());
        accounts.addAll(personal);
        LocalDateTime now = jdbc.queryForObject("SELECT UTC_TIMESTAMP(6)", LocalDateTime.class);
        // Validate both accounts before changing either; all deltas and ledger entries commit together.
        for (var account : accounts) {
            if (account.expiresAt() != null && !account.expiresAt().isAfter(now))
                throw new ModelBudgetService.Exhausted("该模型的额度已到期");
            if (account.limit() != null && account.unreconciledLegacyAttempts() > 0)
                throw new ModelBudgetService.Exhausted("该模型仍有未核实的历史用量，请先完成有审计证据的核对");
            if (account.remaining() != null && account.remaining() < ceiling)
                throw new ModelBudgetService.Exhausted("该模型的可用额度不足以预留本次调用");
            Math.addExact(Math.addExact(account.reserved(), account.spent()), ceiling);
        }
        var after = new ArrayList<Account>();
        for (var account : accounts) {
            updateCounters(account, Math.addExact(account.reserved(), ceiling), account.spent());
            insert(account.id(), root, attempt, "RESERVE", "RESERVE", ceiling, 0, null, null, null,
                    digest("RESERVE", root, attempt, account.id(), ceiling), owner);
            after.add(lockAccount(account.id()));
        }
        return new Reservation(true, List.copyOf(after));
    }

    /**
     * Settle only actual, complete provider usage. Unknown results leave their reservation
     * untouched. An unexpectedly large report is recorded in full and blocks new admission;
     * silently capping it to the reservation would falsify the account.
     */
    Settlement settle(long root, long attempt, long owner, String model, long input, long output, Long cached) {
        if (input < 0 || output < 0 || cached != null && (cached < 0 || cached > input))
            throw new IllegalArgumentException("Invalid provider token report");
        long actual = Math.addExact(input, output);
        String state = lockOperation(root, attempt, owner, model);
        var reserved = reservations(root, attempt, owner, model);
        if (reserved.isEmpty()) throw new IllegalStateException("Provider usage has no reservation to reconcile");
        boolean replay = false, fresh = false, overdrawn = false;
        var after = new ArrayList<Account>();
        for (var entry : reserved) {
            Account account = entry.account();
            String hash = digest("SETTLE", root, attempt, account.id(), input, output, cached, entry.amount());
            var terminal = terminalEntry(account.id(), attempt);
            if (terminal != null) {
                assertEntry(terminal, root, "SETTLE", hash);
                replay = true;
                if (fresh) throw new IllegalStateException("Partially settled account set");
                overdrawn |= account.remaining() != null && account.remaining() < 0;
                after.add(account); continue;
            }
            if (replay) throw new IllegalStateException("Partially settled account set");
            if (!List.of("STARTED", "NEEDS_REVIEW").contains(state))
                throw new IllegalStateException("Usage settlement requires a dispatched or reviewed attempt");
            long remainingReservation = Math.subtractExact(account.reserved(), entry.amount());
            if (remainingReservation < 0) throw new IllegalStateException("Reservation balance is inconsistent");
            long spent = Math.addExact(account.spent(), actual);
            Math.addExact(spent, remainingReservation);
            updateCounters(account, remainingReservation, spent);
            insert(account.id(), root, attempt, "FINAL", "SETTLE", -entry.amount(), actual,
                    input, output, cached, hash, owner);
            var updated = lockAccount(account.id());
            overdrawn |= updated.remaining() != null && updated.remaining() < 0;
            after.add(updated); fresh = true;
        }
        return new Settlement(fresh, overdrawn, List.copyOf(after));
    }

    /** Only a RESERVED attempt may be released; STARTED/timeout/unknown never proves non-dispatch. */
    boolean cancelBeforeDispatch(long root, long attempt, long owner, String model) {
        String state = lockOperation(root, attempt, owner, model);
        var reserved = reservations(root, attempt, owner, model);
        if (reserved.isEmpty()) throw new IllegalStateException("No reservation exists for cancellation");
        boolean fresh = false, replay = false;
        for (var entry : reserved) {
            var account = entry.account();
            String hash = digest("RELEASE", root, attempt, account.id(), entry.amount());
            var terminal = terminalEntry(account.id(), attempt);
            if (terminal != null) {
                assertEntry(terminal, root, "RELEASE", hash);
                if (fresh) throw new IllegalStateException("Partially released account set");
                replay = true; continue;
            }
            if (replay) throw new IllegalStateException("Partially released account set");
            if (!"RESERVED".equals(state)) throw new IllegalStateException("A possibly dispatched request cannot release its reservation");
            long balance = Math.subtractExact(account.reserved(), entry.amount());
            if (balance < 0) throw new IllegalStateException("Reservation balance is inconsistent");
            updateCounters(account, balance, account.spent());
            insert(account.id(), root, attempt, "FINAL", "RELEASE", -entry.amount(), 0,
                    null, null, null, hash, owner);
            fresh = true;
        }
        return fresh;
    }

    private String lockOperation(long root, long attempt, long owner, String model) {
        JdbcTransactions.requireActive(jdbc); model(model);
        if (root <= 0 || attempt <= root || owner <= 0) throw new IllegalArgumentException("Invalid model operation identity");
        var roots = jdbc.queryForList("SELECT kind,owner_user_id,parent_workflow_id FROM workflow_instance WHERE id=? FOR UPDATE", root);
        if (roots.size() != 1 || !"LLM_REQUEST".equals(roots.get(0).get("kind"))
                || number(roots.get(0).get("owner_user_id")) != owner || roots.get(0).get("parent_workflow_id") != null)
            throw new IllegalStateException("LLM request ownership is inconsistent");
        var attempts = jdbc.queryForList("""
                SELECT kind,owner_user_id,parent_workflow_id,resource_type,resource_id,status FROM workflow_instance
                    WHERE id=? AND resource_id=? COLLATE utf8mb4_0900_ai_ci FOR UPDATE
                """, attempt, model);
        if (attempts.size() != 1 || !"LLM_PROVIDER_ATTEMPT".equals(attempts.get(0).get("kind"))
                || number(attempts.get(0).get("owner_user_id")) != owner
                || number(attempts.get(0).get("parent_workflow_id")) != root
                || !"LLM_MODEL".equals(attempts.get(0).get("resource_type")))
            throw new IllegalStateException("Provider attempt ownership/model is inconsistent");
        return Objects.toString(attempts.get(0).get("status"));
    }

    /** Called after the request/attempt lock. The model row serializes all updates for this model. */
    Account lockModel(String model) {
        JdbcTransactions.requireActive(jdbc); model(model);
        jdbc.update("""
                INSERT INTO llm_quota(scope_type,owner_user_id,model_id,period_key,total_tokens,
                    reserved_tokens,spent_tokens,warning_percent,free_only,version,created_at,updated_at)
                VALUES('MODEL',NULL,?,'TOTAL',NULL,0,0,80,TRUE,1,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE id=id
                """, model);
        var rows = jdbc.query("SELECT * FROM llm_quota WHERE scope_type='MODEL' AND subject_key=0 AND model_id=? AND period_key='TOTAL' FOR UPDATE",
                this::account, model);
        if (rows.size() != 1) throw new IllegalStateException("Missing enterprise model account");
        return rows.get(0);
    }

    private List<Reserved> reservations(long root, long attempt, long owner, String model) {
        // Request lock prevents another writer from adding this attempt's ledger concurrently.
        var entries = jdbc.queryForList("""
                SELECT account_id,root_operation_id,reserved_delta,entry_type,request_sha256
                FROM llm_usage WHERE operation_id=? AND entry_key='RESERVE' FOR UPDATE
                """, attempt);
        if (entries.isEmpty()) return List.of();
        // Do not rely on ORDER BY to dictate InnoDB's lock-acquisition order for
        // a joined plan. Take the two account locks explicitly, MODEL before USER.
        var models = jdbc.query("SELECT * FROM llm_quota WHERE scope_type='MODEL' AND subject_key=0 AND model_id=? AND period_key='TOTAL' FOR UPDATE",
                this::account, model);
        if (models.size() != 1) throw new IllegalStateException("Reservation lacks its enterprise account");
        var accounts = new ArrayList<Account>(models);
        accounts.addAll(jdbc.query("SELECT * FROM llm_quota WHERE scope_type='USER' AND owner_user_id=? AND model_id=? AND period_key='TOTAL' FOR UPDATE",
                this::account, owner, model));
        entries.sort(java.util.Comparator.comparingInt(entry -> number(entry.get("account_id")) == models.get(0).id() ? 0 : 1));
        var result = new ArrayList<Reserved>();
        boolean enterprise = false, personal = false;
        for (var entry : entries) {
            Account account = accounts.stream().filter(value -> value.id() == number(entry.get("account_id")))
                    .findFirst().orElseThrow(() -> new IllegalStateException("Reservation references another quota account"));
            long amount = number(entry.get("reserved_delta"));
            if (!"TOTAL".equals(account.period())
                    || !account.model().equalsIgnoreCase(model) || amount <= 0
                    || number(entry.get("root_operation_id")) != root || !"RESERVE".equals(entry.get("entry_type"))
                    || !digest("RESERVE", root, attempt, account.id(), amount).equals(entry.get("request_sha256")))
                throw new IllegalStateException("Reservation ledger identity is inconsistent");
            if ("MODEL".equals(account.scope()) && account.owner() == null && !enterprise) enterprise = true;
            else if ("USER".equals(account.scope()) && Objects.equals(account.owner(), owner) && !personal) personal = true;
            else throw new IllegalStateException("Reservation references an unexpected quota account");
            result.add(new Reserved(account, amount));
        }
        if (!enterprise) throw new IllegalStateException("Reservation lacks its enterprise account");
        return List.copyOf(result);
    }

    private Account lockAccount(long id) {
        var rows = jdbc.query("SELECT * FROM llm_quota WHERE id=? FOR UPDATE", this::account, id);
        if (rows.size() != 1) throw new IllegalStateException("Quota account disappeared");
        return rows.get(0);
    }
    private void updateCounters(Account before, long reserved, long spent) {
        if (jdbc.update("""
                UPDATE llm_quota SET reserved_tokens=?,spent_tokens=?,version=version+1,updated_at=UTC_TIMESTAMP(6)
                WHERE id=? AND version=? AND reserved_tokens=? AND spent_tokens=?
                """, reserved, spent, before.id(), before.version(), before.reserved(), before.spent()) != 1)
            throw new IllegalStateException("Concurrent quota balance change");
    }
    private Map<String,Object> terminalEntry(long account, long attempt) {
        var rows = jdbc.queryForList("SELECT * FROM llm_usage WHERE account_id=? AND operation_id=? AND entry_key='FINAL' FOR UPDATE", account, attempt);
        return rows.isEmpty() ? null : rows.get(0);
    }
    private static void assertEntry(Map<String,Object> entry, long root, String type, String hash) {
        if (number(entry.get("root_operation_id")) != root || !type.equals(entry.get("entry_type"))
                || !hash.equals(entry.get("request_sha256"))) throw conflict();
    }
    private void insert(long account, long root, long attempt, String key, String type, long reserved, long spent,
                        Long input, Long output, Long cached, String hash, long actor) {
        jdbc.update("""
                INSERT INTO llm_usage(account_id,root_operation_id,operation_id,entry_key,entry_type,
                    reserved_delta,spent_delta,input_tokens,output_tokens,cached_tokens,request_sha256,actor_user_id,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,UTC_TIMESTAMP(6))
                """, account, root, attempt, key, type, reserved, spent, input, output, cached, hash, actor);
    }
    private Account account(ResultSet row, int ignored) throws SQLException {
        return new Account(row.getLong("id"), row.getString("scope_type"), row.getObject("owner_user_id", Long.class),
                row.getString("model_id"), row.getString("period_key"), row.getObject("total_tokens", Long.class), row.getLong("reserved_tokens"),
                row.getLong("spent_tokens"), row.getLong("version"), row.getObject("expires_at", LocalDateTime.class),row.getLong("unreconciled_legacy_attempts"));
    }
    private static long number(Object value) {
        if (!(value instanceof Number number)) throw new IllegalStateException("Missing quota identity or amount");
        return number.longValue();
    }
    private static String digest(Object... values) {
        var fields = new String[values.length];
        for (int index=0; index<values.length; index++) fields[index]=values[index]==null ? "NULL" : values[index].toString();
        return ModelConfigurationStore.digest(fields);
    }
    private static void model(String value) {
        ModelBudgetWorkflow.model(value);
    }
    private static IllegalStateException conflict() { return new IllegalStateException("模型额度操作已记录且内容不一致"); }
}
