package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.dao.DuplicateKeyException;
import java.util.*;

@Service
@ConditionalOnProperty(prefix="operations.audit",name="enabled",havingValue="true")
public class OperationsAuditService implements OperationsAuditApi {
    private final JdbcTemplate jdbc;private final BusinessUserDirectory users;
    public OperationsAuditService(JdbcTemplate jdbc,BusinessUserDirectory users){this.jdbc=jdbc;this.users=users;}
    private AgentActor current(AgentActor actor){var user=users.current(actor.userId(),actor.username());return new AgentActor(user.userId(),user.username(),user.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);}
    private static String token(String text,int max){if(text==null||text.length()>max||!text.matches("[A-Za-z0-9_:./-]+"))throw new IllegalArgumentException("审计标识无效");return text;}
    @Override @Transactional public void append(Event event){
        var actor=current(event.actor());
        if(!Set.of("ENTERPRISE","PRIVATE").contains(event.scope()))throw new IllegalArgumentException("审计范围无效");
        token(event.domain(),48);token(event.action(),64);token(event.resourceId(),160);token(event.requestId(),128);token(event.result(),40);
        try{jdbc.update("INSERT INTO operations_audit(actor_user_id,scope,domain,action,resource_id,request_id,result,resource_version,created_at) VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP(6))",actor.userId(),event.scope(),event.domain(),event.action(),event.resourceId(),event.requestId(),event.result(),event.resourceVersion());}
        catch(DuplicateKeyException duplicate){var rows=jdbc.queryForList("SELECT scope,resource_version FROM operations_audit WHERE actor_user_id=? AND domain=? AND action=? AND resource_id=? AND request_id=? AND result=?",actor.userId(),event.domain(),event.action(),event.resourceId(),event.requestId(),event.result());if(rows.size()!=1||!event.scope().equals(rows.get(0).get("scope"))||!Objects.equals(event.resourceVersion(),rows.get(0).get("resource_version")==null?null:((Number)rows.get(0).get("resource_version")).longValue()))throw new IllegalStateException("审计请求编号冲突");}
    }
    public List<Map<String,Object>> list(AgentActor actor,long before,int size,String domain){
        var fresh=current(actor);if(before<1||size<1||size>100)throw new IllegalArgumentException("分页参数无效");
        var args=new ArrayList<Object>();args.add(before);String sql="SELECT id,actor_user_id,scope,domain,action,resource_id,request_id,result,resource_version,created_at FROM operations_audit WHERE id<?";
        if(fresh.supervisor()){sql+=" AND (scope='ENTERPRISE' OR actor_user_id=?)";args.add(fresh.userId());}else{sql+=" AND actor_user_id=?";args.add(fresh.userId());}
        if(domain!=null&&!domain.isBlank()){sql+=" AND domain=?";args.add(token(domain,48));}args.add(size);return jdbc.queryForList(sql+" ORDER BY id DESC LIMIT ?",args.toArray());
    }
}
