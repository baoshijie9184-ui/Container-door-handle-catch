package com.ruanzhu.doorhandle.module.app.dto.chat;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ChatStreamEvent {
    private String type;
    private String sessionId;
    private String content;
    private String message;
    private String intent;
    private String actionId;
    private ChatMessageResponse messageResponse;

    public static ChatStreamEvent status(String sessionId, String message) {
        return ChatStreamEvent.builder()
                .type("status")
                .sessionId(sessionId)
                .message(message)
                .build();
    }
}
