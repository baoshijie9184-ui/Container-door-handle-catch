package com.ruanzhu.doorhandle.contracts.agent;

import java.time.Instant;
import java.util.List;

/** 单体应用的受控健康摘要，不返回原始 Actuator details 或部署连接信息。 */
public interface SystemHealthReadApi {
    record Component(String id, String status, String evidence) {}
    /** status 仅汇总 components 中已接入的探针，不覆盖 notMonitored。 */
    record Snapshot(String status, List<Component> components, List<String> notMonitored, Instant checkedAt, Instant expiresAt) {
        public Snapshot { components = List.copyOf(components); notMonitored = List.copyOf(notMonitored); }
    }
    Snapshot snapshot(AgentActor actor);
}
