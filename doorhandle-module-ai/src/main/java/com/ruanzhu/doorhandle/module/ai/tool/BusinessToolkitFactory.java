package com.ruanzhu.doorhandle.module.ai.tool;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentCatalog;
import com.ruanzhu.doorhandle.module.ai.action.AgentActionService;
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
    private final AgentActionService actions;
    private final com.ruanzhu.doorhandle.module.ai.report.AgentReportGateway reports;
    private final SystemHealthReadApi health;
    public BusinessToolkitFactory(DetectionAgentReadApi detection, ResourceAgentReadApi resources,
                                  ModelAgentReadApi models, ObjectMapper json) {
        this(detection,resources,models,json,null);
    }
    public BusinessToolkitFactory(DetectionAgentReadApi detection,ResourceAgentReadApi resources,ModelAgentReadApi models,ObjectMapper json,AgentActionService actions) {
        this(detection,resources,models,json,actions,null);
    }
    public BusinessToolkitFactory(DetectionAgentReadApi detection,ResourceAgentReadApi resources,ModelAgentReadApi models,ObjectMapper json,AgentActionService actions,com.ruanzhu.doorhandle.module.ai.report.AgentReportGateway reports) {
        this(detection,resources,models,json,actions,reports,null);
    }
    public BusinessToolkitFactory(DetectionAgentReadApi detection,ResourceAgentReadApi resources,ModelAgentReadApi models,ObjectMapper json,AgentActionService actions,com.ruanzhu.doorhandle.module.ai.report.AgentReportGateway reports,SystemHealthReadApi health) {
        this.detection = detection; this.resources = resources; this.models = models; this.json = json; this.actions=actions;this.reports=reports;this.health=health;
    }
    public boolean reportsEnabled(){return reports!=null;}
    public boolean reportDraftsEnabled(){return reports!=null&&reports.draftsEnabled();}
    public boolean confirmationEnabled() {return actions!=null&&actions.enabled();}
    public Toolkit create(AgentActor actor, RoleAgentCatalog.Definition definition) {
        return create(actor,definition,null);
    }
    public Toolkit create(AgentActor actor,RoleAgentCatalog.Definition definition,String runId) {
        return create(actor,definition,runId,null);
    }
    public Toolkit create(AgentActor actor,RoleAgentCatalog.Definition definition,String runId,com.ruanzhu.doorhandle.module.ai.card.AgentCardCollector cards) {
        if (!RoleAgentCatalog.specialists(actor,confirmationEnabled(),reportsEnabled(),reportDraftsEnabled()).contains(definition)) throw new SecurityException("无权注册该专业 Agent");
        Toolkit toolkit = new Toolkit();
        for (String name : definition.tools()) {
            AgentTool tool=com.ruanzhu.doorhandle.module.ai.report.ReportTools.NAMES.contains(name)?new com.ruanzhu.doorhandle.module.ai.report.ReportTools(name,actor,runId,reports,json):name.equals(AgentActionService.TOOL)?new ProposalTool(actor,runId):new ReadTool(actor,name);
            toolkit.registerAgentTool(cards==null?tool:cards.observe(tool));
        }
        return toolkit;
    }
    private class ProposalTool implements AgentTool {
        private final AgentActor actor; private final String runId;
        ProposalTool(AgentActor actor,String runId) {this.actor=actor;this.runId=runId;}
        public String getName() {return AgentActionService.TOOL;}
        public String getDescription() {return "主管提出质检任务分配，必须提供任务编号、质检站点和现有员工账号；只保存待确认提议，不执行业务分配。用户必须在确认卡片确认，不接受聊天文本作为批准。返回 PENDING 不代表任务已分配。";}
        public boolean isReadOnly() {return false;}
        public Map<String,Object> getParameters() {return Map.of("type","object","additionalProperties",false,"required",List.of("taskId","qualityStation","assignee"),"properties",Map.of(
                "taskId",Map.of("type","string","pattern","^[A-Za-z0-9_-]{1,128}$"),
                "qualityStation",Map.of("type","string","minLength",1,"maxLength",64),
                "assignee",Map.of("type","string","pattern","^[A-Za-z0-9_.-]{1,50}$"),
                "dueAt",Map.of("type","string","maxLength",19,"description","可选本地截止时间 YYYY-MM-DDTHH:mm:ss，省略保留原截止时间"),
                "assignmentRemark",Map.of("type","string","maxLength",500)));}
        public Mono<ToolResultBlock> callAsync(ToolCallParam param) {
            return Mono.fromCallable(()->{
                if(runId==null)throw new IllegalStateException("缺少受信运行上下文");
                var input=param.getInput()==null?Map.<String,Object>of():param.getInput();
                if(!Set.of("taskId","qualityStation","assignee","dueAt","assignmentRemark").containsAll(input.keySet())) throw new IllegalArgumentException();
                for(var value:input.values())if(!(value instanceof String))throw new IllegalArgumentException();
                var command=new DetectionAssignmentApi.Command(string(input,"taskId"),string(input,"qualityStation"),string(input,"assignee"),(String)input.get("dueAt"),(String)input.get("assignmentRemark"));
                var saved=actions.propose(actor,runId,param.getToolUseBlock()==null?null:param.getToolUseBlock().getId(),command);
                String message="PENDING".equals(saved.status())?"分配提议已保存，请用户在确认卡片批准；尚未执行分配":
                        "SUCCEEDED".equals(saved.status())?"该提议此前已完成，返回已记录结果，未再次执行":"该提议已终结，返回原状态，未执行新的分配";
                return ToolResultBlock.text(json.writeValueAsString(Map.of("action",saved,"businessExecuted","SUCCEEDED".equals(saved.status()),"message",message)));
            }).subscribeOn(Schedulers.boundedElastic()).onErrorResume(error->Mono.just(ToolResultBlock.error(error instanceof SecurityException?"此操作仅允许主管提出":error instanceof IllegalArgumentException?"任务、责任人员工账号或分配参数不符合条件":"分配提议保存失败，未执行分配")));
        }
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
                case "list_device_alerts" -> "主管按状态、级别、设备主键查询数据库最新入库的采集告警摘要，默认 OPEN 未处理、级别 ALL。按主键降序游标分页；有更多时用 nextCursor 作为下一次 beforeId，保持其他筛选一致。只读，不确认或关闭告警；不返回自由文本说明、运行快照、文件路径或人员备注。结果是 queriedAt 时的记录，不代表设备当前仍故障或已修复，不能从一页记录推断总数。";
                case "get_device_alert" -> "主管按告警数据库主键 alertId 查询当前状态摘要，编号 alertCode 不能代替主键。不确认或关闭告警，未处理/已确认/已解决仅表示告警记录状态，不是设备实时健康证明。";
                case "list_models" -> "主管分页查询模型名称、版本、状态及是否默认，不返回模型文件路径";
                case "get_model_operations" -> "主管按检测模型主键 modelId 查询当前登记的 Precision/Recall/mAP/F1、平均推理耗时、测试集、校验/MLOps 状态、发布策略、配置灰度比例、A/B 分组、回滚来源和登记使用次数。只读，不运行评估或发布/回滚，不属于 LLM 供应商管理。指标是登记值而非在线实测，策略是配置而非分流已生效的证据。null 表示未记录或异常字段已隐藏，零是有效值；存在 invalidFields 时提示核对。没有评估协议、数据集版本和在线分流证据时不能推断模型优劣或线上流量。";
                case "get_system_health" -> "主管查询单体应用已接入的存活、就绪、磁盘、数据库、Redis 固定 Actuator 探针摘要。无参数，只读，不执行修复、SSH、Shell 或容器操作。checkedAt/expiresAt 是服务端检查时间及缓存有效期，最多复用 30 秒；status 只汇总 components，不能称全部服务健康。notMonitored 明确列出无实际探针的组件，配置启用不能当作可用。UNKNOWN、超时、繁忙、未注册或读取失败均不能解释为健康，也不能仅凭本结果推断故障根因。";
                default -> "分页查询当前身份可见的检测任务";
            };
        }
        public boolean isReadOnly() { return true; }
        public Map<String, Object> getParameters() {
            Map<String, Object> properties;
            List<String> required = List.of();
            if (name.equals("get_system_health")) {
                properties = Map.of();
            } else if (name.equals("get_task_detail")) {
                properties = Map.of("taskId", Map.of("type", "string", "pattern", "^[A-Za-z0-9_-]{1,128}$"));
                required = List.of("taskId");
            } else if (name.equals("get_model_operations")) {
                properties = Map.of("modelId", Map.of("type","string","pattern","^[1-9][0-9]{0,9}$","description","检测模型正整数数据库主键，十进制字符串，最大 2147483647"));
                required = List.of("modelId");
            } else if (name.equals("get_device_alert")) {
                properties = Map.of("alertId", resourceIdSchema());
                required = List.of("alertId");
            } else if (name.equals("list_device_alerts")) {
                properties = Map.of("status", Map.of("type", "string", "enum", List.of("ALL", "OPEN", "ACKNOWLEDGED", "RESOLVED"), "default", "OPEN"),
                        "level", Map.of("type", "string", "enum", List.of("ALL", "MINOR", "MAJOR", "CRITICAL"), "default", "ALL"),
                        "deviceId", resourceIdSchema(), "beforeId", resourceIdSchema(), "size", integerSchema(1, 100, 20));
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
                    case "list_device_alerts" -> resources.alerts(actor, new ResourceAgentReadApi.AlertQuery(
                            option(input,"status","OPEN"), option(input,"level","ALL"), option(input,"deviceId",null), option(input,"beforeId",null), size));
                    case "get_device_alert" -> resources.alert(actor, resourceId(input,"alertId"));
                    case "list_models" -> models.models(actor, page, size);
                    case "get_model_operations" -> models.operations(actor, modelId(input));
                    case "get_system_health" -> { if(health==null)throw new IllegalStateException("健康门面不可用"); yield health.snapshot(actor); }
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
    private static Map<String, Object> resourceIdSchema() {
        return Map.of("type", "string", "pattern", "^[1-9][0-9]{0,18}$", "description", "正整数数据库主键，十进制字符串，最大 9223372036854775807");
    }
    private static String option(Map<String,Object> input, String key, String fallback) {
        if (!input.containsKey(key)) return fallback;
        if (!(input.get(key) instanceof String value)) throw new IllegalArgumentException("参数必须为字符串");
        return value;
    }
    private static long resourceId(Map<String,Object> input,String key) {
        String id = option(input,key,null);
        if (!AgentCards.validResourceId(id,Long.MAX_VALUE)) throw new IllegalArgumentException("资源 ID 不合法");
        return Long.parseLong(id);
    }
    private static int modelId(Map<String,Object> input) {
        String id = option(input,"modelId",null);
        if (!AgentCards.validResourceId(id,Integer.MAX_VALUE)) throw new IllegalArgumentException("模型 ID 不合法");
        return Integer.parseInt(id);
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
