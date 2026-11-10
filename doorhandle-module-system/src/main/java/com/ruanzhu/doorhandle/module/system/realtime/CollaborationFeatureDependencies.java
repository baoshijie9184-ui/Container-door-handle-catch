package com.ruanzhu.doorhandle.module.system.realtime;

import jakarta.annotation.PostConstruct;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

/** An enabled write/notification feature cannot silently fall back to metadata-only behavior. */
@Component
public class CollaborationFeatureDependencies {
    private final Environment environment;
    public CollaborationFeatureDependencies(Environment environment) { this.environment = environment; }
    @PostConstruct void validate() {
        boolean audit = enabled("operations.audit.enabled"), sessions = enabled("collaboration.sessions.enabled");
        boolean mutations = enabled("collaboration.mutations.enabled"), history = enabled("collaboration.change-history.enabled");
        boolean realtime = enabled("collaboration.realtime.enabled");
        if ((mutations || history) && !audit) throw new IllegalStateException("协同写入与修改历史必须启用基础审计");
        if (realtime && (!sessions || !history || !audit)) throw new IllegalStateException("实时同步必须同时启用独立登录会话、基础审计和修改历史");
    }
    private boolean enabled(String name) { return environment.getProperty(name, Boolean.class, false); }
}
