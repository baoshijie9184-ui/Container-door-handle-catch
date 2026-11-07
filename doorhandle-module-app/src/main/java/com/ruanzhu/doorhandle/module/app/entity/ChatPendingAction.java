package com.ruanzhu.doorhandle.module.app.entity;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.Map;

@Data
public class ChatPendingAction {

    private Long id;

    private String actionId;

    private String sessionId;

    private String actionType;

    private String actionPayloadJson;

    private String status;

    private LocalDateTime createdAt;

    private LocalDateTime confirmedAt;

    private String errorMessage;

    /** Historical source timezone status; current UTC writes remain separately timestamped. */
    private String clockStatus = "UTC";

    private Map<String,String> sourceWallTimes = Map.of();
}
