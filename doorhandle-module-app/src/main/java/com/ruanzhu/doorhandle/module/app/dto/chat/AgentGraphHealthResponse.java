package com.ruanzhu.doorhandle.module.app.dto.chat;

import lombok.Data;

@Data
public class AgentGraphHealthResponse {

    private long totalRuns;
    private long completedRuns;
    private long pendingConfirmationRuns;
    private long guardBreakRuns;
    private long errorRuns;
    private long fallbackRuns;
    private long totalElapsedMs;
    private long averageElapsedMs;
    private double guardBreakRate;
    private double fallbackRate;
    private String healthStatus;
    private String healthMessage;
    private String lastExitReason;
    private String lastGuardReason;
    private String lastUpdatedAt;
}
