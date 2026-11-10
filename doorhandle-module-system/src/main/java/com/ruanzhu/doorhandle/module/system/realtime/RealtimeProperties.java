package com.ruanzhu.doorhandle.module.system.realtime;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Component
@ConfigurationProperties(prefix = "collaboration.realtime")
public class RealtimeProperties {
    private boolean enabled;
    private int maxConnections = 128;
    private int maxConnectionsPerUser = 6;
    private int queueCapacity = 32;
    private long heartbeatMillis = 25_000;
    private long sendTimeoutMillis = 10_000;
    private long connectionTtlMillis = 300_000;
    private int eventBudget = 1024;

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean value) { enabled = value; }
    public int getMaxConnections() { return maxConnections; }
    public void setMaxConnections(int value) { maxConnections = bounded(value, 1, 512); }
    public int getMaxConnectionsPerUser() { return maxConnectionsPerUser; }
    public void setMaxConnectionsPerUser(int value) { maxConnectionsPerUser = bounded(value, 1, 16); }
    public int getQueueCapacity() { return queueCapacity; }
    public void setQueueCapacity(int value) { queueCapacity = bounded(value, 2, 128); }
    public long getHeartbeatMillis() { return heartbeatMillis; }
    public void setHeartbeatMillis(long value) { heartbeatMillis = bounded(value, 1_000, 30_000); }
    public long getSendTimeoutMillis() { return sendTimeoutMillis; }
    public void setSendTimeoutMillis(long value) { sendTimeoutMillis = bounded(value, 1_000, 30_000); }
    public long getConnectionTtlMillis() { return connectionTtlMillis; }
    public void setConnectionTtlMillis(long value) { connectionTtlMillis = bounded(value, 1_000, 300_000); }
    public int getEventBudget() { return eventBudget; }
    public void setEventBudget(int value) { eventBudget = bounded(value, 2, 4096); }
    private static int bounded(int n, int min, int max) {
        if (n < min || n > max) throw new IllegalArgumentException("实时连接配置超出支持范围");
        return n;
    }
    private static long bounded(long n, long min, long max) {
        if (n < min || n > max) throw new IllegalArgumentException("实时连接配置超出支持范围");
        return n;
    }
}
