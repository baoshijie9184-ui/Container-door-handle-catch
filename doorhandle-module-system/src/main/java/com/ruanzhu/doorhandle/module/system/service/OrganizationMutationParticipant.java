package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.collaboration.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots.Mapping;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import java.util.*;

@Component
public class OrganizationMutationParticipant implements BusinessMutationParticipant,BusinessResourceAccess {
    private static final Mapping DEPARTMENT=new Mapping("DEPARTMENT","organization_department","id","version",List.of("name"),Set.of(),Set.of());
    private static final Mapping BINDING=new Mapping("ACCOUNT_BINDING","users","id","binding_version",List.of("employee_id"),Set.of(),Set.of());
    private final JdbcTemplate jdbc;private final BusinessUserDirectory users;private final JdbcMutationSnapshots snapshots;
    public OrganizationMutationParticipant(JdbcTemplate jdbc,BusinessUserDirectory users){this.jdbc=jdbc;this.users=users;snapshots=new JdbcMutationSnapshots(jdbc);}
    public boolean supports(String domain,String action){return "ORGANIZATION".equals(domain)&&Set.of("CREATE_DEPARTMENT","bind").contains(action);}
    public boolean creates(String action){return "CREATE_DEPARTMENT".equals(action);}
    public String resourceId(String domain,String action,Object[] args,Object result){if("bind".equals(action))return args[1].toString();if(result==null)return null;return JdbcMutationSnapshots.properties(result,"id").get("id").toString();}
    public Snapshot capture(AgentActor actor,String domain,String action,String id,boolean lock){if(!users.current(actor.userId(),actor.username()).supervisor())throw new SecurityException("组织权限已撤销");return snapshots.capture("bind".equals(action)?BINDING:DEPARTMENT,id,lock);}
    public void prepare(AgentActor actor,String domain,String action,String id,Object[] arguments){
        var ids=new TreeSet<Long>();ids.add(actor.userId());if("bind".equals(action)&&id!=null)ids.add(Long.parseLong(id));
        for(Long user:ids)jdbc.queryForList("SELECT id FROM users WHERE id=? FOR UPDATE",user);
    }
    public Snapshot advanceVersion(Snapshot before,Snapshot after){return snapshots.advance("ACCOUNT_BINDING".equals((after==null?before:after).resourceType())?BINDING:DEPARTMENT,before,after);}
    public Object digestInput(String action,Object[] args){return "bind".equals(action)?Arrays.asList(args[1],args[2],args[3]):Arrays.asList(args);}
    public boolean mayRead(AgentActor actor,String scope,String domain,String type,String id){if(!"ENTERPRISE".equals(scope)||!"ORGANIZATION".equals(domain)||!Set.of("DEPARTMENT","ACCOUNT_BINDING").contains(type))return false;try{return users.current(actor.userId(),actor.username()).supervisor();}catch(SecurityException denied){return false;}}
}
