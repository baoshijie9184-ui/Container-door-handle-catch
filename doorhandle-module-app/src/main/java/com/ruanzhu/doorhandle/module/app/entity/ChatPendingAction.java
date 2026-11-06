package com.ruanzhu.doorhandle.module.app.entity;

import lombok.Data;

import java.time.LocalDateTime;

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
}
