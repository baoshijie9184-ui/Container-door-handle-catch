package com.ruanzhu.doorhandle.module.ai.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "agentscope.journal")
public class AgentJournalProperties {
    private boolean enabled;
    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled=enabled; }
}
