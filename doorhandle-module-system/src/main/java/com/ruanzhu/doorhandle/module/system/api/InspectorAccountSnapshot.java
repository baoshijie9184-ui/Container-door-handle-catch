package com.ruanzhu.doorhandle.module.system.api;

import com.ruanzhu.doorhandle.contracts.agent.AgentUserDirectory.Inspector;
import com.ruanzhu.doorhandle.module.system.entity.User;

/** A public-safe account snapshot; no credential or contact field participates. */
final class InspectorAccountSnapshot {
    private InspectorAccountSnapshot(){}
    static Inspector describe(User user){
        if(user.getId()==null||user.getId()<1||user.getUsername()==null||!("INSPECTOR".equalsIgnoreCase(user.getRole())||"OPERATOR".equalsIgnoreCase(user.getRole())))
            throw new IllegalArgumentException("责任人员工账号已失效");
        var account=BusinessAccountSnapshot.describe(user);
        return new Inspector(account.userId(),account.username(),account.revision());
    }
}
