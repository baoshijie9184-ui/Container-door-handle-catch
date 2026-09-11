package com.ruanzhu.doorhandle.module.app.dto.chat;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class ChatSendMessageRequest {

    private String sessionId;

    @NotBlank(message = "消息内容不能为空")
    private String content;

    private String currentRoute;

    private String currentPageTitle;
}
