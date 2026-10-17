package com.ruanzhu.doorhandle.module.app.dto.chat;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class ChatSessionResponse {

    private String sessionId;
    private String title;
    private String status;
    private boolean pinned;
    private String projectId;
    private String sourceSessionId;
    private Long forkMessageId;
    private String updatedAt;
    private int messageCount;
    private String lastMessage;
    private List<ChatMessageResponse> messages = new ArrayList<>();
}
