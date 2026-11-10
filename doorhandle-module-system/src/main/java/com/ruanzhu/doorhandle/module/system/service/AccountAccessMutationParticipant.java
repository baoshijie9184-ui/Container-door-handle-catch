package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessMutationParticipant;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessResourceAccess;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.springframework.stereotype.Component;
import java.util.Map;
import java.util.Set;

@Component
public class AccountAccessMutationParticipant implements BusinessMutationParticipant,BusinessResourceAccess {
    private final AccountAccessService accounts;
    private final UserMapper users;
    public AccountAccessMutationParticipant(AccountAccessService accounts,UserMapper users){this.accounts=accounts;this.users=users;}
    @Override public boolean supports(String domain,String action){return "ORGANIZATION".equals(domain)&&"ACCOUNT_ACCESS".equals(action);}
    @Override public String resourceId(String domain,String action,Object[] args,Object result){return String.valueOf((Long)args[1]);}
    /** Runs before the shared audit aspect locks the actor; both identities use one stable order. */
    public void prepare(AgentActor actor,String domain,String action,String resourceId,Object[] arguments){accounts.lock(actor.userId(),actor.username(),Long.parseLong(resourceId));}
    @Override public Snapshot capture(AgentActor actor,String domain,String action,String resourceId,boolean lock){
        long id=Long.parseLong(resourceId);
        var user=lock?accounts.lock(actor.userId(),actor.username(),id):users.selectById(id);
        if(!lock)accounts.supervisor(actor.userId(),actor.username());
        return user==null?null:new Snapshot("ACCOUNT",resourceId,user.getAccountVersion(),Map.of("enabled",user.getEnabled(),"role",user.getRole()),Set.of(),Set.of());
    }
    @Override public Object digestInput(String action,Object[] args){var change=(AccountAccessService.Change)args[2];return Map.of("userId",args[1],"enabled",change.enabled(),"role",change.role(),"expectedVersion",change.expectedVersion(),"requestId",change.requestId());}
    @Override public boolean mayRead(AgentActor actor,String scope,String domain,String resourceType,String id){
        if(!"ENTERPRISE".equals(scope)||!"ORGANIZATION".equals(domain)||!"ACCOUNT".equals(resourceType))return false;
        try{accounts.supervisor(actor.userId(),actor.username());return id!=null&&id.matches("[1-9][0-9]{0,18}")&&users.selectById(Long.parseLong(id))!=null;}catch(RuntimeException denied){return false;}
    }
}
