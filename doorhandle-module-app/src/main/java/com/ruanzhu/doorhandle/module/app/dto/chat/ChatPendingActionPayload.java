package com.ruanzhu.doorhandle.module.app.dto.chat;

import lombok.Data;

@Data
public class ChatPendingActionPayload {

    private String username;
    private String userPrompt;
    private String intent;
    private String targetAgent;
}
