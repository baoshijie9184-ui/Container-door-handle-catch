package com.ruanzhu.doorhandle.module.ai.card;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentCards;
import io.agentscope.core.message.*;
import io.agentscope.core.tool.*;
import reactor.core.publisher.Mono;
import java.util.*;

/** 每轮独立收集成功业务工具的资源引用，不解析模型回复，不写入运行审计正文。 */
public final class AgentCardCollector {
    private final ObjectMapper json;
    private final LinkedHashSet<AgentCards.Reference> cards = new LinkedHashSet<>();
    public AgentCardCollector(ObjectMapper json) { this.json = json; }
    public synchronized List<AgentCards.Reference> snapshot() { return List.copyOf(cards); }
    public AgentTool observe(AgentTool tool) {
        return new AgentTool() {
            public String getName() { return tool.getName(); }
            public String getDescription() { return tool.getDescription(); }
            public Map<String,Object> getParameters() { return tool.getParameters(); }
            public Boolean getStrict() { return tool.getStrict(); }
            public Map<String,Object> getOutputSchema() { return tool.getOutputSchema(); }
            public boolean isReadOnly() { return tool.isReadOnly(); }
            public boolean isReturnDirect() { return tool.isReturnDirect(); }
            public Mono<ToolResultBlock> callAsync(ToolCallParam param) {
                return tool.callAsync(param).doOnNext(result -> collect(tool.getName(), param.getInput(), result));
            }
        };
    }
    private synchronized void collect(String tool, Map<String,Object> input, ToolResultBlock result) {
        // 2.0.4 的 ToolResultBlock.text 在 Toolkit 标记终态前为 RUNNING；这里观察的是已返回的 Mono 结果，仍须校验业务 status/source。
        if (cards.size() >= 8 || result == null || !Set.of(ToolResultState.RUNNING,ToolResultState.SUCCESS).contains(result.getState()) || result.isSuspended()) return;
        try {
            String text = result.getOutput().stream().filter(TextBlock.class::isInstance).map(TextBlock.class::cast)
                    .map(TextBlock::getText).reduce("", String::concat);
            if (text.length() > 1_000_000) return;
            JsonNode root = json.readTree(text);
            if (!"OK".equals(root.path("status").asText()) || !tool.equals(root.path("source").asText())) return;
            JsonNode data = root.path("data");
            AgentCards.Reference ref;
            if (AgentCards.TASK_TOOLS.contains(tool)) {
                var ids = tool.equals("get_task_detail") ? List.of(data.path("taskId").asText()) : ids(data.path("items"), "taskId");
                ref = new AgentCards.Reference("TASKS", tool, ids, null);
            } else if (AgentCards.REPORT_TOOLS.contains(tool)) {
                var ids = tool.equals("list_quality_reports") ? ids(data.path("records"), "reportId") : List.of(data.path("report").path("reportId").asText());
                ref = new AgentCards.Reference("REPORTS", tool, ids, null);
            } else if (AgentCards.ALERT_TOOLS.contains(tool)) {
                var ids = tool.equals("get_device_alert") ? List.of(data.path("alertId").asText()) : ids(data.path("items"), "alertId");
                ref = new AgentCards.Reference("DEVICE_ALERTS", tool, ids, null);
            } else if (AgentCards.DEVICE_TOOLS.contains(tool)) {
                ref = new AgentCards.Reference("DEVICES", tool, ids(data, "deviceId"), null);
            } else if (AgentCards.MODEL_OPERATION_TOOLS.contains(tool)) {
                ref = new AgentCards.Reference("MODEL_OPERATIONS", tool, List.of(data.path("model").path("modelId").asText()), null);
            } else if (AgentCards.MODEL_TOOLS.contains(tool)) {
                ref = new AgentCards.Reference("MODELS", tool, ids(data, "modelId"), null);
            } else if (AgentCards.METRIC_TOOLS.contains(tool)) {
                int days = input != null && input.get("days") instanceof Number n ? n.intValue() : 7;
                ref = new AgentCards.Reference("METRICS", tool, List.of(), days);
            } else return;
            cards.add(ref);
        } catch (Exception ignored) { /* 非法或不支持的结果不影响业务工具完成，也不形成卡片。 */ }
    }
    private List<String> ids(JsonNode items, String field) {
        if (!items.isArray()) throw new IllegalArgumentException();
        var ids = new LinkedHashSet<String>();
        for (JsonNode item : items) { if (ids.size() == 5) break; ids.add(item.path(field).asText()); }
        return List.copyOf(ids);
    }
}
