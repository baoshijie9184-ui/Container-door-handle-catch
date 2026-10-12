package com.ruanzhu.doorhandle.module.ai.tool;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentCatalog;
import io.agentscope.core.message.ToolResultBlock;
import io.agentscope.core.tool.*;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;
import java.time.Duration;
import java.util.*;

/** 每请求、每专业 Agent 单独创建，身份通过闭包绑定，不依赖异步线程上下文。 */
public class BusinessToolkitFactory {
    private final DetectionAgentReadApi detection;
    private final ResourceAgentReadApi resources;
    private final ModelAgentReadApi models;
    private final ObjectMapper json;
    public BusinessToolkitFactory(DetectionAgentReadApi detection, ResourceAgentReadApi resources,
                                  ModelAgentReadApi models, ObjectMapper json) {
        this.detection = detection; this.resources = resources; this.models = models; this.json = json;
    }
    public Toolkit create(AgentActor actor, RoleAgentCatalog.Definition definition) {
        if (!RoleAgentCatalog.specialists(actor).contains(definition)) throw new SecurityException("无权注册该专业 Agent");
        Toolkit toolkit = new Toolkit();
        for (String name : definition.tools()) toolkit.registerAgentTool(new ReadTool(actor, name));
        return toolkit;
    }
    private class ReadTool implements AgentTool {
        private final AgentActor actor;
        private final String name;
        ReadTool(AgentActor actor, String name) { this.actor = actor; this.name = name; }
        public String getName() { return name; }
        public String getDescription() {
            return switch (name) {
                case "get_task_detail" -> "按 taskId 查询授权任务的进度、缺陷数量、复核状态及任务记录中的设备名称，不含实时设备状态";
                case "get_my_work_metrics", "get_department_work_metrics" -> "按任务创建时间统计最近 days 天的任务数、图片数和缺陷数量；缺陷数量不能当作缺陷图片数计算不良率";
                case "get_my_quality_records", "get_quality_records" -> "分页查询有复核状态的质检记录，包含历史记录，不等同于待办队列";
                case "list_devices" -> "主管分页查询设备在线及 PLC、相机、采集状态";
                case "list_models" -> "主管分页查询模型名称、版本、状态及是否默认，不返回模型文件路径";
                default -> "分页查询当前身份可见的检测任务";
            };
        }
        public boolean isReadOnly() { return true; }
        public Map<String, Object> getParameters() {
            Map<String, Object> properties;
            List<String> required = List.of();
            if (name.equals("get_task_detail")) {
                properties = Map.of("taskId", Map.of("type", "string", "pattern", "^[A-Za-z0-9_-]{1,128}$"));
                required = List.of("taskId");
            } else if (name.endsWith("work_metrics")) {
                properties = Map.of("days", integerSchema(1, 366, 7));
            } else {
                properties = Map.of("page", integerSchema(1, 10000, 1), "size", integerSchema(1, 100, 20));
            }
            return Map.of("type", "object", "properties", properties, "required", required, "additionalProperties", false);
        }
        public Mono<ToolResultBlock> callAsync(ToolCallParam param) {
            return Mono.fromCallable(() -> {
                Map<String, Object> input = param.getInput() == null ? Map.of() : param.getInput();
                @SuppressWarnings("unchecked")
                var allowed = ((Map<String, Object>) getParameters().get("properties")).keySet();
                if (!allowed.containsAll(input.keySet())) throw new IllegalArgumentException("工具参数不在白名单中");
                int page = number(input, "page", 1), size = number(input, "size", 20);
                Object data = switch (name) {
                    case "get_my_detection_tasks", "search_detection_tasks" -> detection.tasks(actor, page, size, false);
                    case "get_my_quality_records", "get_quality_records" -> detection.tasks(actor, page, size, true);
                    case "get_task_detail" -> detection.task(actor, string(input, "taskId"));
                    case "get_my_work_metrics", "get_department_work_metrics" -> detection.metrics(actor, number(input, "days", 7));
                    case "list_devices" -> resources.devices(actor, page, size);
                    case "list_models" -> models.models(actor, page, size);
                    default -> throw new SecurityException("工具未授权");
                };
                return ToolResultBlock.text(json.writeValueAsString(Map.of("data", data, "source", name,
                        "traceId", UUID.randomUUID().toString(), "status", "OK", "error", "")));
            }).subscribeOn(Schedulers.boundedElastic()).timeout(Duration.ofSeconds(15))
                    .onErrorResume(e -> Mono.just(ToolResultBlock.error(
                            e instanceof SecurityException ? "无访问权限或资源不存在" :
                            e instanceof IllegalArgumentException ? "工具参数不合法" : "业务查询失败，请稍后重试")));
        }
    }
    private static Map<String, Object> integerSchema(int min, int max, int value) {
        return Map.of("type", "integer", "minimum", min, "maximum", max, "default", value);
    }
    private static int number(Map<String, Object> input, String key, int defaultValue) {
        if (!input.containsKey(key)) return defaultValue;
        Object value = input.get(key);
        if (!(value instanceof Number n) || !Double.isFinite(n.doubleValue())
                || n.doubleValue() != n.intValue()) throw new IllegalArgumentException("参数必须为整数");
        int result = n.intValue();
        int max = key.equals("page") ? 10000 : key.equals("days") ? 366 : 100;
        if (result < 1 || result > max) throw new IllegalArgumentException("参数超出范围");
        return result;
    }
    private static String string(Map<String, Object> input, String key) {
        if (!(input.get(key) instanceof String s) || s.isBlank()) throw new IllegalArgumentException("缺少任务编号");
        return s;
    }
}
