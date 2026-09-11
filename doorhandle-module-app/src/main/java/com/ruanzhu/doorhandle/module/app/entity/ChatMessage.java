package com.ruanzhu.doorhandle.module.app.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("chat_message")
public class ChatMessage {

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    @TableField("session_id")
    private String sessionId;

    @TableField("role")
    private String role;

    @TableField("message_type")
    private String messageType;

    @TableField("content")
    private String content;

    @TableField("intent")
    private String intent;

    @TableField("action_id")
    private String actionId;

    @TableField("created_at")
    private LocalDateTime createdAt;
}
