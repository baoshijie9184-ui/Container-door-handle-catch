package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;
import java.util.Set;
import java.time.LocalDateTime;

public interface ResourceAgentReadApi {
    record DeviceView(String deviceId, String deviceCode, String status, String onlineStatus,
                      String plcStatus, String cameraStatus, String captureStatus) {}
    List<DeviceView> devices(AgentActor actor, int page, int size);
    DeviceView device(AgentActor actor, long deviceId);

    /** 仅返回状态摘要，不传递运行快照、自由文本告警内容或人员备注。ID 均为数据库主键。 */
    record AlertView(String alertId, String alertCode, String deviceId, String deviceCode,
                     String type, String level, String status, LocalDateTime createdAt, LocalDateTime updatedAt) {}
    record AlertPage(List<AlertView> items, String nextCursor, boolean hasMore, LocalDateTime queriedAt) {
        public AlertPage { items = List.copyOf(items); }
    }
    record AlertQuery(String status, String level, String deviceId, String beforeId, int size) {
        public AlertQuery {
            status = status == null ? "OPEN" : status;
            level = level == null ? "ALL" : level;
            if (!Set.of("ALL", "OPEN", "ACKNOWLEDGED", "RESOLVED").contains(status)
                    || !Set.of("ALL", "MINOR", "MAJOR", "CRITICAL").contains(level) || size < 1 || size > 100)
                throw new IllegalArgumentException("告警筛选参数不合法");
            for (String id : new String[]{deviceId, beforeId}) {
                if (id != null) {
                    if (!id.matches("[1-9][0-9]{0,18}")) throw new IllegalArgumentException("资源 ID 不合法");
                    try { Long.parseLong(id); }
                    catch (NumberFormatException error) { throw new IllegalArgumentException("资源 ID 超出范围"); }
                }
            }
        }
    }
    AlertPage alerts(AgentActor actor, AlertQuery query);
    AlertView alert(AgentActor actor, long alertId);
}
