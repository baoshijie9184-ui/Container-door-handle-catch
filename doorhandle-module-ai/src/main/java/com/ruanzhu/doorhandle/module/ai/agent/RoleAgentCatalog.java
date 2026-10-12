package com.ruanzhu.doorhandle.module.ai.agent;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import java.util.List;

/** 两类主 Agent + 各四个专业 Agent；只声明已实现工具。 */
public final class RoleAgentCatalog {
    private RoleAgentCatalog() {}
    public record Definition(String id, String description, List<String> tools) {}
    public static String mainId(AgentActor actor) {
        return actor.supervisor() ? "supervisor-main" : "employee-main";
    }
    public static List<Definition> specialists(AgentActor actor) {
        return actor.supervisor() ? List.of(
                new Definition("detection-quality", "检测质检管理，查询任务和质检记录", List.of("search_detection_tasks", "get_task_detail", "get_quality_records")),
                new Definition("resource-management", "设备资源查询", List.of("list_devices")),
                new Definition("model-ops", "模型目录、版本和发布状态查询", List.of("list_models")),
                new Definition("department-analytics", "当前单企业检测工作量统计", List.of("get_department_work_metrics")))
                : List.of(
                new Definition("detection-task", "本人创建的检测任务和进度查询", List.of("get_my_detection_tasks", "get_task_detail")),
                new Definition("quality-review", "本人任务质检记录查询", List.of("get_my_quality_records", "get_task_detail")),
                new Definition("device-status", "查询本人任务关联的设备名称；暂不提供实时设备状态和绑定设备清单", List.of("get_task_detail")),
                new Definition("personal-analytics", "本人创建的检测任务工作量统计", List.of("get_my_work_metrics")));
    }
}
