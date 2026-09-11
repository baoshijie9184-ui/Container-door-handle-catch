package com.ruanzhu.doorhandle.module.app.dto.chat;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class ChatProjectResponse {

    private String projectId;
    private String name;
    private String description;
    private String color;
    private Integer sortOrder;
    private String createdAt;
    private String updatedAt;
    private int sessionCount;
    private List<ChatSessionResponse> sessions = new ArrayList<>();
}
