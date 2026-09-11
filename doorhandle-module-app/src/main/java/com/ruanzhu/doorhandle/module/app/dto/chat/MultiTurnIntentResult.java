package com.ruanzhu.doorhandle.module.app.dto.chat;

import lombok.Data;

import java.util.Collections;
import java.util.Map;

/**
 * 多轮对话意图分类结果，包含意图类型、槽位更新、目标 Agent 和执行类型。
 */
@Data
public class MultiTurnIntentResult {
    /** NEW_TASK / SUPPLEMENT / MODIFY / FOLLOWUP / CHITCHAT */
    private String intent;
    /** 从用户消息中提取的槽位键值对 */
    private Map<String, Object> slotUpdates;
    /** DETECTION / RESOURCE / REPORT / OPS */
    private String targetAgent;
    /** 是否需要确认（写操作） */
    private boolean isAction;

    public static MultiTurnIntentResult defaultResult() {
        MultiTurnIntentResult r = new MultiTurnIntentResult();
        r.intent = "CHITCHAT";
        r.slotUpdates = Collections.emptyMap();
        r.targetAgent = "OPS";
        r.isAction = false;
        return r;
    }
}
