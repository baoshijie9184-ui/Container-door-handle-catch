package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;
import java.util.*;

@Service
@ConditionalOnProperty(prefix="operations.audit",name="enabled",havingValue="true")
public class OperationsAuditService implements OperationsAuditApi {
    private final JdbcTemplate jdbc;
    private final BusinessUserDirectory users;
    private final OperationsAuditPersistence records;
    public OperationsAuditService(JdbcTemplate jdbc,BusinessUserDirectory users) {
        this.jdbc=jdbc;this.users=users;records=new OperationsAuditPersistence(jdbc);
    }
    private AgentActor current(AgentActor actor) {
        var user=users.current(actor.userId(),actor.username());
        return new AgentActor(user.userId(),user.username(),user.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);
    }
    @Override @Transactional public void append(Event event) {
        var actor=current(event.actor());
        records.append(actor.userId(),event.scope(),event.domain(),event.action(),event.resourceId(),event.requestId(),event.result(),event.resourceVersion());
    }
    public List<Map<String,Object>> list(AgentActor actor,long before,int size,String domain) {
        var fresh=current(actor);
        if(before<1 || size<1 || size>100)throw new IllegalArgumentException("分页参数无效");
        var args=new ArrayList<Object>();args.add(before);
        String sql="SELECT id,actor_user_id,operation_scope,operation_domain,action,resource_id,request_id,operation_result,payload_json,occurred_at "
                + "FROM audit_event WHERE kind='OPERATIONS' AND id<?";
        sql+=fresh.supervisor()?" AND (operation_scope='ENTERPRISE' OR actor_user_id=?)":" AND actor_user_id=?";args.add(fresh.userId());
        if(domain!=null && !domain.isBlank()) {sql+=" AND operation_domain=?";args.add(OperationsAuditPersistence.token(domain,48));}
        args.add(size);
        return jdbc.query(sql+" ORDER BY id DESC LIMIT ?",(rs,index)->{
            var payload=records.decode(rs.getString("payload_json"));
            Map<String,Object> row=new LinkedHashMap<>();
            row.put("id",rs.getLong("id"));row.put("actor_user_id",rs.getLong("actor_user_id"));row.put("scope",payload.scope());
            row.put("domain",payload.domain());row.put("action",rs.getString("action"));row.put("resource_id",rs.getString("resource_id"));
            row.put("request_id",rs.getString("request_id"));row.put("result",payload.result());row.put("resource_version",payload.resourceVersion());
            row.put("created_at",OperationsAuditPersistence.displayTime(rs.getObject("occurred_at",LocalDateTime.class)));return row;
        },args.toArray());
    }
}
