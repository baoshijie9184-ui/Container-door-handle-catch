package com.ruanzhu.doorhandle.module.ai.research;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "agentscope.research")
public class ResearchEvidenceProperties {
    private boolean enabled;
    private boolean governanceEnabled;
    private boolean purgeEnabled;
    private boolean exportEnabled;
    private boolean exportRateLimitEnabled;
    private int exportMaxPerWindow = 5;
    private int exportWindowSeconds = 60;
    private int maxSourcesPerUser = 500;
    private int cleanupBatchSize = 100;
    private long cleanupDelayMs = 60000;
    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public boolean isGovernanceEnabled() { return governanceEnabled; }
    public void setGovernanceEnabled(boolean value) { governanceEnabled = value; }
    public boolean isPurgeEnabled() { return purgeEnabled; }
    public void setPurgeEnabled(boolean value) { purgeEnabled = value; }
    public boolean isExportEnabled() { return exportEnabled; }
    public void setExportEnabled(boolean value) { exportEnabled = value; }
    public boolean isExportRateLimitEnabled() { return exportRateLimitEnabled; }
    public void setExportRateLimitEnabled(boolean value) { exportRateLimitEnabled = value; }
    public int getExportMaxPerWindow() { return exportMaxPerWindow; }
    public void setExportMaxPerWindow(int value) { exportMaxPerWindow = value; }
    public int getExportWindowSeconds() { return exportWindowSeconds; }
    public void setExportWindowSeconds(int value) { exportWindowSeconds = value; }
    public int getMaxSourcesPerUser() { return maxSourcesPerUser; }
    public void setMaxSourcesPerUser(int value) { maxSourcesPerUser = value; }
    public int getCleanupBatchSize() { return cleanupBatchSize; }
    public void setCleanupBatchSize(int value) { cleanupBatchSize = value; }
    public long getCleanupDelayMs() { return cleanupDelayMs; }
    public void setCleanupDelayMs(long value) { cleanupDelayMs = value; }
}
