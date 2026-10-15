package com.ruanzhu.doorhandle.module.ai.config;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/** Agent runtime options. Model credentials are bound separately by AgentModelProperties. */
@Validated
@ConfigurationProperties(prefix = "agentscope.ai")
public class AgentScopeProperties {
    private boolean enabled;
    @NotBlank
    private String model = "dashscope:qwen-plus";
    private String agentId = "doorhandle-assistant";
    private String name = "doorhandle-assistant";
    private String systemPrompt = "你是门把手缺陷检测系统的智能助手。优先使用系统提供的检测、设备和模型数据回答问题；不确定时明确说明，不要编造结果。";
    private String workspace = "${user.dir}/.agentscope/workspace";
    @Min(1)
    private int maxIters = 12;
    private boolean enableReasoning;
    private boolean emitTokenUsage;

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public String getAgentId() { return agentId; }
    public void setAgentId(String agentId) { this.agentId = agentId; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getSystemPrompt() { return systemPrompt; }
    public void setSystemPrompt(String systemPrompt) { this.systemPrompt = systemPrompt; }
    public String getWorkspace() { return workspace; }
    public void setWorkspace(String workspace) { this.workspace = workspace; }
    public int getMaxIters() { return maxIters; }
    public void setMaxIters(int maxIters) { this.maxIters = maxIters; }
    public boolean isEnableReasoning() { return enableReasoning; }
    public void setEnableReasoning(boolean enableReasoning) { this.enableReasoning = enableReasoning; }
    public boolean isEmitTokenUsage() { return emitTokenUsage; }
    public void setEmitTokenUsage(boolean emitTokenUsage) { this.emitTokenUsage = emitTokenUsage; }
}
