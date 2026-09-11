package com.ruanzhu.doorhandle.module.app.dto.chat;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class ChatProjectRequest {

    @NotBlank(message = "项目名称不能为空")
    private String name;

    private String description;

    private String color;
}
