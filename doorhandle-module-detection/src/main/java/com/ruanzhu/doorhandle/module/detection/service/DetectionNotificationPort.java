package com.ruanzhu.doorhandle.module.detection.service;

/**
 * 检测域向外部通知任务结果的端口。
 *
 * <p>检测模块只定义能力，不依赖聊天或 Agent 实现。</p>
 */
public interface DetectionNotificationPort {

    void notifyTaskCompleted(String sessionId, String content);
}
