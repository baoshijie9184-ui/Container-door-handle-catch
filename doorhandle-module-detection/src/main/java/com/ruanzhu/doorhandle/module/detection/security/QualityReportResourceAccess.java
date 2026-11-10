package com.ruanzhu.doorhandle.module.detection.security;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessResourceAccess;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class QualityReportResourceAccess implements BusinessResourceAccess {
    private final JdbcTemplate jdbc;
    private final BusinessUserDirectory users;
    private final DetectionTaskAccessPolicy tasks;
    public QualityReportResourceAccess(JdbcTemplate jdbc, BusinessUserDirectory users, DetectionTaskAccessPolicy tasks) { this.jdbc = jdbc; this.users = users; this.tasks = tasks; }
    public boolean mayRead(AgentActor actor, String scope, String domain, String type, String id) {
        if (!"QUALITY_REPORT".equals(domain) || !"QUALITY_REPORT".equals(type) || id == null || !id.matches("qr-[a-f0-9-]{36}")) return false;
        if (!"PRIVATE".equals(scope) && !"ENTERPRISE".equals(scope)) return false;
        var current = users.current(actor.userId(), actor.username());
        var rows = jdbc.queryForList("SELECT r.owner_user_id,r.status,t.task_id,t.created_by,t.assignee FROM quality_report r JOIN detection_task t ON t.task_id=r.task_id WHERE r.report_id=?", id);
        if (rows.isEmpty()) return false;
        var row = rows.get(0); boolean owner = ((Number) row.get("owner_user_id")).longValue() == current.userId();
        if (!owner && ("PRIVATE".equals(scope) || !current.supervisor() || "DRAFT".equals(row.get("status")))) return false;
        var task = new DetectionTask(); task.setTaskId((String) row.get("task_id")); task.setCreatedBy((String) row.get("created_by")); task.setAssignee((String) row.get("assignee"));
        return tasks.canAccess(task, new AgentActor(current.userId(), current.username(), current.supervisor() ? AgentActor.Role.SUPERVISOR : AgentActor.Role.INSPECTOR));
    }
}
