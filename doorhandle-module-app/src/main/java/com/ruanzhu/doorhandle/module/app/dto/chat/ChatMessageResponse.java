package com.ruanzhu.doorhandle.module.app.dto.chat;

import lombok.Data;

@Data
public class ChatMessageResponse {

    private Long id;
    private String sessionId;
    private String role;
    private String messageType;
    private String content;
    private String intent;
    private String actionId;
    private String createdAt;
    private String runId;
    /** Provenance of the historical execution link; never substitutes for createdAt. */
    private String executionClockStatus;
    private java.util.Map<String,String> executionSourceWallTimes;
}
