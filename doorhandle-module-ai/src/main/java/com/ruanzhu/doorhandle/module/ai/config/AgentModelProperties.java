package com.ruanzhu.doorhandle.module.ai.config;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;
import java.time.Duration;
import java.util.List;

/** Server-owned model credentials. Never serialize this configuration to clients. */
@Validated
@ConfigurationProperties(prefix = "agentscope.models")
public class AgentModelProperties {
    private Duration timeout = Duration.ofSeconds(60);
    @Min(0) @Max(3) private int maxRetries = 2;
    @Min(16) private int maxOutputTokens = 2048;
    private boolean fallbackEnabled;
    private String fallbackModel = "deepseek:deepseek-flash";
    private List<String> fallbackModels = List.of();
    private Duration firstTokenTimeout = Duration.ofSeconds(15);
    @Min(1) private int failureThreshold = 2;
    private Duration circuitCooldown = Duration.ofSeconds(60);
    private Duration quotaCooldown = Duration.ofMinutes(5);
    private boolean store;
    private String actorAuthorization = "";
    private String proxyUrl = "";
    private String gatewayBaseUrl = "";
    private Connection dashscope = new Connection("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus");
    private Connection deepseek = new Connection("https://api.deepseek.com", "deepseek-flash");
    private Connection openai = new Connection("https://api.openai.com/v1", "gpt-4o-mini");

    public Duration getTimeout() { return timeout; }
    public void setTimeout(Duration value) { timeout = value; }
    public int getMaxRetries() { return maxRetries; }
    public void setMaxRetries(int value) { maxRetries = value; }
    public int getMaxOutputTokens() { return maxOutputTokens; }
    public void setMaxOutputTokens(int value) { maxOutputTokens = value; }
    public boolean isFallbackEnabled() { return fallbackEnabled; }
    public void setFallbackEnabled(boolean value) { fallbackEnabled = value; }
    public String getFallbackModel() { return fallbackModel; }
    public void setFallbackModel(String value) { fallbackModel = value; }
    public List<String> getFallbackModels() { return fallbackModels; }
    public void setFallbackModels(List<String> value) { fallbackModels = value; }
    public Duration getFirstTokenTimeout() { return firstTokenTimeout; }
    public void setFirstTokenTimeout(Duration value) { firstTokenTimeout = value; }
    public int getFailureThreshold() { return failureThreshold; }
    public void setFailureThreshold(int value) { failureThreshold = value; }
    public Duration getCircuitCooldown() { return circuitCooldown; }
    public void setCircuitCooldown(Duration value) { circuitCooldown = value; }
    public Duration getQuotaCooldown() { return quotaCooldown; }
    public void setQuotaCooldown(Duration value) { quotaCooldown = value; }
    public boolean isStore() { return store; }
    public void setStore(boolean value) { store = value; }
    public String getActorAuthorization() { return actorAuthorization; }
    public void setActorAuthorization(String value) { actorAuthorization = value; }
    public String getProxyUrl() { return proxyUrl; }
    public void setProxyUrl(String value) { proxyUrl = value; }
    public String getGatewayBaseUrl() { return gatewayBaseUrl; }
    public void setGatewayBaseUrl(String value) { gatewayBaseUrl = value; }
    public Connection getDashscope() { return dashscope; }
    public void setDashscope(Connection value) { dashscope = value; }
    public Connection getDeepseek() { return deepseek; }
    public void setDeepseek(Connection value) { deepseek = value; }
    public Connection getOpenai() { return openai; }
    public void setOpenai(Connection value) { openai = value; }

    public static class Connection {
        private String apiKey = "";
        private String baseUrl;
        private String model;
        public Connection() {}
        public Connection(String baseUrl, String model) { this.baseUrl = baseUrl; this.model = model; }
        public String getApiKey() { return apiKey; }
        public void setApiKey(String value) { apiKey = value; }
        public String getBaseUrl() { return baseUrl; }
        public void setBaseUrl(String value) { baseUrl = value; }
        public String getModel() { return model; }
        public void setModel(String value) { model = value; }
    }
}
