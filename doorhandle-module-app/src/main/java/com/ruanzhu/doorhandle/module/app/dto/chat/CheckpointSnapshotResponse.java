package com.ruanzhu.doorhandle.module.app.dto.chat;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class CheckpointSnapshotResponse {

    private String sessionId;
    private boolean hasState;
    private int checkpointVersion;
    private String checkpointNode;
    private String checkpointExitReason;
    private String checkpointUpdatedAt;
    private int stateSize;
    private List<String> stateKeys = new ArrayList<>();
    private String guardReason;
    private Integer guardElapsedMs;
    private Integer routeRepeatCount;
    private List<String> nodeTrace = new ArrayList<>();
    private List<String> routeTrace = new ArrayList<>();
    private List<String> nodeVisitSummary = new ArrayList<>();
}
