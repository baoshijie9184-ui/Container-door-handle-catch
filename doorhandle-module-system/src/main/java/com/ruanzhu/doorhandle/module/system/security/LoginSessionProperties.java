package com.ruanzhu.doorhandle.module.system.security;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;
import java.util.Map;

/** Candidate activation is explicit; legacy aliases require an account-by-account decision. */
@Component
@ConfigurationProperties(prefix="collaboration.sessions")
public class LoginSessionProperties {
    private boolean enabled;
    private Map<String,String> legacyRoleAccounts=Map.of();
    public boolean isEnabled(){return enabled;}
    public void setEnabled(boolean value){enabled=value;}
    public Map<String,String> getLegacyRoleAccounts(){return legacyRoleAccounts;}
    public void setLegacyRoleAccounts(Map<String,String> value){
        if(value!=null&&value.entrySet().stream().anyMatch(e->e.getKey()==null||e.getKey().isBlank()||e.getKey().length()>50||!("SUPERVISOR".equals(e.getValue())||"INSPECTOR".equals(e.getValue()))))
            throw new IllegalArgumentException("Legacy role decisions require an exact username and SUPERVISOR or INSPECTOR");
        legacyRoleAccounts=value==null?Map.of():Map.copyOf(value);
    }
}
