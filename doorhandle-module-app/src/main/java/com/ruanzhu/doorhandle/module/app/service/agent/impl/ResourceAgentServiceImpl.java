package com.ruanzhu.doorhandle.module.app.service.agent.impl;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ruanzhu.doorhandle.module.app.dto.chat.AgentExecutionResult;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.app.service.DeepSeekClient;
import com.ruanzhu.doorhandle.module.device.service.DeviceService;
import com.ruanzhu.doorhandle.module.device.service.EmployeeService;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import com.ruanzhu.doorhandle.module.app.service.agent.ResourceAgentService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.function.Consumer;

@Slf4j
@Service
@RequiredArgsConstructor
public class ResourceAgentServiceImpl implements ResourceAgentService {

    private final DeviceService deviceService;
    private final EmployeeService employeeService;
    private final ModelService modelService;
    private final DeepSeekClient deepSeekClient;

    @Override
    public String previewAction(String userPrompt) {
        return "这条请求会修改资源数据，属于需要确认的操作。确认后我会帮你继续执行，或者告诉你当前还缺少哪些关键字段。";
    }

    @Override
    public AgentExecutionResult answer(String userPrompt, String username) {
        return answer(userPrompt, username, null);
    }

    @Override
    public AgentExecutionResult answer(String userPrompt, String username, Consumer<String> tokenConsumer) {
        String dataContext = buildResourceDataContext(userPrompt);

        String content;
        try {
            content = tokenConsumer == null
                    ? deepSeekClient.generateResourceResponse(userPrompt, dataContext)
                    : deepSeekClient.generateResourceResponseStream(userPrompt, dataContext, tokenConsumer);
        } catch (Exception e) {
            log.warn("DeepSeek 回复生成失败，使用模板回复: {}", e.getMessage());
            content = fallbackResourceAnswer(userPrompt);
        }
        content = appendSourceIfMissing(content);
        return AgentExecutionResult.builder().messageType("TEXT").intent("RESOURCE_QUERY").content(content).build();
    }

    private String buildResourceDataContext(String userPrompt) {
        String text = userPrompt == null ? "" : userPrompt;
        StringBuilder sb = new StringBuilder();
        if (text.contains("设备")) {
            List<Device> devices = deviceService.getAllDevices();
            sb.append("设备总数：").append(devices.size()).append(" 台\n");
            if (!devices.isEmpty()) {
                sb.append("设备列表：\n");
                devices.forEach(d -> sb.append("  - ").append(d.getDeviceCode())
                        .append("，业务状态：").append(defaultText(d.getStatus()))
                        .append("，在线：").append(defaultText(d.getOnlineStatus()))
                        .append("，工位：").append(defaultText(d.getStationCode()))
                        .append("，边缘节点：").append(defaultText(d.getEdgeNodeId()))
                        .append("，PLC：").append(defaultText(d.getPlcStatus()))
                        .append("，相机：").append(defaultText(d.getCameraStatus()))
                        .append("，采集：").append(defaultText(d.getCaptureStatus()))
                        .append("\n"));
            }
        } else if (text.contains("人员") || text.contains("员工")) {
            // 尝试从用户输入中提取姓名做精确查询
            String nameFilter = extractNameFilter(text);
            Page<Employee> page = employeeService.findByPage(1, 20, nameFilter, null, null, null, null, null);
            sb.append("人员总数：").append(page.getTotal()).append(" 人\n");
            if (!page.getRecords().isEmpty()) {
                sb.append("人员列表：\n");
                page.getRecords().forEach(e -> sb.append("  - 姓名：").append(e.getName())
                        .append("，员工编号：").append(defaultText(e.getEmployeeNumber()))
                        .append("，部门：").append(defaultText(e.getDepartment()))
                        .append("，类型：").append(defaultText(e.getEmployeeType()))
                        .append("，状态：").append(defaultText(e.getStatus())).append("\n"));
            }
        } else {
            List<ModelInfo> models = modelService.getAllModels();
            sb.append("模型总数：").append(models.size()).append(" 个\n");
            if (!models.isEmpty()) {
                sb.append("模型列表：\n");
                models.forEach(m -> sb.append("  - ID：").append(m.getModelId())
                        .append("，").append(defaultText(m.getModelName()))
                        .append(" v").append(defaultText(m.getVersion()))
                        .append("，状态：").append(defaultText(m.getStatus()))
                        .append("，默认：").append(Boolean.TRUE.equals(m.getIsDefault()) ? "是" : "否")
                        .append("，验证：").append(defaultText(m.getValidationStatus()))
                        .append("，MLOps：").append(defaultText(m.getMlopsStatus()))
                        .append("，Precision：").append(defaultText(m.getPrecisionScore()))
                        .append("，Recall：").append(defaultText(m.getRecallScore()))
                        .append("，mAP：").append(defaultText(m.getMapScore()))
                        .append("，F1：").append(defaultText(m.getF1Score()))
                        .append("，平均推理耗时ms：").append(defaultText(m.getAvgInferenceMs()))
                        .append("，部署策略：").append(defaultText(m.getDeploymentStrategy()))
                        .append("，灰度比例：").append(defaultText(m.getCanaryPercent()))
                        .append("，A/B组：").append(defaultText(m.getAbGroup()))
                        .append("，回滚来源：").append(defaultText(m.getRollbackFromModelId()))
                        .append("\n"));
            }
        }
        return sb.toString();
    }

    private String fallbackResourceAnswer(String userPrompt) {
        String text = userPrompt == null ? "" : userPrompt;
        if (text.contains("设备")) {
            List<Device> devices = deviceService.getAllDevices();
            if (devices.isEmpty()) return "当前没有设备记录。";
            return "当前共有 " + devices.size() + " 台设备。最近可见设备包括：" + devices.stream().limit(3)
                    .map(item -> item.getDeviceCode() + "（" + defaultText(item.getStatus())
                            + "，在线：" + defaultText(item.getOnlineStatus())
                            + "，采集：" + defaultText(item.getCaptureStatus()) + "）")
                    .reduce((left, right) -> left + "、" + right).orElse("暂无");
        }
        if (text.contains("人员") || text.contains("员工")) {
            String nameFilter = extractNameFilter(text);
            Page<Employee> page = employeeService.findByPage(1, 10, nameFilter, null, null, null, null, null);
            if (page.getRecords().isEmpty()) return "当前没有人员记录。";
            return "当前可见人员共 " + page.getTotal() + " 人。最近记录包括：" + page.getRecords().stream().limit(5)
                    .map(item -> item.getName() + "（编号" + defaultText(item.getEmployeeNumber()) + "，" + item.getDepartment() + "）")
                    .reduce((left, right) -> left + "、" + right).orElse("暂无");
        }
        List<ModelInfo> models = modelService.getAllModels();
        if (models.isEmpty()) return "当前没有模型记录。";
        return "当前共有 " + models.size() + " 个模型版本。最近可见模型包括：" + models.stream().limit(3)
                .map(item -> defaultText(item.getModelName()) + " v" + defaultText(item.getVersion())
                        + "（状态：" + defaultText(item.getStatus())
                        + "，验证：" + defaultText(item.getValidationStatus())
                        + "，部署：" + defaultText(item.getDeploymentStrategy()) + "）")
                .reduce((left, right) -> left + "、" + right).orElse("暂无");
    }

    /** 从用户输入中提取可能的员工姓名（2-4个中文字符） */
    private String extractNameFilter(String text) {
        if (text == null) return null;
        java.util.regex.Matcher m = java.util.regex.Pattern
                .compile(".*(?:查|找|搜索|查询|有哪些|列出).*?([\\u4e00-\\u9fff]{2,4})(?:的|是|在|员工|人员|信息|$).*")
                .matcher(text);
        if (m.matches()) return m.group(1);
        return null;
    }

    private String defaultText(String value) {
        return (value != null && !value.isBlank()) ? value : "未知";
    }

    private String defaultText(Object value) {
        return value == null ? "未知" : String.valueOf(value);
    }

    private String appendSourceIfMissing(String content) {
        if (content == null || content.contains("来源：")) {
            return content;
        }
        return content + "\n\n来源：系统数据";
    }

    @Override
    public AgentExecutionResult executeConfirmedAction(String userPrompt, String username) {
        String content;
        try {
            content = deepSeekClient.generateResourceResponse(userPrompt, "用户确认了一个资源修改操作。当前版本暂不在聊天中直接执行复杂表单写操作。");
        } catch (Exception e) {
            log.warn("DeepSeek 回复生成失败: {}", e.getMessage());
            content = "我已经收到资源修改类操作的确认。当前第一版先不在聊天里直接落库执行复杂表单写操作，我建议你告诉我更具体的目标字段，我会先帮你整理成可执行变更说明，或者你也可以去对应管理页完成最终提交。";
        }
        return AgentExecutionResult.builder().messageType("TEXT").intent("RESOURCE_ACTION").content(content).build();
    }
}
