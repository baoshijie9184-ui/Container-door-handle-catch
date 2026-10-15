package com.ruanzhu.doorhandle.module.ai.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix="agentscope.actions")
public class AgentActionProperties {
    private boolean enabled;
    private java.util.List<String> allowedOrigins=java.util.List.of("http://127.0.0.1:3001","http://localhost:3001","http://127.0.0.1:3003","http://localhost:3003","http://127.0.0.1:8080","http://localhost:8080");
    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled=enabled; }
    public java.util.List<String> getAllowedOrigins(){return allowedOrigins;}
    public void setAllowedOrigins(java.util.List<String> values){allowedOrigins=java.util.List.copyOf(values);}
}
