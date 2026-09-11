package com.ruanzhu.doorhandle.module.app.config.properties;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Data
@Configuration
@ConfigurationProperties(prefix = "agent.graph.guard")
public class AgentGraphGuardProperties {

    /**
     * 单轮图执行最大耗时，超过后保护性中断。
     */
    private Long maxExecutionMs = 15000L;

    /**
     * 同一节点在单轮执行中的最大访问次数。
     */
    private Integer maxVisitsPerNode = 4;

    /**
     * 同一路由连续重复跳转的最大次数。
     */
    private Integer maxRepeatRoute = 3;

    /**
     * checkpoint 中保留的最近节点/路由轨迹长度。
     */
    private Integer maxTraceSize = 24;
}
