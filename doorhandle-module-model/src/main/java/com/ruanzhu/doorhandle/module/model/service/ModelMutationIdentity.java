package com.ruanzhu.doorhandle.module.model.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;
import java.util.UUID;

/** Resolve server authentication through the owning module's stable account facade. */
@Component
public class ModelMutationIdentity {
    private final BusinessUserDirectory users;
    public ModelMutationIdentity(BusinessUserDirectory users) {
        this.users = users;
    }
    public AgentActor supervisor() {
        var user = users.authenticated();
        if (!user.supervisor()) throw new SecurityException("模型变更需要当前主管权限");
        return new AgentActor(user.userId(), user.username(), AgentActor.Role.SUPERVISOR);
    }
    public String requestId() {
        var attributes = RequestContextHolder.getRequestAttributes();
        if (!(attributes instanceof ServletRequestAttributes http)) return UUID.randomUUID().toString();
        String value = http.getRequest().getHeader("X-Request-ID");
        if ((value == null || value.isBlank()) && http.getResponse() != null)
            value = http.getResponse().getHeader("X-Request-ID");
        if (value == null || value.isBlank()) value = UUID.randomUUID().toString();
        if (!value.matches("[A-Za-z0-9_-]{1,128}")) throw new IllegalArgumentException("请求编号无效");
        if (http.getResponse() != null) http.getResponse().setHeader("X-Request-ID", value);
        return value;
    }
}
