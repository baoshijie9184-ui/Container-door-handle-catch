package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;
import java.util.*;
import com.ruanzhu.doorhandle.contracts.collaboration.*;

@Service
@ConditionalOnProperty(prefix="operations.audit",name="enabled",havingValue="true")
public class OperationsAuditService implements OperationsAuditApi {
    private final JdbcTemplate jdbc;
    private final BusinessUserDirectory users;
    private final OperationsAuditPersistence records;
    private List<BusinessResourceAccess> resourceAccess=List.of();
    private org.springframework.context.ApplicationEventPublisher publisher;
    private com.ruanzhu.doorhandle.module.system.mapper.AccountEmployeeBindingMapper bindings;
    private com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi employees;
    @org.springframework.beans.factory.annotation.Value("${collaboration.change-history.enabled:false}") private boolean changeHistoryEnabled;
    public OperationsAuditService(JdbcTemplate jdbc,BusinessUserDirectory users) {
        this.jdbc=jdbc;this.users=users;records=new OperationsAuditPersistence(jdbc);
    }
    @org.springframework.beans.factory.annotation.Autowired
    public void collaboration(List<BusinessResourceAccess> access,org.springframework.context.ApplicationEventPublisher events,
            com.ruanzhu.doorhandle.module.system.mapper.AccountEmployeeBindingMapper bindings,
            com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi employees) {
        this.resourceAccess=List.copyOf(access);this.publisher=events;this.bindings=bindings;this.employees=employees;
    }
    private AgentActor current(AgentActor actor) {
        var user=users.current(actor.userId(),actor.username());
        return new AgentActor(user.userId(),user.username(),user.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);
    }
    @Override @Transactional public void append(Event event) {
        var actor=current(event.actor());
        records.append(actor.userId(),event.scope(),event.domain(),event.action(),event.resourceId(),event.requestId(),event.result(),event.resourceVersion());
    }
    @Override @Transactional public void appendChange(ChangeEvent change) {
        // This internal port receives the actor authorized and locked before the mutation.
        // Re-deriving a role after a self-demotion would rewrite the operation-time fact.
        var event=change.metadata();var actor=event.actor();
        if(actor==null||actor.userId()<=0)throw new SecurityException("修改记录缺少已授权操作账号");
        String display=change.displayName()==null?actorDisplayName(actor):change.displayName().isEmpty()?null:change.displayName();
        var receipt=records.appendChange(actor,event.scope(),event.domain(),event.action(),event.resourceId(),event.requestId(),
                event.result(),event.resourceVersion(),change.resourceType(),display,change.beforeVersion(),change.changes());
        if(receipt.created()&&publisher!=null)publisher.publishEvent(new BusinessResourceChanged(receipt.eventId(),receipt.auditId(),
                event.scope(),event.domain(),change.resourceType(),event.resourceId(),string(event.resourceVersion()),
                event.action(),event.requestId(),actor.userId(),receipt.occurredAt()));
    }
    /** Server-only identity snapshot, called by the mutation aspect before the domain write. */
    public String actorDisplayName(AgentActor actor){
        String display=null;
        if(bindings!=null&&employees!=null){var binding=bindings.selectById(actor.userId());
            if(binding!=null&&binding.getEmployeeId()!=null){var staff=employees.findAll(List.of(binding.getEmployeeId()));
                if(staff.size()==1)display=staff.get(0).name();}}
        return display;
    }
    public List<Map<String,Object>> list(AgentActor actor,long before,int size,String domain) {
        var fresh=current(actor);
        if(before<1 || size<1 || size>100)throw new IllegalArgumentException("分页参数无效");
        var args=new ArrayList<Object>();args.add(before);
        String sql="SELECT id,actor_user_id,operation_scope,operation_domain,action,resource_id,request_id,operation_result,payload_version,payload_json,occurred_at "
                + "FROM audit_event WHERE kind='OPERATIONS' AND id<?";
        sql+=fresh.supervisor()?" AND (operation_scope='ENTERPRISE' OR actor_user_id=?)":" AND actor_user_id=?";args.add(fresh.userId());
        if(domain!=null && !domain.isBlank()) {sql+=" AND operation_domain=?";args.add(OperationsAuditPersistence.token(domain,48));}
        args.add(size);
        return jdbc.query(sql+" ORDER BY id DESC LIMIT ?",(rs,index)->{
            var payload=records.decode(rs.getInt("payload_version"),rs.getString("payload_json"));
            Map<String,Object> row=new LinkedHashMap<>();
            row.put("id",rs.getLong("id"));row.put("actor_user_id",rs.getLong("actor_user_id"));row.put("scope",payload.scope());
            row.put("domain",payload.domain());row.put("action",rs.getString("action"));row.put("resource_id",rs.getString("resource_id"));
            row.put("request_id",rs.getString("request_id"));row.put("result",payload.result());row.put("resource_version",payload.resourceVersion());
            row.put("created_at",OperationsAuditPersistence.displayTime(rs.getObject("occurred_at",LocalDateTime.class)));return row;
        },args.toArray());
    }
    public record Filter(String domain,String resourceType,String resourceId,String actorUserId,String actorRole,
                         String action,java.time.Instant occurredFrom,java.time.Instant occurredTo) { }
    public ChangeHistory.Page changes(AgentActor requested,long before,int size,Filter filter) {
        if(!changeHistoryEnabled)throw new com.ruanzhu.doorhandle.common.BusinessException(404,"修改记录尚未启用");
        var actor=current(requested);if(before<1||size<1||size>100)throw new IllegalArgumentException("分页参数无效");
        if((filter.resourceType()==null)!=(filter.resourceId()==null))throw new IllegalArgumentException("资源类型和编号必须同时提供");
        if(filter.occurredFrom()!=null&&filter.occurredTo()!=null&&!filter.occurredFrom().isBefore(filter.occurredTo()))throw new IllegalArgumentException("时间范围无效");
        var args=new ArrayList<Object>();args.add(before);
        String sql="SELECT * FROM audit_event WHERE kind='OPERATIONS' AND id<?";
        sql+=" AND (operation_scope='ENTERPRISE' OR actor_user_id=?)";args.add(actor.userId());
        if(filter.domain()!=null){sql+=" AND operation_domain=?";args.add(OperationsAuditPersistence.token(filter.domain(),48));}
        if(filter.resourceType()!=null){sql+=" AND payload_version=2 AND operation_resource_type=? AND resource_id=?";args.add(OperationsAuditPersistence.token(filter.resourceType(),64));args.add(OperationsAuditPersistence.token(filter.resourceId(),160));}
        if(filter.actorUserId()!=null){if(!filter.actorUserId().matches("[1-9][0-9]{0,18}"))throw new IllegalArgumentException("账号无效");sql+=" AND actor_user_id=?";args.add(Long.parseLong(filter.actorUserId()));}
        if(filter.actorRole()!=null){if(!Set.of("SUPERVISOR","INSPECTOR").contains(filter.actorRole()))throw new IllegalArgumentException("角色无效");sql+=" AND payload_version=2 AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.actorRole'))=?";args.add(filter.actorRole());}
        if(filter.action()!=null){sql+=" AND action=?";args.add(OperationsAuditPersistence.token(filter.action(),64));}
        if(filter.occurredFrom()!=null){sql+=" AND occurred_at>=?";args.add(LocalDateTime.ofInstant(filter.occurredFrom(),java.time.ZoneOffset.UTC));}
        if(filter.occurredTo()!=null){sql+=" AND occurred_at<?";args.add(LocalDateTime.ofInstant(filter.occurredTo(),java.time.ZoneOffset.UTC));}
        args.add(Math.min(1000,size*10));var rows=jdbc.queryForList(sql+" ORDER BY id DESC LIMIT ?",args.toArray());
        var items=new ArrayList<ChangeHistory.Item>();String cursor=null;
        for(var row:rows){cursor=String.valueOf(row.get("id"));var payload=decode(row);boolean allowed=allowed(actor,row,payload);
            if(allowed||((Number)row.get("actor_user_id")).longValue()==actor.userId()||legacySummary(actor,payload))items.add(item(row,payload,allowed));
            if(items.size()==size)break;}
        return new ChangeHistory.Page(items,rows.isEmpty()?null:cursor);
    }
    public ChangeHistory.Detail change(AgentActor requested,String id) {
        if(!changeHistoryEnabled)throw new com.ruanzhu.doorhandle.common.BusinessException(404,"修改记录尚未启用");
        var actor=current(requested);if(id==null||!id.matches("[1-9][0-9]{0,18}"))throw new IllegalArgumentException("记录编号无效");
        var rows=jdbc.queryForList("SELECT * FROM audit_event WHERE kind='OPERATIONS' AND id=?",Long.parseLong(id));
        if(rows.size()!=1)throw new SecurityException("记录不存在或无权查看");
        var row=rows.get(0);var payload=decode(row);boolean allowed=allowed(actor,row,payload);
        boolean ownLegacy=payload.detail()==null&&((Number)row.get("actor_user_id")).longValue()==actor.userId();
        if(!allowed&&!ownLegacy&&!legacySummary(actor,payload))throw new SecurityException("当前无权读取资源历史");
        var item=item(row,payload,allowed);return new ChangeHistory.Detail(item.id(),item.eventId(),item.actor(),item.domain(),item.resourceType(),
                item.resourceId(),item.action(),item.result(),item.beforeVersion(),item.afterVersion(),item.requestId(),item.occurredAt(),item.scope(),
                item.diffAvailable(),payload.detail()==null?List.of():payload.detail().changes());
    }
    private boolean allowed(AgentActor actor,Map<String,Object> row,OperationsAuditPersistence.Decoded payload) {
        if("PRIVATE".equals(payload.scope())&&((Number)row.get("actor_user_id")).longValue()!=actor.userId())return false;
        if(payload.detail()==null)return false;
        return resourceAccess.stream().anyMatch(access->access.mayRead(actor,payload.scope(),payload.domain(),payload.detail().resourceType(),String.valueOf(row.get("resource_id"))));
    }
    private static boolean legacySummary(AgentActor actor,OperationsAuditPersistence.Decoded payload){
        // V1 has no trustworthy resource type/field snapshot. Preserve the existing enterprise metadata view,
        // while returning no inferred resource identity, actor role, revisions or field differences.
        return payload.detail()==null&&actor.supervisor()&&"ENTERPRISE".equals(payload.scope());
    }
    private OperationsAuditPersistence.Decoded decode(Map<String,Object> row){return records.decode(((Number)row.get("payload_version")).intValue(),String.valueOf(row.get("payload_json")));}
    private ChangeHistory.Item item(Map<String,Object> row,OperationsAuditPersistence.Decoded payload,boolean allowed) {
        var detail=payload.detail();allowed=allowed&&detail!=null;var identity=new ChangeHistory.Actor(String.valueOf(row.get("actor_user_id")),
                detail==null?null:detail.actorUsername(),detail==null?null:detail.actorDisplayName(),detail==null?null:detail.actorRole());
        Object time=row.get("occurred_at");java.time.Instant instant=time instanceof LocalDateTime date?date.toInstant(java.time.ZoneOffset.UTC):((java.sql.Timestamp)time).toInstant();
        return new ChangeHistory.Item(String.valueOf(row.get("id")),String.valueOf(row.get("event_id")),identity,payload.domain(),
                allowed?detail.resourceType():null,allowed?String.valueOf(row.get("resource_id")):null,String.valueOf(row.get("action")),payload.result(),
                allowed?string(detail.beforeVersion()):null,allowed?string(payload.resourceVersion()):null,String.valueOf(row.get("request_id")),instant,payload.scope(),allowed&&detail!=null);
    }
    private static String string(Long value){return value==null?null:Long.toString(value);}
}
