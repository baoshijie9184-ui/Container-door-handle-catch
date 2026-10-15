package com.ruanzhu.doorhandle.module.ai.agent;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import java.util.List;

/** 两类主 Agent，专业能力按可用门面注册，只声明已实现工具。 */
public final class RoleAgentCatalog {
    private RoleAgentCatalog() {}
    public record Definition(String id, String description, List<String> tools) {}
    public static String mainId(AgentActor actor) {
        return actor.supervisor() ? "supervisor-main" : "employee-main";
    }
    public static List<Definition> specialists(AgentActor actor) {
        return specialists(actor,false);
    }
    public static List<Definition> specialists(AgentActor actor,boolean confirmation) {
        return specialists(actor,confirmation,false,false);
    }
    public static List<Definition> specialists(AgentActor actor,boolean confirmation,boolean reports,boolean drafts) {
        var result=new java.util.ArrayList<Definition>(actor.supervisor() ? List.of(
                new Definition("detection-quality", confirmation?"检测质检查询，提出需人工确认的质检分配":"检测质检管理，查询任务和质检记录", confirmation?List.of("search_detection_tasks", "get_task_detail", "get_quality_records","propose_quality_assignment"):List.of("search_detection_tasks", "get_task_detail", "get_quality_records")),
                new Definition("resource-management", "设备资源查询", List.of("list_devices")),
                new Definition("model-ops", "模型目录、版本和发布状态查询", List.of("list_models")),
                new Definition("department-analytics", "当前单企业检测工作量统计", List.of("get_department_work_metrics")))
                : List.of(
                new Definition("detection-task", "本人及分派的检测任务和进度查询", List.of("get_my_detection_tasks", "get_task_detail")),
                new Definition("quality-review", "本人任务质检记录查询", List.of("get_my_quality_records", "get_task_detail")),
                new Definition("device-status", "查询本人任务关联的设备名称；暂不提供实时设备状态和绑定设备清单", List.of("get_task_detail")),
                new Definition("personal-analytics", "本人及分派的检测任务工作量统计", List.of("get_my_work_metrics"))));
        if(reports)result.add(new Definition("report-assistant",actor.supervisor()?"查询授权报告与待审批列表，按明确请求保存本人草稿；审批请到报告页面人工确认":"查询本人报告，按明确请求编写或编辑本人草稿；提交审批请到报告页面",
                drafts?List.of("list_quality_reports","get_quality_report","create_report_draft","edit_report_draft"):List.of("list_quality_reports","get_quality_report")));
        return List.copyOf(result);
    }
}
