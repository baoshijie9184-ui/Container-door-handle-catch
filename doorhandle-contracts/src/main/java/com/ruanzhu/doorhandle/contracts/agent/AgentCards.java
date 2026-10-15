package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;
import java.util.Map;
import java.util.Set;

/** 卡片仅持久化受控资源引用；正文、布局与业务动作不能由模型指定。 */
public final class AgentCards {
    private AgentCards() {}
    public static final String MESSAGE_TYPE = "AGENT_CARDS";
    public static final Set<String> TASK_TOOLS = Set.of("get_task_detail", "get_my_detection_tasks", "search_detection_tasks", "get_my_quality_records", "get_quality_records");
    public static final Set<String> METRIC_TOOLS = Set.of("get_my_work_metrics", "get_department_work_metrics");
    public static final Set<String> REPORT_TOOLS = Set.of("list_quality_reports", "get_quality_report", "create_report_draft", "edit_report_draft");

    public record Reference(String type, String tool, List<String> ids, Integer days) {
        public Reference {
            if (type == null || tool == null || ids == null || ids.size() > 5)
                throw new IllegalArgumentException("卡片引用不合法");
            ids = List.copyOf(ids);
            if (Set.copyOf(ids).size() != ids.size()) throw new IllegalArgumentException("卡片引用重复");
            boolean valid = switch (type) {
                case "TASKS" -> TASK_TOOLS.contains(tool) && days == null && ids.stream().allMatch(id -> id.matches("[A-Za-z0-9_-]{1,128}"));
                case "REPORTS" -> REPORT_TOOLS.contains(tool) && days == null && ids.stream().allMatch(id -> id.matches("qr-[a-f0-9-]{36}"));
                case "METRICS" -> METRIC_TOOLS.contains(tool) && ids.isEmpty() && days != null && days >= 1 && days <= 366;
                default -> false;
            };
            if (!valid) throw new IllegalArgumentException("未登记卡片或参数不合法");
        }
    }
    public record Envelope(int version, String text, String runId, List<Reference> cards) {
        public Envelope {
            if (version != 1 || text == null || cards == null || cards.size() > 8
                    || runId != null && !runId.matches("[A-Za-z0-9_:.-]{1,128}"))
                throw new IllegalArgumentException("卡片消息不合法");
            cards = List.copyOf(cards);
        }
    }
    /** 只读实时视图；items 仅放门面白名单字段，不返回报告正文或内部路径。 */
    public record View(String type, String tool, String status, List<?> items, Map<String, Object> metrics,
                       String from, String to, String scope, String message, String updatedAt) {}
}
