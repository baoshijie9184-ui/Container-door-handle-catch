package com.ruanzhu.doorhandle.module.app.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("chat_pending_action")
public class ChatPendingAction {

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    @TableField("action_id")
    private String actionId;

    @TableField("session_id")
    private String sessionId;

    @TableField("action_type")
    private String actionType;

    @TableField("action_payload_json")
    private String actionPayloadJson;

    @TableField("status")
    private String status;

    @TableField("created_at")
    private LocalDateTime createdAt;

    @TableField("confirmed_at")
    private LocalDateTime confirmedAt;

    @TableField("error_message")
    private String errorMessage;
}
