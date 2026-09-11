package com.ruanzhu.doorhandle.module.app.dto.chat;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class ChatConfirmActionRequest {

    @NotBlank(message = "会话编号不能为空")
    private String sessionId;

    @NotBlank(message = "动作编号不能为空")
    private String actionId;

    private boolean confirmed;
}
