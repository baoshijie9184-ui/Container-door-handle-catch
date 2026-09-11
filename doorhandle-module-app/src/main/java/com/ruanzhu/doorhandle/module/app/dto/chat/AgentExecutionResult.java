package com.ruanzhu.doorhandle.module.app.dto.chat;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class AgentExecutionResult {

    private String messageType;
    private String content;
    private String intent;
}
