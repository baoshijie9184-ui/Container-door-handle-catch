package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcWorkflowStore;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind;
import java.util.List;
import java.util.Objects;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

/** ModelBudgetService calls admission and finalization inside the same transaction as its token receipts. */
@Service
@ConditionalOnProperty(prefix="app.model-budget",name={"enabled","provider-limits"},havingValue="true")
@Transactional(isolation=Isolation.READ_COMMITTED,rollbackFor=Exception.class)
public class ProviderBudgetService {
    static final String POOL="NATIVE_POOL", MEMBER="NATIVE_MEMBER", RATE="NATIVE_RATE";
    private static final BigDecimal ZERO=BigDecimal.ZERO;
    private final JdbcTemplate jdbc;
    private final BusinessUserDirectory users;
    private final ObjectMapper json;

    public ProviderBudgetService(JdbcTemplate jdbc,BusinessUserDirectory users,ObjectMapper mapper) {
        this.jdbc=jdbc; this.users=users;
        this.json=mapper.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS);
    }
    @jakarta.annotation.PostConstruct
    public void verifySchema() {
        jdbc.queryForList("SELECT native_unit,native_limit,native_opening_used,native_reserved,native_spent,native_rates FROM llm_quota WHERE 1=0");
        jdbc.queryForList("SELECT native_reserved_delta,native_spent_delta,native_detail,native_command FROM llm_usage WHERE 1=0");
    }
    public record Policy(String kind,String model,Long employeeId,BigDecimal limit,BigDecimal openingUsed,
                         BigDecimal input,BigDecimal cached,BigDecimal output,long expectedVersion,String requestId) {}
    public record Account(long id,String kind,String key,Long employeeId,String unit,String limit,String openingUsed,
                          String spent,String reserved,String available,long version,ProviderMeter.Rate rates) {}
    public record Employee(long id,String name) {}
    public record Usage(long attempt,String model,String unit,String held,String cost,String status,String basis,
                        Long inputTokens,Long outputTokens,Long cachedTokens,String time) {}
    public record View(List<Account> accounts,List<Usage> usage) {}
    public record Review(@com.fasterxml.jackson.databind.annotation.JsonDeserialize(using=PersonalModelQuotaService.ExactInteger.class) Long input,
                         @com.fasterxml.jackson.databind.annotation.JsonDeserialize(using=PersonalModelQuotaService.ExactInteger.class) Long output,
                         @com.fasterxml.jackson.databind.annotation.JsonDeserialize(using=PersonalModelQuotaService.ExactInteger.class) Long cached,BigDecimal amount,String reference,String requestId) {}
    record Verified(long supervisor,String reference,String requestId,String amount,long input,long output,Long cached) {}
    record Snapshot(String model,String unit,ProviderMeter.Rate rate) {}
    record Hold(long account,BigDecimal amount,Snapshot snapshot) {}

    private String encode(Object value) {
        try {return json.writeValueAsString(value);} catch(Exception e){throw new IllegalStateException("额度回执写入失败",e);}
    }
    private <T> T decode(String text,Class<T> type) {
        try {return json.readValue(text,type);} catch(Exception e){throw new IllegalStateException("额度回执格式错误",e);}
    }
    static String decimal(BigDecimal amount) {
        return amount==null?null:amount.stripTrailingZeros().toPlainString();
    }
    private Account account(ResultSet r,int index) throws SQLException {
        BigDecimal limit=r.getBigDecimal("native_limit"), opening=r.getBigDecimal("native_opening_used"),
                spent=r.getBigDecimal("native_spent"), held=r.getBigDecimal("native_reserved");
        String rates=r.getString("native_rates");
        return new Account(r.getLong("id"),r.getString("period_key"),r.getString("model_id"),r.getObject("owner_user_id",Long.class),
                r.getString("native_unit"),decimal(limit),decimal(opening),decimal(spent),decimal(held),
                limit==null?null:decimal(limit.subtract(opening).subtract(spent).subtract(held)),r.getLong("version"),
                rates==null?null:decode(rates,ProviderMeter.Rate.class));
    }
    private Account lock(String kind,String key,long owner) {
        var rows=jdbc.query("SELECT * FROM llm_quota WHERE scope_type=? AND subject_key=? AND model_id=? AND period_key=? FOR UPDATE",
                this::account,owner==0?"MODEL":"USER",owner,key,kind);
        return rows.isEmpty()?null:rows.get(0);
    }
    private BusinessUserDirectory.Identity actor() {
        var who=users.authenticated();
        return users.current(who.userId(),who.username());
    }
    private static void requireSupervisor(BusinessUserDirectory.Identity who) {
        if(!who.supervisor()) throw new BusinessException(403,"仅主管可管理员工额度");
    }
    public List<Employee> employees(String query,long after) {
        requireSupervisor(actor());
        if(query.length()>50 || after<0) throw new BusinessException(400,"员工查询条件无效");
        return jdbc.query("SELECT id,username FROM users WHERE enabled=TRUE AND role NOT IN ('SUPERVISOR','ADMIN') AND id>? AND LOCATE(?,username)>0 ORDER BY id LIMIT 51",
                (r,i)->new Employee(r.getLong(1),r.getString(2)),after,query);
    }
    public View view(Long employee,long before,boolean pending) {
        var who=actor();
        long owner=employee==null?who.userId():employee;
        if(owner!=who.userId()) requireSupervisor(who);
        if(owner<1 || before<1) throw new BusinessException(400,"员工编号无效");
        String visible=who.supervisor()?"period_key IN ('NATIVE_POOL','NATIVE_RATE') OR ":"";
        var list=jdbc.query("SELECT * FROM llm_quota WHERE "+visible+"(period_key='NATIVE_MEMBER' AND owner_user_id=?) ORDER BY model_id,period_key",this::account,owner);
        // Only the company-side receipt is counted. Member and pool entries describe the same call.
        var usage=jdbc.query("""
                SELECT h.operation_id,w.resource_id,h.native_reserved_delta,f.native_spent_delta,
                       q.native_unit,CASE WHEN w.status='STARTED' AND w.updated_at<UTC_TIMESTAMP(6)-INTERVAL 1 DAY THEN 'STALE' ELSE w.status END,f.input_tokens,f.output_tokens,f.cached_tokens,h.created_at,f.entry_type,JSON_EXTRACT(f.native_detail,'$.reference')
                FROM llm_usage h JOIN llm_quota q ON q.id=h.account_id
                JOIN workflow_instance w ON w.id=h.operation_id
                LEFT JOIN llm_usage f ON f.account_id=h.account_id AND f.operation_id=h.operation_id AND f.entry_key='NATIVE:FINAL'
                WHERE q.period_key='NATIVE_POOL' AND h.actor_user_id=? AND h.entry_key='NATIVE:HOLD' AND h.operation_id<?
                  AND (?=FALSE OR (f.id IS NULL AND (w.status<>'STARTED' OR w.updated_at<UTC_TIMESTAMP(6)-INTERVAL 1 DAY)))
                ORDER BY h.operation_id DESC LIMIT 50
                """,(r,i)->new Usage(r.getLong(1),r.getString(2),r.getString(5),decimal(r.getBigDecimal(3)),
                        decimal(r.getBigDecimal(4)),r.getString(11)!=null?r.getString(11):
                        "STARTED".equals(r.getString(6))?"IN_PROGRESS":"NEEDS_REVIEW",
                        r.getString(11)==null?null:r.getString(12)!=null?"BILL":r.getString(5).equals("TOKEN")?"USAGE":"TARIFF",
                        r.getObject(7,Long.class),r.getObject(8,Long.class),r.getObject(9,Long.class),r.getTimestamp(10).toLocalDateTime()+"Z"),owner,before,pending);
        return new View(list,usage);
    }
    public void configure(Policy p) {
        var auth=actor(); requireSupervisor(auth);
        if(p==null || p.kind()==null || !List.of(POOL,MEMBER,RATE).contains(p.kind()) || p.model()==null
                || p.requestId()==null || !p.requestId().matches("[a-zA-Z0-9_-]{8,128}") || p.expectedVersion()<0)
            throw new BusinessException(400,"额度配置参数无效");
        String vendor=ProviderMeter.provider(p.model()),unit=ProviderMeter.unit(vendor);
        long owner=p.employeeId()==null?0:p.employeeId();
        if(MEMBER.equals(p.kind()) ? owner<=0 : p.employeeId()!=null) throw new BusinessException(400,"员工与额度类型不匹配");
        String key=RATE.equals(p.kind())?p.model():ProviderMeter.pool(p.model());
        ProviderMeter.Rate rate=null;
        if(RATE.equals(p.kind())) {
            if(unit.equals("TOKEN") || p.limit()!=null || p.openingUsed()!=null) throw new BusinessException(400,"只有金额模型需要单价");
            rate=new ProviderMeter.Rate(p.input(),p.cached(),p.output());
        } else {
            ProviderMeter.amount(p.limit(),unit);
            if(p.input()!=null || p.cached()!=null || p.output()!=null) throw new BusinessException(400,"额度不包含单价");
            if(POOL.equals(p.kind())) ProviderMeter.amount(p.openingUsed(),unit);
            else if(p.openingUsed()!=null) throw new BusinessException(400,"员工额度不能设置历史用量");
        }
        if(owner!=0) {
            var ids=jdbc.queryForList("SELECT id FROM users WHERE id IN (?,?) ORDER BY id FOR UPDATE",Long.class,owner,auth.userId());
            if(!ids.contains(owner)) throw new BusinessException(404,"员工账号不存在");
        }
        requireSupervisor(users.lockCurrent(auth.userId(),auth.username()));
        if(owner!=0 && jdbc.queryForObject("SELECT COUNT(*) FROM users WHERE id=? AND enabled=TRUE AND role NOT IN ('SUPERVISOR','ADMIN')",Long.class,owner)!=1)
            throw new BusinessException(400,"只能给启用的员工账号分配额度");
        String digest=ModelConfigurationStore.digest(p.kind(),key,Long.toString(owner),encode(p));
        var existing=jdbc.queryForList("SELECT request_sha256 FROM llm_usage WHERE actor_user_id=? AND native_command=?",String.class,auth.userId(),p.requestId());
        if(!existing.isEmpty()) {
            if(!digest.equals(existing.get(0))) throw new BusinessException(409,"请求编号已用于其他额度修改");
            return;
        }
        BigDecimal opening=POOL.equals(p.kind())?p.openingUsed():ZERO;
        // Insert a fully valid placeholder only within the transaction; a failed CAS rolls it back.
        jdbc.update("""
                INSERT INTO llm_quota(scope_type,owner_user_id,model_id,period_key,native_unit,native_limit,native_opening_used,
                    native_rates,version,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE id=id
                """,owner==0?"MODEL":"USER",owner==0?null:owner,key,p.kind(),unit,p.limit(),opening,rate==null?null:encode(rate));
        var before=Objects.requireNonNull(lock(p.kind(),key,owner));
        if(before.version()!=p.expectedVersion()) throw new BusinessException(409,"额度配置已更新，请刷新核对");
        if(before.version()>0 && opening.compareTo(new BigDecimal(before.openingUsed()))!=0)
            throw new BusinessException(409,"期初已用已登记，不能覆盖历史消耗");
        if(p.limit()!=null && p.limit().compareTo(opening.add(new BigDecimal(before.spent())).add(new BigDecimal(before.reserved())))<0)
            throw new BusinessException(409,"新限额低于已用与预留之和");
        jdbc.update("""
                UPDATE llm_quota SET native_limit=?,native_rates=?,updated_by=?,version=version+1,updated_at=UTC_TIMESTAMP(6) WHERE id=?
                """,p.limit(),rate==null?null:encode(rate),auth.userId(),before.id());
        jdbc.update("""
                INSERT INTO llm_usage(account_id,entry_key,entry_type,request_sha256,actor_user_id,native_command,native_detail,created_at)
                VALUES(?,'NATIVE:POLICY','NATIVE_POLICY',?,?,?,?,UTC_TIMESTAMP(6))
                """,before.id(),digest,auth.userId(),p.requestId(),encode(p));
    }

    void hold(long root,long attempt,BusinessUserDirectory.Identity who,String model,long ceiling) {
        String vendor=ProviderMeter.provider(model),unit=ProviderMeter.unit(vendor);
        var pool=lock(POOL,ProviderMeter.pool(model),0);
        Account member=who.supervisor()?null:lock(MEMBER,ProviderMeter.pool(model),who.userId());
        if(!who.supervisor() && member==null) throw exhausted("请先由主管分配该员工的调用限额");
        if(pool==null) throw exhausted("主管尚未登记该厂家的模型预算");
        ProviderMeter.Rate rate=null;
        if(!unit.equals("TOKEN")) {
            var configured=lock(RATE,model,0);
            if(configured==null) throw exhausted("请先登记该模型的计费单价");
            rate=configured.rates();
        }
        BigDecimal amount=rate==null?BigDecimal.valueOf(ceiling):rate.hold(ceiling);
        var snapshot=new Snapshot(model,unit,rate);
        for(Account a : member==null?List.of(pool):List.of(pool,member)) {
            if(!unit.equals(a.unit())) throw new IllegalStateException("额度单位不一致");
            if(new BigDecimal(a.available()).compareTo(amount)<0) throw exhausted(a==pool?"厂家可用额度不足":"员工可用限额不足");
            jdbc.update("UPDATE llm_quota SET native_reserved=native_reserved+? WHERE id=?",amount,a.id());
            ledger(a.id(),root,attempt,who.userId(),"NATIVE:HOLD","NATIVE_HOLD",amount,ZERO,null,null,null,encode(snapshot));
        }
    }
    private static ModelBudgetService.Exhausted exhausted(String message) {return new ModelBudgetService.Exhausted(message);}
    private List<Hold> holds(long attempt) {
        return jdbc.query("""
                SELECT h.account_id,h.native_reserved_delta,h.native_detail FROM llm_usage h JOIN llm_quota q ON h.account_id=q.id
                WHERE h.operation_id=? AND h.entry_key='NATIVE:HOLD' ORDER BY (q.period_key='NATIVE_POOL') DESC,h.id
                """,(r,i)->new Hold(r.getLong(1),r.getBigDecimal(2),decode(r.getString(3),Snapshot.class)),attempt);
    }
    void settle(long root,long attempt,long owner,long in,long out,Long cached) {
        var rows=holds(attempt);
        if(rows.isEmpty()) return; // Pre-activation reservation.
        var pricing=rows.get(0).snapshot().rate();
        BigDecimal cost=pricing==null?BigDecimal.valueOf(Math.addExact(in,out)):pricing.cost(in,out,cached);
        if(cost==null) return; // Provider omitted cache usage needed by this tariff. Keep the hold pending.
        finish(root,attempt,owner,rows,cost,in,out,cached,null);
    }
    void release(long root,long attempt,long owner) {
        for(var h:holds(attempt)) {
            if(jdbc.update("UPDATE llm_quota SET native_reserved=native_reserved-? WHERE id=? AND native_reserved>=?",h.amount(),h.account(),h.amount())!=1)
                throw new IllegalStateException("释放额度时账本不一致");
            ledger(h.account(),root,attempt,owner,"NATIVE:FINAL","NATIVE_RELEASE",h.amount().negate(),ZERO,null,null,null,encode(h.snapshot()));
        }
    }
    /** The original provider report stays intact. Manual finalization needs supplier evidence. */
    public void review(long attemptId,Review r) {
        var who=actor(); requireSupervisor(who);
        if(r==null || attemptId<1 || r.input()==null || r.output()==null || r.input()<0 || r.output()<0
                || r.cached()!=null && (r.cached()<0 || r.cached()>r.input()) || r.reference()==null
                || r.reference().isBlank() || r.reference().length()>250 || r.requestId()==null
                || !r.requestId().matches("[a-zA-Z0-9_-]{8,128}")) throw new BusinessException(400,"需要完整用量、账单依据及请求编号");
        var ids=jdbc.queryForList("SELECT owner_user_id,parent_workflow_id,workflow_id,resource_id FROM workflow_instance WHERE kind='LLM_PROVIDER_ATTEMPT' AND id=?",attemptId);
        if(ids.size()!=1) throw new BusinessException(404,"调用不存在");
        var op=ids.get(0);long owner=((Number)op.get("owner_user_id")).longValue(),root=((Number)op.get("parent_workflow_id")).longValue();
        String model=String.valueOf(op.get("resource_id"));
        ProviderMeter.amount(r.amount(),ProviderMeter.unit(ProviderMeter.provider(model)));
        long total=Math.addExact(r.input(),r.output());
        if(ProviderMeter.provider(model).equals("dashscope") && r.amount().compareTo(BigDecimal.valueOf(total))!=0)
            throw new BusinessException(400,"百炼扣减量必须等于输入与输出 token 之和");
        jdbc.queryForList("SELECT id FROM users WHERE id IN (?,?) ORDER BY id FOR UPDATE",Long.class,owner,who.userId());
        requireSupervisor(users.lockCurrent(who.userId(),who.username()));
        var workflows=new JdbcWorkflowStore(jdbc,json,ModelBudgetWorkflow.protocols());
        String rootKey=jdbc.queryForObject("SELECT workflow_id FROM workflow_instance WHERE id=? FOR UPDATE",String.class,root);
        var parent=workflows.findLocked(WorkflowKind.LLM_REQUEST,rootKey).orElseThrow();
        var opRecord=workflows.findLocked(WorkflowKind.LLM_PROVIDER_ATTEMPT,(String)op.get("workflow_id")).orElseThrow();
        var reservations=holds(attemptId);
        if(reservations.isEmpty()) throw new BusinessException(409,"调用没有厂家额度预留");
        var verified=new Verified(who.userId(),r.reference().strip(),r.requestId(),decimal(r.amount()),r.input(),r.output(),r.cached());
        var previous=jdbc.queryForList("SELECT native_detail FROM llm_usage WHERE account_id=? AND operation_id=? AND entry_key='NATIVE:FINAL'",String.class,reservations.get(0).account(),attemptId);
        if(!previous.isEmpty()) {
            var stored=decode(previous.get(0),com.fasterxml.jackson.databind.JsonNode.class);
            if(!stored.has("reference") || !verified.equals(decode(previous.get(0),Verified.class))) throw new BusinessException(409,"该调用已有结算回执");
            return;
        }
        if("STARTED".equals(opRecord.status()) && jdbc.queryForObject(
                "SELECT COUNT(*) FROM workflow_instance WHERE id=? AND updated_at<UTC_TIMESTAMP(6)-INTERVAL 1 DAY",Long.class,attemptId)!=1)
            throw new BusinessException(409,"调用仍在进行");
        if("COMPLETED".equals(opRecord.status())) {
            var booked=jdbc.queryForList("""
                    SELECT input_tokens,output_tokens FROM llm_usage WHERE account_id=(SELECT id FROM llm_quota
                    WHERE scope_type='MODEL' AND subject_key=0 AND model_id=? AND period_key='TOTAL') AND operation_id=? AND entry_key='FINAL'
                    """,model,attemptId);
            if(booked.size()!=1 || !r.input().equals(booked.get(0).get("input_tokens")) || !r.output().equals(booked.get(0).get("output_tokens")))
                throw new BusinessException(409,"已入账的 token 与核对值不符");
        } else {
            if(!List.of("STARTED","NEEDS_REVIEW").contains(opRecord.status())) throw new BusinessException(409,"调用状态不支持核对");
            new QuotaAccountStore(jdbc).settle(root,attemptId,owner,model,r.input(),r.output(),r.cached());
            workflows.transition(opRecord,"COMPLETED",workflows.payload(opRecord,ModelBudgetWorkflow.AttemptV1.class),opRecord.runId(),null,null);
            if(!"COMPLETED".equals(parent.status()) && jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE parent_workflow_id=? AND status NOT IN ('COMPLETED','FAILED','CANCELLED')",Long.class,root)==0)
                workflows.transition(parent,"COMPLETED",workflows.payload(parent,ModelBudgetWorkflow.RequestV1.class),parent.runId(),null,null);
        }
        finish(root,attemptId,owner,reservations,r.amount(),r.input(),r.output(),r.cached(),verified);
    }
    private void finish(long root,long attempt,long owner,List<Hold> rows,BigDecimal cost,Long in,Long out,Long cached,Verified verification) {
        for(var h:rows) {
            if(jdbc.update("UPDATE llm_quota SET native_reserved=native_reserved-?,native_spent=native_spent+? WHERE id=? AND native_reserved>=?",
                    h.amount(),cost,h.account(),h.amount())!=1) throw new IllegalStateException("厂家或员工的预留额度不一致");
            ledger(h.account(),root,attempt,owner,"NATIVE:FINAL","NATIVE_SETTLE",h.amount().negate(),cost,in,out,cached,encode(verification==null?h.snapshot():verification));
        }
    }
    private void ledger(long account,long root,long attempt,long owner,String key,String type,BigDecimal held,BigDecimal cost,
                        Long in,Long out,Long cached,String detail) {
        String digest=ModelConfigurationStore.digest(key,Long.toString(attempt),Long.toString(account),decimal(held),decimal(cost),detail);
        jdbc.update("""
                INSERT INTO llm_usage(account_id,root_operation_id,operation_id,entry_key,entry_type,request_sha256,actor_user_id,
                    native_reserved_delta,native_spent_delta,input_tokens,output_tokens,cached_tokens,native_detail,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,UTC_TIMESTAMP(6))
                """,account,root,attempt,key,type,digest,owner,held,cost,in,out,cached,detail);
    }
}
