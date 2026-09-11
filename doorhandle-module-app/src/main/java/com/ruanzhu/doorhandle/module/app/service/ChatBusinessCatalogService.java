package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Locale;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class ChatBusinessCatalogService {

    private final ObjectMapper objectMapper;

    private record BusinessModule(
            String name,
            String route,
            String agent,
            String summary,
            List<String> keywords,
            List<String> examples
    ) {
    }

    private static final List<BusinessModule> MODULES = List.of(
            new BusinessModule(
                    "检测任务与结果",
                    "#/detection",
                    "DETECTION",
                    "上传图片、创建检测任务、查看进度、结果图、缺陷证据、任务追溯。",
                    List.of("检测", "任务", "图片", "上传", "结果", "结果图", "追溯", "缺陷", "证据"),
                    List.of("查看最近一条检测任务状态", "查看某个任务的缺陷证据链", "按设备编号查询检测记录")
            ),
            new BusinessModule(
                    "质检复核闭环",
                    "#/detection?tab=quality",
                    "DETECTION",
                    "处理待复核、缺陷确认、处置、返工、复检和失败任务。",
                    List.of("质检", "复核", "处置", "返工", "复检", "队列", "误报", "确认"),
                    List.of("查看待复核质检队列", "统计返工复检任务", "说明某个任务为什么需要处置")
            ),
            new BusinessModule(
                    "缺陷证据库",
                    "#/detection?tab=defect-gallery",
                    "DETECTION",
                    "按缺陷类型、严重等级、设备、批次和模型筛选缺陷证据，查看图片证据链和复核状态。",
                    List.of("缺陷证据", "证据库", "缺陷图库", "缺陷图片", "严重缺陷", "缺陷类型", "缺陷等级"),
                    List.of("查看严重缺陷证据", "按设备查询缺陷证据", "查看某个批次的缺陷图片")
            ),
            new BusinessModule(
                    "设备与采集状态",
                    "#/devices",
                    "RESOURCE",
                    "查看设备台账、在线状态、PLC/相机/采集状态、采集告警和设备绑定人员。",
                    List.of("设备", "在线", "采集", "相机", "plc", "告警", "工位", "边缘节点"),
                    List.of("查看当前设备在线状态", "列出采集异常设备", "某台设备绑定了谁")
            ),
            new BusinessModule(
                    "人员与设备绑定",
                    "#/employees",
                    "RESOURCE",
                    "维护员工信息、岗位类型、部门状态，以及人员与设备的绑定关系。",
                    List.of("人员", "员工", "采集员", "质检员", "部门", "岗位", "绑定"),
                    List.of("查询某个员工信息", "查看质检员列表", "某个员工绑定了哪些设备")
            ),
            new BusinessModule(
                    "模型管理与 MLOps",
                    "#/models",
                    "RESOURCE",
                    "管理模型版本、上传、校验、发布、默认模型、评估指标、灰度、A/B 和回滚。",
                    List.of("模型", "mlops", "评估", "指标", "灰度", "回滚", "发布", "默认模型", "ab", "a/b"),
                    List.of("查看模型评估指标", "查看模型灰度发布状态", "哪个模型是默认模型")
            ),
            new BusinessModule(
                    "数据总览与报表",
                    "#/home",
                    "REPORT",
                    "查看检测趋势、区域分布、模型表现、质量处置统计和质检工作量。",
                    List.of("报表", "统计", "趋势", "总览", "首页", "质量", "工作量", "分布"),
                    List.of("生成本周质量处置统计", "查看质检工作量", "总结今日检测趋势")
            ),
            new BusinessModule(
                    "设备使用记录",
                    "#/device-records",
                    "RESOURCE",
                    "查询设备使用、借还、维护和历史流转记录。",
                    List.of("使用记录", "借用", "归还", "维护", "设备记录", "流转"),
                    List.of("查看某台设备使用记录", "统计设备维护记录", "查询最近设备流转")
            ),
            new BusinessModule(
                    "Agent 可观测与稳定性",
                    "聊天面板右上角诊断按钮，或直接问助手",
                    "OPS",
                    "查看 Agent 健康状态、checkpoint、路由轨迹、循环守卫、兜底率和最近异常原因。",
                    List.of("agent健康", "agent 健康", "智能体健康", "智能体状态", "checkpoint", "循环守卫", "路由轨迹", "兜底率", "诊断"),
                    List.of("查看 Agent checkpoint 和健康状态", "智能体为什么触发循环守卫", "查看最近 Agent 路由轨迹")
            ),
            new BusinessModule(
                    "系统运维链路",
                    "无单独页面，可直接问助手",
                    "OPS",
                    "检查 OSS、Kafka、远程 Worker、失败任务和检测链路健康状态。",
                    List.of("系统", "运维", "kafka", "worker", "oss", "健康", "失败", "链路"),
                    List.of("检查OSS、Kafka和远程Worker运行状态", "为什么任务卡住了", "最近是否有失败任务")
            )
    );

    public String buildBusinessMap(String userPrompt) {
        List<BusinessModule> matched = matchModules(userPrompt);
        StringBuilder sb = new StringBuilder();
        sb.append("可以。我把当前平台能力按业务入口整理如下：\n\n");
        for (BusinessModule module : matched) {
            appendModule(sb, module);
        }
        if (matched.size() < MODULES.size()) {
            sb.append("\n如果你想看完整业务地图，可以问我：智能助手能覆盖哪些系统业务功能。");
        }
        sb.append("\n\n说明：查询和分析类问题可以直接在助手里问；创建、修改、删除、发布、回滚等写操作会先走确认流程或引导到对应页面。");
        return sb.toString();
    }

    public String buildBusinessMapCard(String userPrompt) {
        List<BusinessModule> matched = matchModules(userPrompt);
        Map<String, Object> payload = Map.of(
                "type", "business-map",
                "title", matched.size() == MODULES.size() ? "系统业务地图" : "相关业务入口",
                "description", "我把当前问题关联的系统功能、页面入口和可直接提问的示例整理成卡片。",
                "cards", matched.stream().map(module -> Map.of(
                        "title", module.name(),
                        "summary", module.summary(),
                        "route", module.route(),
                        "agent", module.agent(),
                        "examples", module.examples()
                )).toList(),
                "note", "查询和分析类问题可以直接问助手；创建、修改、删除、发布、回滚等写操作会先走确认流程或引导到对应页面。"
        );
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new BusinessException("业务地图卡片序列化失败");
        }
    }

    public String buildFullBusinessMap() {
        StringBuilder sb = new StringBuilder();
        sb.append("系统业务地图：\n\n");
        MODULES.forEach(module -> appendModule(sb, module));
        sb.append("\n你可以直接用自然语言问这些模块的问题；涉及高风险写操作时，我会先说明影响并等待确认。");
        return sb.toString();
    }

    public boolean isBusinessMapQuestion(String userPrompt) {
        String text = normalize(userPrompt);
        return text.contains("在哪")
                || text.contains("入口")
                || text.contains("页面")
                || text.contains("菜单")
                || text.contains("怎么用")
                || text.contains("业务地图")
                || text.contains("功能地图")
                || text.contains("导航")
                || text.contains("下一步");
    }

    private List<BusinessModule> matchModules(String userPrompt) {
        String text = normalize(userPrompt);
        if (text.isBlank()
                || text.contains("全部")
                || text.contains("所有")
                || text.contains("业务地图")
                || text.contains("功能地图")) {
            return MODULES;
        }
        List<BusinessModule> matched = MODULES.stream()
                .filter(module -> module.keywords().stream().anyMatch(text::contains))
                .toList();
        return matched.isEmpty() ? MODULES : matched;
    }

    private void appendModule(StringBuilder sb, BusinessModule module) {
        sb.append("- ").append(module.name())
                .append("：").append(module.summary()).append("\n")
                .append("  入口：").append(formatRoute(module)).append("\n")
                .append("  助手路由：").append(module.agent()).append("\n")
                .append("  可直接问：").append(String.join("；", module.examples())).append("\n");
    }

    private String formatRoute(BusinessModule module) {
        if (module.route().startsWith("#/")) {
            return "[" + module.name() + "](" + module.route() + ")";
        }
        return module.route();
    }

    private String normalize(String userPrompt) {
        return userPrompt == null ? "" : userPrompt.trim().toLowerCase(Locale.ROOT);
    }
}
