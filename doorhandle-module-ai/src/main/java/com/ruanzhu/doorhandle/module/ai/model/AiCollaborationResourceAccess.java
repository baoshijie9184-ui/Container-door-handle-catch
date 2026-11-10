package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessResourceAccess;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/** Same current account/range rules as configuration, budget and mine/team application HTTP reads. */
@Component
public class AiCollaborationResourceAccess implements BusinessResourceAccess {
    private final JdbcTemplate jdbc;private final BusinessUserDirectory users;
    public AiCollaborationResourceAccess(JdbcTemplate jdbc,BusinessUserDirectory users){this.jdbc=jdbc;this.users=users;}
    public boolean mayRead(AgentActor actor,String scope,String domain,String type,String id){
        if(actor==null||!"ENTERPRISE".equals(scope)||id==null)return false;
        try{
            var current=users.current(actor.userId(),actor.username());
            if("MODEL_CONFIG".equals(domain)&&"LLM_CONFIGURATION".equals(type)&&id.matches("[1-9][0-9]{0,18}"))
                return current.supervisor()&&jdbc.queryForObject("SELECT COUNT(*) FROM llm_configuration WHERE revision=?",Long.class,Long.parseLong(id))==1;
            if("MODEL_BUDGET".equals(domain)&&"LLM_MODEL".equals(type)&&id.matches("(dashscope|deepseek|openai|openai-official):[A-Za-z0-9._/-]{1,140}"))
                return current.supervisor()&&jdbc.queryForObject("SELECT COUNT(*) FROM llm_quota WHERE scope_type='MODEL' AND model_id=? AND period_key='TOTAL'",Long.class,id)==1;
            if("MODEL_BUDGET".equals(domain)&&"MODEL_QUOTA_OBSERVATION".equals(type)&&id.matches("[a-f0-9-]{36}"))
                return current.supervisor()&&jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='MODEL_QUOTA_OBSERVATION' AND event_id=?",Long.class,id)==1;
            if("LLM_QUOTA_APPLICATION".equals(domain)&&"LLM_QUOTA_APPLICATION".equals(type)&&id.matches("[a-f0-9-]{36}")){
                var owners=jdbc.queryForList("SELECT owner_user_id FROM workflow_instance WHERE kind='LLM_QUOTA_APPLICATION' AND workflow_id=?",Long.class,id);
                return owners.size()==1&&(current.supervisor()||owners.get(0)==current.userId());
            }
            if("MODEL_BUDGET".equals(domain)&&"LLM_PERSONAL_QUOTA".equals(type)&&id.matches("[1-9][0-9]{0,18}")){
                var owners=jdbc.queryForList("SELECT owner_user_id FROM llm_quota WHERE scope_type='USER' AND id=? AND period_key='TOTAL'",Long.class,Long.parseLong(id));
                return owners.size()==1&&owners.get(0)==current.userId();
            }
            return false;
        }catch(SecurityException|org.springframework.security.core.AuthenticationException|org.springframework.security.access.AccessDeniedException|NumberFormatException denied){return false;}
    }
}
