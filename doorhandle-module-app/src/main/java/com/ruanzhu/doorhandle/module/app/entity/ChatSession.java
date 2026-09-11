package com.ruanzhu.doorhandle.module.app.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("chat_session")
public class ChatSession {

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    @TableField("session_id")
    private String sessionId;

    @TableField("username")
    private String username;

    @TableField("user_id")
    private Long userId;

    @TableField("title")
    private String title;

    @TableField("status")
    private String status;

    @TableField("pinned")
    private Boolean pinned;

    @TableField("project_id")
    private String projectId;

    @TableField("created_at")
    private LocalDateTime createdAt;

    @TableField("updated_at")
    private LocalDateTime updatedAt;

    @TableField("state_json")
    private String stateJson;

    @TableField("checkpoint_version")
    private Integer checkpointVersion;

    @TableField("checkpoint_node")
    private String checkpointNode;

    @TableField("checkpoint_exit_reason")
    private String checkpointExitReason;

    @TableField("checkpoint_updated_at")
    private LocalDateTime checkpointUpdatedAt;
}
