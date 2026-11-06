package com.ruanzhu.doorhandle.module.system.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.workflow.AuditEvent;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcAuditStore;
import com.ruanzhu.doorhandle.module.system.entity.OrganizationBindingAudit;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/** Immutable account/employee association evidence, separate from the live binding on users. */
@Repository
public class OrganizationBindingAuditStore {
    public record BindingV1(String username,String actorUsername,Long beforeEmployeeId,Long afterEmployeeId,
                            String legacyId,String legacyCreatedAt) {
        public BindingV1 {
            if(username==null||username.isEmpty()||username.codePointCount(0,username.length())>50
                    ||actorUsername==null||actorUsername.isEmpty()||actorUsername.codePointCount(0,actorUsername.length())>50
                    ||beforeEmployeeId!=null&&beforeEmployeeId<=0||afterEmployeeId!=null&&afterEmployeeId<=0
                    ||Objects.equals(beforeEmployeeId,afterEmployeeId)||(legacyId==null)!=(legacyCreatedAt==null))
                throw new IllegalArgumentException("Invalid account binding evidence");
        }
    }
    private final JdbcTemplate jdbc;
    private final ObjectMapper json=new ObjectMapper().enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
    private final JdbcAuditStore audits;
    public OrganizationBindingAuditStore(JdbcTemplate jdbc) {
        this.jdbc=jdbc;audits=new JdbcAuditStore(jdbc,json,Map.of("ORGANIZATION_BINDING",BindingV1.class));
    }
    public void append(OrganizationBindingAudit value) {
        if(value.getUserId()==null||value.getUserId()<=0||value.getActorUserId()==null||value.getActorUserId()<=0
                ||value.getBindingVersion()==null||value.getBindingVersion()<=0)throw new IllegalArgumentException("Invalid binding audit identity");
        var payload=new BindingV1(value.getUsername(),value.getActorUsername(),value.getBeforeEmployeeId(),value.getAfterEmployeeId(),null,null);
        requireAction(value.getAction(),payload);
        audits.append(new AuditEvent("ORGANIZATION_BINDING",value.getUserId(),value.getActorUserId(),"USER",
                Long.toString(value.getUserId()),null,null,null,null,value.getAction(),value.getBindingVersion().longValue(),null,null,1,payload));
    }
    public List<OrganizationBindingAudit> latest(long userId) {
        return jdbc.query("SELECT id,owner_user_id,actor_user_id,action,revision,payload_version,payload_json,occurred_at "
                +"FROM audit_event WHERE kind='ORGANIZATION_BINDING' AND owner_user_id=? ORDER BY id DESC LIMIT 50",(rs,index)-> {
            if(rs.getInt("payload_version")!=1)throw new IllegalStateException("Unsupported binding audit payload version");
            BindingV1 payload;
            try {payload=json.readValue(rs.getString("payload_json"),BindingV1.class);}
            catch(JsonProcessingException invalid){throw new IllegalStateException("Invalid stored binding audit",invalid);}
            requireAction(rs.getString("action"),payload);
            var item=new OrganizationBindingAudit();item.setId(rs.getLong("id"));item.setUserId(rs.getLong("owner_user_id"));
            item.setActorUserId(rs.getLong("actor_user_id"));item.setUsername(payload.username());item.setActorUsername(payload.actorUsername());
            item.setBeforeEmployeeId(payload.beforeEmployeeId());item.setAfterEmployeeId(payload.afterEmployeeId());
            item.setBindingVersion(Math.toIntExact(rs.getLong("revision")));item.setAction(rs.getString("action"));
            item.setCreatedAt(OperationsAuditPersistence.displayTime(rs.getObject("occurred_at",LocalDateTime.class)));
            return item;
        },userId);
    }
    private static void requireAction(String action,BindingV1 value) {
        String expected=value.afterEmployeeId()==null?"UNBIND":value.beforeEmployeeId()==null?"BIND":"REBIND";
        if(action==null||!Set.of("BIND","UNBIND","REBIND").contains(action)||!expected.equals(action))
            throw new IllegalArgumentException("Binding action differs from its before/after evidence");
    }
}
