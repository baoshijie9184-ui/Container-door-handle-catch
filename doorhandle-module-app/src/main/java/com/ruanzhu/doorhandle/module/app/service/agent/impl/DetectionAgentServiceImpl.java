package com.ruanzhu.doorhandle.module.app.service.agent.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.AgentExecutionResult;
import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionCaptureInfo;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionDispositionRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskProgressResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadFileRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.app.service.ChatSessionService;
import com.ruanzhu.doorhandle.module.app.service.DeepSeekClient;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskDispatchService;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskService;
import com.ruanzhu.doorhandle.module.app.service.DetectionUploadAsyncService;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import com.ruanzhu.doorhandle.module.app.service.agent.DetectionAgentService;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.function.Consumer;
import java.util.stream.Stream;

@Slf4j
@Service
@RequiredArgsConstructor
public class DetectionAgentServiceImpl implements DetectionAgentService {

    private final DetectionTaskMapper detectionTaskMapper;
    private final DeepSeekClient deepSeekClient;
    private final DetectionTaskService detectionTaskService;
    private final ChatSessionService chatSessionService;
    private final OssStorageService ossStorageService;
    private final DetectionUploadAsyncService uploadAsyncService;
    private final DetectionTaskDispatchService detectionTaskDispatchService;
    private final DetectionTaskAccessPolicy detectionTaskAccessPolicy;
    private final ObjectMapper objectMapper;
    private final ChatAssistantProperties chatAssistantProperties;

    /** 匹配 workflowUuid 的正则 (UUID 格式) */
    private static final Pattern UUID_PATTERN =
            Pattern.compile("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}");

    /** 匹配 taskId 的正则 (det_yyyyMMdd_HHmmss_XXXXXXXX) */
    private static final Pattern TASK_ID_PATTERN =
            Pattern.compile("det_\\d{8}_\\d{6}_[a-f0-9]{8}");

    /** 匹配 Windows 路径的正则 */
    private static final Pattern WIN_PATH_PATTERN =
            Pattern.compile("[A-Za-z]:[\\\\/][\\w\\u4e00-\\u9fff\\-\\\\/]+");

    /** 图片文件扩展名 */
    private static final java.util.Set<String> IMAGE_EXTENSIONS =
            java.util.Set.of(".jpg", ".jpeg", ".png", ".bmp");

    @Override
    public String previewAction(String userPrompt) {
        QualityDispositionAction qualityAction = detectQualityDispositionAction(userPrompt);
        if (qualityAction != null) {
            return "确认后将把工单「" + qualityAction.targetNo() + "」关联的质检任务标记为「"
                    + qualityAction.displayName() + "」。我会先按工单查询系统数据，再提交质检处置。";
        }
        String folderPath = extractFolderPath(userPrompt);
        if (folderPath != null) {
            return "检测到本地文件夹路径：「" + folderPath + "」。确认后将自动扫描该文件夹中的图片文件，创建检测任务并上传到 OSS 进行检测。";
        }
        String taskId = extractTaskId(userPrompt);
        if (taskId != null) {
            return "确认后将启动检测任务「" + taskId + "」的检测流程。";
        }
        String uuid = extractUuid(userPrompt);
        if (uuid != null) {
            return "确认后将查找工作流「" + uuid + "」对应的检测任务并启动检测流程。";
        }
        return "确认后将为你查找最近上传的检测任务并启动检测流程。";
    }

    @Override
    public AgentExecutionResult executeConfirmedAction(String userPrompt, TenantContext tenant, String sessionId) {
        return executeConfirmedActionInternal(userPrompt, tenant.username(), tenant, sessionId);
    }

    private AgentExecutionResult executeConfirmedActionInternal(String userPrompt, String username,
                                                                TenantContext tenant, String sessionId) {
        QualityDispositionAction qualityAction = detectQualityDispositionAction(userPrompt);
        if (qualityAction != null) {
            return executeQualityDispositionAction(qualityAction);
        }

        // 1. 尝试识别为文件夹上传
        String folderPath = extractFolderPath(userPrompt);
        if (folderPath == null) {
            try {
                String paramsJson = deepSeekClient.extractUploadParams(userPrompt);
                folderPath = parseFolderPathFromLLM(paramsJson);
            } catch (Exception e) {
                log.warn("LLM 参数提取失败", e);
            }
        }

        // 2. 有文件夹路径 → 走上传流程
        if (folderPath != null && !folderPath.isBlank()) {
            return executeUploadFlow(folderPath, userPrompt, tenant, sessionId);
        }

        // 3. 没有文件夹路径 → 尝试识别为"开始检测"
        return executeStartDetectionFlow(userPrompt, sessionId);
    }

    private AgentExecutionResult executeQualityDispositionAction(QualityDispositionAction action) {
        DetectionTask task = findTaskForQualityAction(action);
        if (task == null) {
            return AgentExecutionResult.builder()
                    .messageType("TEXT")
                    .intent("DETECTION_ACTION")
                    .content("系统中未找到工单「" + action.targetNo() + "」关联的质检任务，未执行任何处置。\n\n来源：系统数据")
                    .build();
        }

        DetectionDispositionRequest request = new DetectionDispositionRequest();
        request.setDispositionAction(action.dispositionAction());
        request.setRecheckRequired("REWORK".equals(action.dispositionAction()) || "RECHECK".equals(action.dispositionAction()));
        request.setDispositionRemark("智能助手确认后提交：" + action.displayName());

        DetectionTaskProgressResponse response = detectionTaskService.disposeTask(task.getTaskId(), request);
        String content = "已将工单「" + defaultText(response.getWorkOrderNo()) + "」关联任务「"
                + response.getTaskId() + "」标记为" + action.displayName() + "。\n\n"
                + "- 当前流转状态：" + defaultText(response.getFlowStatus()) + "\n"
                + "- 处置动作：" + defaultText(response.getDispositionAction()) + "\n"
                + "- 系统消息：" + defaultText(response.getMessage()) + "\n\n"
                + "来源：系统数据";
        return AgentExecutionResult.builder()
                .messageType("TEXT")
                .intent("DETECTION_ACTION")
                .content(content)
                .build();
    }

    private DetectionTask findTaskForQualityAction(QualityDispositionAction action) {
        List<DetectionTask> tasks = selectAccessibleList(new LambdaQueryWrapper<DetectionTask>()
                .eq(DetectionTask::getWorkOrderNo, action.targetNo())
                .orderByDesc(DetectionTask::getUpdatedAt)
                .last("limit 1"));
        return tasks == null || tasks.isEmpty() ? null : tasks.get(0);
    }

    /** 上传流程：扫描文件夹 → 创建任务 → 异步上传 + 自动触发检测 */
    private AgentExecutionResult executeUploadFlow(String folderPath, String userPrompt,
                                                   TenantContext tenant, String sessionId) {
        Path folder;
        try {
            folder = validateAgentScanPath(Path.of(folderPath.trim()));
        } catch (Exception e) {
            return AgentExecutionResult.builder()
                    .messageType("TEXT").intent("DETECTION_ACTION")
                    .content("路径不可访问：「" + folderPath + "」。" + e.getMessage())
                    .build();
        }

        if (!Files.exists(folder)) {
            Path parent = folder.getParent();
            if (parent != null && Files.isDirectory(parent)) {
                String typedName = folder.getFileName().toString();
                Path matched = findBestMatchFolder(parent, typedName, userPrompt);
                if (matched != null) {
                    log.info("DetectionAgent: 路径模糊匹配成功: {} → {}", folderPath, matched);
                    try {
                        folder = validateAgentScanPath(matched);
                    } catch (BusinessException e) {
                        return AgentExecutionResult.builder()
                                .messageType("TEXT").intent("DETECTION_ACTION")
                                .content("匹配到的文件夹不在允许扫描范围内：" + e.getMessage())
                                .build();
                    }
                }
            }
            if (!Files.exists(folder)) {
                return AgentExecutionResult.builder()
                        .messageType("TEXT").intent("DETECTION_ACTION")
                        .content("文件夹路径不存在：「" + folderPath + "」。请检查路径是否正确。")
                        .build();
            }
        }

        if (!Files.isDirectory(folder)) {
            return AgentExecutionResult.builder()
                    .messageType("TEXT").intent("DETECTION_ACTION")
                    .content("提供的路径不是一个文件夹：「" + folderPath + "」。请提供图片文件夹的路径。")
                    .build();
        }

        List<DetectionUploadFileRequest> files = scanImageFiles(folder);
        if (files.isEmpty()) {
            return AgentExecutionResult.builder()
                    .messageType("TEXT").intent("DETECTION_ACTION")
                    .content("文件夹「" + folder.getFileName() + "」中没有找到图片文件（支持 .jpg/.jpeg/.png/.bmp）。请检查文件夹内容。")
                    .build();
        }

        if (!ossStorageService.isConfigured()) {
            return AgentExecutionResult.builder()
                    .messageType("TEXT").intent("DETECTION_ACTION")
                    .content("OSS 存储服务未配置，无法上传图片。请先配置 OSS 后再试。")
                    .build();
        }

        DetectionCaptureInfo captureInfo = parseCaptureInfo(folder.getFileName().toString(), userPrompt);

        CreateDetectionTaskRequest createReq = new CreateDetectionTaskRequest();
        createReq.setFiles(files);
        createReq.setCaptureInfo(captureInfo);
        createReq.setTaskType("BATCH");
        createReq.setSessionId(sessionId);

        CreateDetectionTaskResponse createResp;
        try {
            createResp = detectionTaskService.createTask(createReq);
        } catch (Exception e) {
            log.error("创建检测任务失败", e);
            return AgentExecutionResult.builder()
                    .messageType("TEXT").intent("DETECTION_ACTION")
                    .content("创建检测任务失败：" + e.getMessage())
                    .build();
        }

        log.info("DetectionAgent: 创建任务成功 taskId={}, workflowUuid={}, 文件数={}",
                createResp.getTaskId(), createResp.getWorkflowUuid(), files.size());

        uploadAsyncService.uploadAndConfirm(tenant, createResp, files, folder, sessionId);

        String msg = "已创建检测任务「" + createResp.getTaskId() + "」，共 " + files.size()
                + " 张图片，正在后台上传到 OSS，上传完成后将自动开始检测，请稍候…\n\n"
                + "任务信息：\n"
                + "- 工作流UUID：`" + createResp.getWorkflowUuid() + "`（可用于后续查询）\n"
                + "- 地区：" + captureInfo.getRegion() + "\n"
                + "- 采集员：" + captureInfo.getCollector() + "\n"
                + "- 日期：" + captureInfo.getCaptureDate() + "\n"
                + "- 文件夹：" + captureInfo.getImageFolderName();

        return AgentExecutionResult.builder()
                .messageType("TEXT").intent("DETECTION_ACTION").content(msg).build();
    }

    /** 开始检测流程：根据 taskId/UUID 查找任务 → 触发检测调度 */
    private AgentExecutionResult executeStartDetectionFlow(String userPrompt, String sessionId) {
        // 尝试从消息中提取 taskId 或 UUID
        String taskId = extractTaskId(userPrompt);
        String uuid = extractUuid(userPrompt);

        DetectionTask task = null;

        if (taskId != null) {
            task = selectAccessibleOne(new LambdaQueryWrapper<DetectionTask>()
                    .eq(DetectionTask::getTaskId, taskId));
        } else if (uuid != null) {
            task = selectAccessibleOne(new LambdaQueryWrapper<DetectionTask>()
                    .eq(DetectionTask::getWorkflowUuid, uuid));
        } else {
            // 没有指定具体任务 → 查找最近一个已上传但未检测的任务
            task = selectAccessibleOne(new LambdaQueryWrapper<DetectionTask>()
                    .eq(DetectionTask::getStatus, "UPLOADED")
                    .orderByDesc(DetectionTask::getCreatedAt)
                    .last("limit 1"));
        }

        if (task == null) {
            return AgentExecutionResult.builder()
                    .messageType("TEXT").intent("DETECTION_ACTION")
                    .content("没有找到可检测的任务。请先通过上传文件夹创建检测任务，或指定任务ID（如「检测任务 det_20260526_220605_75247eed」）。")
                    .build();
        }

        // 检查任务状态
        if ("DETECTING".equals(task.getStatus()) || "QUEUED".equals(task.getStatus())) {
            return AgentExecutionResult.builder()
                    .messageType("TEXT").intent("DETECTION_ACTION")
                    .content("任务「" + task.getTaskId() + "」已在检测中，当前阶段：" + task.getStage() + "。")
                    .build();
        }
        if ("COMPLETED".equals(task.getStatus())) {
            return AgentExecutionResult.builder()
                    .messageType("TEXT").intent("DETECTION_ACTION")
                    .content("任务「" + task.getTaskId() + "」已经完成检测，无需重复执行。")
                    .build();
        }

        // 保存 sessionId，确保检测完成后能通知到聊天会话
        if (sessionId != null && !sessionId.equals(task.getSessionId())) {
            task.setSessionId(sessionId);
            detectionTaskMapper.updateById(task);
        }

        // 触发检测
        try {
            detectionTaskDispatchService.dispatchTaskAsync(task.getTaskId());
            log.info("DetectionAgent: 手动触发检测 taskId={}", task.getTaskId());
            return AgentExecutionResult.builder()
                    .messageType("TEXT").intent("DETECTION_ACTION")
                    .content("已为任务「" + task.getTaskId() + "」启动检测流程。\n\n"
                            + "任务信息：\n"
                            + "- 工作流UUID：`" + task.getWorkflowUuid() + "`\n"
                            + "- 图片数量：" + (task.getTotalImages() != null ? task.getTotalImages() : "未知") + "\n"
                            + "- 当前阶段：已提交检测队列\n\n"
                            + "检测完成后我会通知你。")
                    .build();
        } catch (Exception e) {
            log.error("启动检测失败: taskId={}", task.getTaskId(), e);
            return AgentExecutionResult.builder()
                    .messageType("TEXT").intent("DETECTION_ACTION")
                    .content("启动检测失败：" + e.getMessage())
                    .build();
        }
    }

    @Override
    public AgentExecutionResult answer(String userPrompt, String username) {
        return answer(userPrompt, username, null);
    }

    @Override
    public AgentExecutionResult answer(String userPrompt, String username, Consumer<String> tokenConsumer) {
        if (isDefectGalleryQuestion(userPrompt)) {
            DefectGalleryCriteria criteria = extractDefectGalleryCriteria(userPrompt);
            return AgentExecutionResult.builder()
                    .messageType("BUSINESS_CARD")
                    .intent("DETECTION_QUERY")
                    .content(buildDefectGalleryCard(criteria))
                    .build();
        }

        if (isBatchTraceQuestion(userPrompt)) {
            String batchNo = extractBatchNo(userPrompt);
            if (!StringUtils.hasText(batchNo)) {
                return AgentExecutionResult.builder()
                        .messageType("TEXT")
                        .intent("DETECTION_QUERY")
                        .content("可以，我能帮你生成批次追溯报告。请补充批次号，例如「查询批次 2026-06-11_SH_CAM01_A 的追溯」。")
                        .build();
            }
            return AgentExecutionResult.builder()
                    .messageType("BUSINESS_CARD")
                    .intent("DETECTION_QUERY")
                    .content(buildBatchTraceCard(batchNo))
                    .build();
        }

        if (isWorkOrderTraceQuestion(userPrompt)) {
            String workOrderNo = extractWorkOrderNo(userPrompt);
            if (!StringUtils.hasText(workOrderNo)) {
                return AgentExecutionResult.builder()
                        .messageType("TEXT")
                        .intent("DETECTION_QUERY")
                        .content("可以，我能帮你生成工单追溯报告。请补充工单号，例如「查询工单 WO-001 的检测闭环」。")
                        .build();
            }
            return AgentExecutionResult.builder()
                    .messageType("BUSINESS_CARD")
                    .intent("DETECTION_QUERY")
                    .content(buildWorkOrderTraceCard(workOrderNo))
                    .build();
        }

        if (isQualityWorkflowQuestion(userPrompt)) {
            List<DetectionTask> qualityTasks = queryQualityWorkflowTasks();
            return AgentExecutionResult.builder()
                    .messageType("BUSINESS_CARD")
                    .intent("DETECTION_QUERY")
                    .content(buildQualityWorkflowCard(qualityTasks))
                    .build();
        }

        // 1. 尝试按 UUID 查询单条任务
        DetectionTask foundTask = extractUuidAndQuery(userPrompt);

        // 2. 尝试按 taskId 查询
        if (foundTask == null) {
            String taskId = extractTaskId(userPrompt);
            if (taskId != null) {
                foundTask = selectAccessibleOne(new LambdaQueryWrapper<DetectionTask>()
                        .eq(DetectionTask::getTaskId, taskId));
            }
        }

        // 3. 尝试按采集人查询（支持地区和时间过滤）
        if (foundTask == null) {
            String collector = extractCollectorName(userPrompt);
            if (collector != null) {
                List<DetectionTask> tasks = queryByCollector(userPrompt, collector);
                if (!tasks.isEmpty()) {
                    String dataContext = buildMultiTaskDataContext(tasks, collector);
                    String content = buildContentWithLLM(userPrompt, dataContext,
                            () -> generateDetectionContent(userPrompt, dataContext, tokenConsumer),
                            () -> fallbackMultiTaskAnswer(tasks, collector));
                    return AgentExecutionResult.builder().messageType("TEXT").intent("DETECTION_QUERY").content(content).build();
                }
            }
        }

        // 3.5 尝试按设备编号查询
        if (foundTask == null) {
            String deviceName = extractDeviceName(userPrompt);
            if (deviceName != null) {
                List<DetectionTask> tasks = queryByDevice(userPrompt, deviceName);
                if (!tasks.isEmpty()) {
                    String dataContext = buildDeviceMultiTaskDataContext(tasks, deviceName);
                    String content = buildContentWithLLM(userPrompt, dataContext,
                            () -> generateDetectionContent(userPrompt, dataContext, tokenConsumer),
                            () -> fallbackDeviceMultiTaskAnswer(tasks, deviceName));
                    return AgentExecutionResult.builder().messageType("TEXT").intent("DETECTION_QUERY").content(content).build();
                }
            }
        }

        // 4. 回退到最近一条任务
        if (foundTask == null) {
            foundTask = selectAccessibleOne(new LambdaQueryWrapper<DetectionTask>()
                    .orderByDesc(DetectionTask::getCreatedAt)
                    .last("limit 1"));
        }

        final DetectionTask targetTask = foundTask;
        String dataContext = buildTaskDataContext(targetTask);

        String content = buildContentWithLLM(userPrompt, dataContext,
                () -> generateDetectionContent(userPrompt, dataContext, tokenConsumer),
                () -> fallbackDetectionAnswer(targetTask));
        return AgentExecutionResult.builder().messageType("TEXT").intent("DETECTION_QUERY").content(content).build();
    }

    private String generateDetectionContent(String userPrompt, String dataContext, Consumer<String> tokenConsumer) {
        return tokenConsumer == null
                ? deepSeekClient.generateDetectionResponse(userPrompt, dataContext)
                : deepSeekClient.generateDetectionResponseStream(userPrompt, dataContext, tokenConsumer);
    }

    // ---- 设备查询 ----

    /**
     * 从用户输入中提取设备编号。
     * 匹配模式："DEV-0001采集了多少"/"设备DEV-0001的检测记录"/"DEV-0001的图片" 等
     */
    private String extractDeviceName(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        String text = userPrompt.trim();

        // "设备/编号/编码 DEV-XXXX"
        Matcher m1 = Pattern.compile("(?:设备|编号|编码)[：:]?\\s*([A-Za-z]+-\\d+)").matcher(text);
        if (m1.find()) return m1.group(1);

        // "DEV-XXXX采集了/的检测/的图片/的记录"
        Matcher m2 = Pattern.compile("([A-Za-z]+-\\d+)(?:采集了?|的|检测|图片|记录)").matcher(text);
        if (m2.find()) return m2.group(1);

        // 单独出现的设备编号格式 (如 DEV-0001)
        Matcher m3 = Pattern.compile("\\b([A-Za-z]{2,}-\\d{2,})\\b").matcher(text);
        if (m3.find()) return m3.group(1);

        return null;
    }

    /**
     * 按设备编号查询检测任务
     */
    private List<DetectionTask> queryByDevice(String userPrompt, String deviceName) {
        LambdaQueryWrapper<DetectionTask> wrapper = new LambdaQueryWrapper<DetectionTask>()
                .like(DetectionTask::getDeviceName, deviceName)
                .orderByDesc(DetectionTask::getCreatedAt);

        // 时间过滤
        String month = extractMonth(userPrompt);
        if (month != null) {
            wrapper.like(DetectionTask::getCaptureDate, month);
        }

        return selectAccessibleList(wrapper);
    }

    /** 构建设备维度多任务数据上下文 */
    private String buildDeviceMultiTaskDataContext(List<DetectionTask> tasks, String deviceName) {
        StringBuilder sb = new StringBuilder();
        sb.append("设备「").append(deviceName).append("」的检测任务记录（共").append(tasks.size()).append("条）：\n\n");

        int totalImages = 0;
        java.util.Set<String> collectors = new java.util.LinkedHashSet<>();
        java.util.Set<String> regions = new java.util.LinkedHashSet<>();

        for (int i = 0; i < tasks.size(); i++) {
            DetectionTask t = tasks.get(i);
            sb.append("任务").append(i + 1).append("：\n");
            sb.append("  - 任务ID：").append(t.getTaskId()).append("\n");
            sb.append("  - 状态：").append(defaultText(t.getStatus())).append("\n");
            if (StringUtils.hasText(t.getCaptureDate())) sb.append("  - 采集日期：").append(t.getCaptureDate()).append("\n");
            if (StringUtils.hasText(t.getCollector())) {
                sb.append("  - 采集人：").append(t.getCollector()).append("\n");
                collectors.add(t.getCollector());
            }
            if (StringUtils.hasText(t.getRegion())) {
                sb.append("  - 地区：").append(t.getRegion()).append("\n");
                regions.add(t.getRegion());
            }
            if (t.getTotalImages() != null) {
                sb.append("  - 图片数量：").append(t.getTotalImages()).append(" 张\n");
                totalImages += t.getTotalImages();
            }
            sb.append("\n");
        }

        sb.append("汇总统计：\n");
        sb.append("- 总任务数：").append(tasks.size()).append(" 条\n");
        sb.append("- 总图片数：").append(totalImages).append(" 张\n");
        if (!collectors.isEmpty()) {
            sb.append("- 涉及采集人：").append(String.join("、", collectors)).append("\n");
        }
        if (!regions.isEmpty()) {
            sb.append("- 涉及地区：").append(String.join("、", regions)).append("\n");
        }
        return sb.toString();
    }

    /** 设备多任务模板回复 */
    private String fallbackDeviceMultiTaskAnswer(List<DetectionTask> tasks, String deviceName) {
        int totalImages = tasks.stream().mapToInt(t -> t.getTotalImages() != null ? t.getTotalImages() : 0).sum();
        StringBuilder sb = new StringBuilder();
        sb.append("设备「").append(deviceName).append("」共有 ").append(tasks.size())
                .append(" 条检测任务记录，累计 ").append(totalImages).append(" 张图片。");
        if (tasks.size() <= 3) {
            tasks.forEach(t -> sb.append("\n- ").append(t.getTaskId())
                    .append("（").append(defaultText(t.getStatus())).append("，")
                    .append(t.getTotalImages() != null ? t.getTotalImages() : 0).append("张）"));
        }
        return sb.toString();
    }

    // ---- 采集人查询 ----

    /**
     * 从用户输入中提取采集人姓名。
     * 匹配模式："XX采集了多少"/"采集人XX"/"XX上个月"/"XX在北京" 等
     */
    private String extractCollectorName(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        String text = userPrompt.trim();

        // "采集人/采集员：XXX"
        Matcher m1 = Pattern.compile("(?:采集人|采集员)[：:]?\\s*([\\u4e00-\\u9fff]{2,4})").matcher(text);
        if (m1.find()) return m1.group(1);

        // "XXX采集了/采集的/拍了/拍的/拍摄了/上传了"
        Matcher m2 = Pattern.compile("([\\u4e00-\\u9fff]{2,4})(?:采集了?|拍摄?了?|上传了?)").matcher(text);
        if (m2.find()) return m2.group(1);

        // "XXX上个月/上月/本月" 的模式
        Matcher m3 = Pattern.compile("([\\u4e00-\\u9fff]{2,4})(?:上个?月|本月|这个月|最近|今年|去年|\\d{4}年)").matcher(text);
        if (m3.find()) return m3.group(1);

        // "查/找/看XXX的检测/任务/记录"
        Matcher m4 = Pattern.compile("(?:查|找|看|查询|查看)([\\u4e00-\\u9fff]{2,4})(?:的|采集)").matcher(text);
        if (m4.find()) return m4.group(1);

        // "XXX的检测/任务/记录"
        Matcher m5 = Pattern.compile("([\\u4e00-\\u9fff]{2,4})的(?:检测|任务|记录|图片)").matcher(text);
        if (m5.find()) return m5.group(1);

        return null;
    }

    /**
     * 按采集人查询检测任务，支持地区和时间过滤
     */
    private List<DetectionTask> queryByCollector(String userPrompt, String collector) {
        LambdaQueryWrapper<DetectionTask> wrapper = new LambdaQueryWrapper<DetectionTask>()
                .like(DetectionTask::getCollector, collector)
                .orderByDesc(DetectionTask::getCreatedAt);

        // 地区过滤
        String region = extractRegion(userPrompt);
        if (region != null) {
            wrapper.like(DetectionTask::getRegion, region);
        }

        // 时间过滤
        String month = extractMonth(userPrompt);
        if (month != null) {
            wrapper.like(DetectionTask::getCaptureDate, month);
        }

        return selectAccessibleList(wrapper);
    }

    /** 从用户输入中提取地区关键词（必须带市/省/区/县后缀） */
    private String extractRegion(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        // 模式1："在XX" + 地区后缀
        Matcher m1 = Pattern.compile("在([\\u4e00-\\u9fff]{2,4}(?:市|省|区|县))").matcher(userPrompt);
        if (m1.find()) return m1.group(1);
        // 模式2：直接出现带后缀的地区名
        Matcher m2 = Pattern.compile("([\\u4e00-\\u9fff]{2,4}(?:市|省|区|县))").matcher(userPrompt);
        if (m2.find()) return m2.group(1);
        return null;
    }

    /** 从用户输入中提取年月（如 "上个月" → "2026-04", "5月" → "2026-05"） */
    private String extractMonth(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        String text = userPrompt.trim();
        java.time.LocalDate now = java.time.LocalDate.now();

        if (text.contains("上个") || text.contains("上月")) {
            java.time.LocalDate lastMonth = now.minusMonths(1);
            return lastMonth.getYear() + "-" + String.format("%02d", lastMonth.getMonthValue());
        }
        if (text.contains("本月") || text.contains("这个月")) {
            return now.getYear() + "-" + String.format("%02d", now.getMonthValue());
        }

        // "X月" 或 "X月份"
        Matcher m = Pattern.compile("(\\d{1,2})月").matcher(text);
        if (m.find()) {
            int monthNum = Integer.parseInt(m.group(1));
            if (monthNum >= 1 && monthNum <= 12) {
                return now.getYear() + "-" + String.format("%02d", monthNum);
            }
        }

        // "XXXX年X月"
        Matcher m2 = Pattern.compile("(\\d{4})年(\\d{1,2})月").matcher(text);
        if (m2.find()) {
            return m2.group(1) + "-" + String.format("%02d", Integer.parseInt(m2.group(2)));
        }

        return null;
    }

    /** 构建多任务数据上下文（采集人维度汇总） */
    private String buildMultiTaskDataContext(List<DetectionTask> tasks, String collector) {
        StringBuilder sb = new StringBuilder();
        sb.append("采集人「").append(collector) .append("」的检测任务记录（共").append(tasks.size()).append("条）：\n\n");

        int totalImages = 0, totalSuccessful = 0, totalFailed = 0;
        java.util.Set<String> regions = new java.util.LinkedHashSet<>();

        for (int i = 0; i < tasks.size(); i++) {
            DetectionTask t = tasks.get(i);
            sb.append("任务").append(i + 1).append("：\n");
            sb.append("  - 任务ID：").append(t.getTaskId()).append("\n");
            sb.append("  - 状态：").append(defaultText(t.getStatus())).append("\n");
            if (StringUtils.hasText(t.getCaptureDate())) sb.append("  - 采集日期：").append(t.getCaptureDate()).append("\n");
            if (StringUtils.hasText(t.getRegion())) {
                sb.append("  - 地区：").append(t.getRegion()).append("\n");
                regions.add(t.getRegion());
            }
            if (t.getTotalImages() != null) {
                sb.append("  - 图片数量：").append(t.getTotalImages()).append(" 张\n");
                totalImages += t.getTotalImages();
            }
            if (t.getSuccessfulImages() != null) totalSuccessful += t.getSuccessfulImages();
            if (t.getFailedImages() != null) totalFailed += t.getFailedImages();
            sb.append("\n");
        }

        sb.append("汇总统计：\n");
        sb.append("- 总任务数：").append(tasks.size()).append(" 条\n");
        sb.append("- 总图片数：").append(totalImages).append(" 张\n");
        if (totalSuccessful > 0 || totalFailed > 0) {
            sb.append("- 成功：").append(totalSuccessful).append(" 张，失败：").append(totalFailed).append(" 张\n");
        }
        if (!regions.isEmpty()) {
            sb.append("- 涉及地区：").append(String.join("、", regions)).append("\n");
        }
        return sb.toString();
    }

    /** 多任务模板回复 */
    private String fallbackMultiTaskAnswer(List<DetectionTask> tasks, String collector) {
        int totalImages = tasks.stream().mapToInt(t -> t.getTotalImages() != null ? t.getTotalImages() : 0).sum();
        StringBuilder sb = new StringBuilder();
        sb.append("采集人「").append(collector).append("」共有 ").append(tasks.size())
                .append(" 条检测任务记录，累计 ").append(totalImages).append(" 张图片。");
        if (tasks.size() <= 3) {
            tasks.forEach(t -> sb.append("\n- ").append(t.getTaskId())
                    .append("（").append(defaultText(t.getStatus())).append("，")
                    .append(t.getTotalImages() != null ? t.getTotalImages() : 0).append("张）"));
        }
        return sb.toString();
    }

    // ---- 路径提取 ----

    /**
     * 从用户输入中提取 Windows 文件夹路径
     */
    private String extractFolderPath(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        Matcher matcher = WIN_PATH_PATTERN.matcher(userPrompt);
        if (matcher.find()) {
            return matcher.group().replace('\\', '/');
        }
        return null;
    }

    /**
     * 从用户输入中提取 taskId（det_yyyyMMdd_HHmmss_XXXXXXXX）
     */
    private String extractTaskId(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        Matcher matcher = TASK_ID_PATTERN.matcher(userPrompt);
        return matcher.find() ? matcher.group() : null;
    }

    /**
     * 从用户输入中提取 workflowUuid
     */
    private String extractUuid(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        Matcher matcher = UUID_PATTERN.matcher(userPrompt);
        return matcher.find() ? matcher.group() : null;
    }

    /**
     * 从 LLM 返回的 JSON 中提取文件夹路径
     */
    private String parseFolderPathFromLLM(String paramsJson) {
        if (!StringUtils.hasText(paramsJson)) return null;
        try {
            com.fasterxml.jackson.databind.JsonNode node = new ObjectMapper().readTree(paramsJson);
            String path = node.path("folderPath").asText(null);
            if (path != null && !path.isBlank()) {
                return path.replace('\\', '/');
            }
        } catch (JsonProcessingException e) {
            log.debug("LLM 参数 JSON 解析失败: {}", paramsJson);
        }
        return null;
    }

    // ---- 采集信息解析 ----

    /**
     * 从文件夹名解析采集信息。
     * 期望格式: 日期-地区-采集人-批次名
     * 示例: 2026-5-26-上海-王三-批次1图片文件夹
     */
    private DetectionCaptureInfo parseCaptureInfo(String folderName, String userPrompt) {
        DetectionCaptureInfo info = new DetectionCaptureInfo();
        String[] parts = folderName.split("-");
        if (parts.length >= 5) {
            info.setCaptureDate(parts[0] + "-" + parts[1] + "-" + parts[2]);
            info.setRegion(parts[3]);
            info.setCollector(parts[4]);
            info.setImageFolderName(folderName);
        } else {
            info.setCaptureDate(java.time.LocalDate.now().toString());
            info.setRegion("unknown-region");
            info.setCollector("unknown-collector");
            info.setImageFolderName(folderName);
        }

        // 优先从用户提示中提取设备名
        String deviceName = extractDeviceName(userPrompt);
        // 其次从该采集人的历史任务中查找最近使用的设备
        if (deviceName == null && StringUtils.hasText(info.getCollector()) && !"unknown-collector".equals(info.getCollector())) {
            DetectionTask recentTask = selectAccessibleOne(
                    new LambdaQueryWrapper<DetectionTask>()
                            .eq(DetectionTask::getCollector, info.getCollector())
                            .isNotNull(DetectionTask::getDeviceName)
                            .ne(DetectionTask::getDeviceName, "unknown-device")
                            .orderByDesc(DetectionTask::getCreatedAt)
                            .last("LIMIT 1"));
            if (recentTask != null && StringUtils.hasText(recentTask.getDeviceName())) {
                deviceName = recentTask.getDeviceName();
            }
        }
        info.setDeviceName(deviceName != null ? deviceName : "unknown-device");
        return info;
    }

    // ---- 文件扫描 ----

    /**
     * 扫描文件夹中的图片文件（先扫描顶层，没有图片则递归扫描）
     */
    private List<DetectionUploadFileRequest> scanImageFiles(Path folder) {
        List<DetectionUploadFileRequest> topLevel = scanDir(folder, folder);
        if (!topLevel.isEmpty()) {
            return topLevel;
        }
        // 顶层没有图片，递归扫描子目录
        List<DetectionUploadFileRequest> all = new ArrayList<>();
        try (Stream<Path> stream = Files.walk(folder, safeMaxScanDepth())) {
            stream.filter(Files::isRegularFile)
                    .filter(this::isImageFile)
                    .limit(safeMaxScanFiles())
                    .forEach(p -> all.add(toUploadFileRequest(p, folder)));
        } catch (IOException e) {
            log.error("递归扫描文件夹失败: {}", folder, e);
        }
        return all;
    }

    private List<DetectionUploadFileRequest> scanDir(Path dir, Path root) {
        List<DetectionUploadFileRequest> files = new ArrayList<>();
        try (Stream<Path> stream = Files.list(dir)) {
            stream.filter(Files::isRegularFile)
                    .filter(this::isImageFile)
                    .limit(safeMaxScanFiles())
                    .forEach(p -> files.add(toUploadFileRequest(p, root)));
        } catch (IOException e) {
            log.error("扫描文件夹失败: {}", dir, e);
        }
        return files;
    }

    private boolean isImageFile(Path path) {
        String name = path.getFileName().toString().toLowerCase();
        int dot = name.lastIndexOf('.');
        if (dot < 0) return false;
        return IMAGE_EXTENSIONS.contains(name.substring(dot));
    }

    private DetectionUploadFileRequest toUploadFileRequest(Path path, Path root) {
        DetectionUploadFileRequest req = new DetectionUploadFileRequest();
        req.setFileName(path.getFileName().toString());
        req.setContentType(detectContentType(path.getFileName().toString()));
        req.setRelativePath(root.toAbsolutePath().normalize()
                .relativize(path.toAbsolutePath().normalize())
                .toString()
                .replace('\\', '/'));
        try {
            req.setFileSize(Files.size(path));
        } catch (IOException e) {
            log.warn("读取图片文件大小失败: {}", path, e);
        }
        return req;
    }

    private Path validateAgentScanPath(Path rawPath) {
        Path normalized = rawPath.toAbsolutePath().normalize();
        String normalizedText = normalized.toString().toLowerCase(Locale.ROOT);
        for (String keyword : chatAssistantProperties.getBlockedPathKeywords()) {
            if (StringUtils.hasText(keyword) && normalizedText.contains(keyword.toLowerCase(Locale.ROOT))) {
                throw new BusinessException("该路径包含敏感目录关键字，已拒绝扫描");
            }
        }
        boolean allowed = chatAssistantProperties.getAllowedScanRoots().stream()
                .filter(StringUtils::hasText)
                .map(this::resolveConfiguredRoot)
                .anyMatch(root -> isSameOrChild(normalized, root));
        if (!allowed) {
            throw new BusinessException("智能助手只允许扫描配置白名单目录内的图片文件夹");
        }
        return normalized;
    }

    private Path resolveConfiguredRoot(String configuredRoot) {
        String value = configuredRoot.replace("${user.dir}", System.getProperty("user.dir"));
        return Path.of(value).toAbsolutePath().normalize();
    }

    private boolean isSameOrChild(Path child, Path root) {
        String childText = child.toString().toLowerCase(Locale.ROOT);
        String rootText = root.toString().toLowerCase(Locale.ROOT);
        return childText.equals(rootText) || childText.startsWith(rootText + java.io.File.separator);
    }

    private int safeMaxScanDepth() {
        return Math.max(1, chatAssistantProperties.getMaxScanDepth() == null ? 4 : chatAssistantProperties.getMaxScanDepth());
    }

    private long safeMaxScanFiles() {
        return Math.max(1, chatAssistantProperties.getMaxScanFiles() == null ? 200 : chatAssistantProperties.getMaxScanFiles());
    }

    private String detectContentType(String fileName) {
        String lower = fileName.toLowerCase();
        if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
        if (lower.endsWith(".png")) return "image/png";
        if (lower.endsWith(".bmp")) return "image/bmp";
        return "application/octet-stream";
    }

    /**
     * 在父目录中寻找与用户输入最匹配的子文件夹。
     * 策略：前缀包含匹配 → 子串匹配 → LLM 语义匹配
     */
    private Path findBestMatchFolder(Path parent, String typedName, String userPrompt) {
        try (Stream<Path> stream = Files.list(parent)) {
            List<Path> subDirs = stream.filter(Files::isDirectory).toList();
            if (subDirs.isEmpty()) return null;

            // 1. 前缀匹配：typedName 是某个文件夹名的前缀（如 "批次1图片文件夹" 包含 "批次1"）
            List<Path> prefixMatches = new ArrayList<>();
            for (Path dir : subDirs) {
                String dirName = dir.getFileName().toString();
                if (dirName.startsWith(typedName) || typedName.startsWith(dirName)
                        || dirName.contains(typedName) || typedName.contains(dirName)) {
                    prefixMatches.add(dir);
                }
            }
            if (prefixMatches.size() == 1) {
                log.info("DetectionAgent: 前缀匹配到文件夹: {}", prefixMatches.get(0).getFileName());
                return prefixMatches.get(0);
            }
            if (prefixMatches.size() > 1) {
                // 多个匹配，用 LLM 选择
                return llmPickFolder(prefixMatches, typedName, userPrompt);
            }

            // 2. 无前缀匹配时，尝试用 LLM 从所有子目录中选择
            if (subDirs.size() <= 20) {
                return llmPickFolder(subDirs, typedName, userPrompt);
            }
        } catch (IOException e) {
            log.warn("扫描父目录失败: {}", parent, e);
        }
        return null;
    }

    /**
     * 使用 LLM 从候选文件夹中选择最匹配用户意图的
     */
    private Path llmPickFolder(List<Path> candidates, String typedName, String userPrompt) {
        if (candidates.isEmpty()) return null;
        if (candidates.size() == 1) return candidates.get(0);

        StringBuilder ctx = new StringBuilder("候选文件夹：\n");
        for (int i = 0; i < candidates.size(); i++) {
            ctx.append(i + 1).append(". ").append(candidates.get(i).getFileName()).append("\n");
        }
        try {
            String choice = deepSeekClient.pickBestFolder(userPrompt, typedName, ctx.toString());
            if (choice != null) {
                for (Path c : candidates) {
                    if (c.getFileName().toString().equals(choice.trim())) {
                        log.info("DetectionAgent: LLM 选择文件夹: {}", choice);
                        return c;
                    }
                }
                // 尝试数字匹配
                try {
                    int idx = Integer.parseInt(choice.trim()) - 1;
                    if (idx >= 0 && idx < candidates.size()) {
                        return candidates.get(idx);
                    }
                } catch (NumberFormatException ignored) {}
            }
        } catch (Exception e) {
            log.warn("LLM 文件夹选择失败", e);
        }
        return null;
    }


    // ---- UUID 查询 ----

    private DetectionTask extractUuidAndQuery(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        Matcher matcher = UUID_PATTERN.matcher(userPrompt);
        if (matcher.find()) {
            String uuid = matcher.group();
            log.info("DetectionAgent: 从用户输入中提取到 workflowUuid = {}", uuid);
            return selectAccessibleOne(new LambdaQueryWrapper<DetectionTask>()
                    .eq(DetectionTask::getWorkflowUuid, uuid));
        }
        return null;
    }

    private String buildTaskDataContext(DetectionTask task) {
        if (task == null) {
            return "目前系统中没有任何检测任务记录。";
        }
        StringBuilder sb = new StringBuilder();
        sb.append("检测任务详情：\n");
        sb.append("- 工作流UUID：").append(task.getWorkflowUuid()).append(" (可在对话中引用)\n");
        sb.append("- 任务ID：").append(task.getTaskId()).append("\n");
        sb.append("- 状态：").append(defaultText(task.getStatus())).append("\n");
        sb.append("- 阶段：").append(defaultText(task.getStage())).append("\n");
        sb.append("- 业务流转：").append(defaultText(task.getFlowStatus())).append("\n");
        if (StringUtils.hasText(task.getCaptureDate())) {
            sb.append("- 采集日期：").append(task.getCaptureDate()).append("\n");
        }
        if (StringUtils.hasText(task.getRegion())) {
            sb.append("- 地区：").append(task.getRegion()).append("\n");
        }
        if (task.getSuccessfulImages() != null || task.getFailedImages() != null) {
            sb.append("- 成功图片：").append(defaultInt(task.getSuccessfulImages())).append(" 张\n");
            sb.append("- 失败图片：").append(defaultInt(task.getFailedImages())).append(" 张\n");
            sb.append("- 总图片：").append(defaultInt(task.getTotalImages())).append(" 张\n");
        }
        sb.append("- 缺陷数量：").append(defaultInt(task.getDefectCount())).append("\n");
        sb.append("- 主要缺陷：").append(defaultText(task.getPrimaryDefectType())).append("\n");
        sb.append("- 最高严重等级：").append(defaultText(task.getMaxDefectSeverity())).append("\n");
        sb.append("- 复核状态：").append(defaultText(task.getReviewStatus())).append("\n");
        sb.append("- 复核结论：").append(defaultText(task.getReviewConclusion())).append("\n");
        sb.append("- 处置状态：").append(defaultText(task.getDispositionStatus())).append("\n");
        sb.append("- 处置动作：").append(defaultText(task.getDispositionAction())).append("\n");
        sb.append("- 质检站点：").append(defaultText(task.getQualityStation())).append("\n");
        sb.append("- 责任人：").append(defaultText(task.getAssignee())).append("\n");
        sb.append("- 返工结果：").append(defaultText(task.getReworkResult())).append("\n");
        sb.append("- 复检要求：").append(Boolean.TRUE.equals(task.getRecheckRequired()) ? "需要复检" : "无").append("\n");
        if (StringUtils.hasText(task.getErrorMessage())) {
            sb.append("- 失败原因：").append(task.getErrorMessage()).append("\n");
        }
        return sb.toString();
    }

    private String fallbackDetectionAnswer(DetectionTask latestTask) {
        if (latestTask == null) {
            return "目前还没有检测任务记录。你可以告诉我帮你开始一批检测，我会先帮你确认检测动作。";
        }
        StringBuilder builder = new StringBuilder();
        builder.append("我查到了最近一条检测任务：").append(latestTask.getTaskId())
                .append("，WorkflowUUID：").append(latestTask.getWorkflowUuid())
                .append("，当前状态是 ").append(defaultText(latestTask.getStatus()))
                .append("，阶段是 ").append(defaultText(latestTask.getStage())).append("。");
        if (latestTask.getSuccessfulImages() != null || latestTask.getFailedImages() != null) {
            builder.append(" 成功 ").append(defaultInt(latestTask.getSuccessfulImages()))
                    .append(" 张，失败 ").append(defaultInt(latestTask.getFailedImages())).append(" 张。");
        }
        if (StringUtils.hasText(latestTask.getErrorMessage())) {
            builder.append(" 失败原因摘要：").append(latestTask.getErrorMessage()).append("。");
        }
        return builder.toString();
    }

    private String defaultText(String value) {
        return StringUtils.hasText(value) ? value : "未知";
    }

    private String filterText(String value) {
        return StringUtils.hasText(value) ? value : "全部";
    }

    private boolean isQualityWorkflowQuestion(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return false;
        String text = userPrompt.toLowerCase();
        return text.contains("质检")
                || text.contains("复核")
                || text.contains("处置")
                || text.contains("返工")
                || text.contains("复检")
                || text.contains("缺陷证据")
                || text.contains("缺陷确认")
                || text.contains("待处理")
                || text.contains("队列");
    }

    private boolean isDefectGalleryQuestion(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return false;
        String text = userPrompt.toLowerCase();
        return text.contains("缺陷证据")
                || text.contains("证据库")
                || text.contains("缺陷图库")
                || text.contains("缺陷图片")
                || text.contains("defect gallery")
                || (text.contains("缺陷") && (text.contains("严重") || text.contains("高危") || text.contains("critical")))
                || (text.contains("缺陷") && text.contains("设备") && (text.contains("查看") || text.contains("查询")));
    }

    private DefectGalleryCriteria extractDefectGalleryCriteria(String userPrompt) {
        return new DefectGalleryCriteria(
                extractDefectType(userPrompt),
                extractSeverityLevel(userPrompt),
                extractDeviceName(userPrompt),
                extractBatchNo(userPrompt)
        );
    }

    private String extractSeverityLevel(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        String text = userPrompt.toLowerCase();
        if (text.contains("critical") || text.contains("严重") || text.contains("高危") || text.contains("高严重")) {
            return "CRITICAL";
        }
        if (text.contains("major") || text.contains("中等") || text.contains("主要")) {
            return "MAJOR";
        }
        if (text.contains("minor") || text.contains("轻微") || text.contains("低危")) {
            return "MINOR";
        }
        return null;
    }

    private String extractDefectType(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        String text = userPrompt.trim();
        Matcher explicit = Pattern.compile("(?:缺陷类型|缺陷类别|类型)[：:\\s]*([\\u4e00-\\u9fa5A-Za-z0-9_-]{1,20})").matcher(text);
        if (explicit.find()) {
            return explicit.group(1);
        }
        for (String type : List.of("划痕", "锈蚀", "变形", "裂纹", "缺失", "污渍", "毛刺", "破损", "松动", "掉漆")) {
            if (text.contains(type)) {
                return type;
            }
        }
        if (text.toLowerCase().contains("scratch")) return "划痕";
        if (text.toLowerCase().contains("rust")) return "锈蚀";
        if (text.toLowerCase().contains("deform")) return "变形";
        if (text.toLowerCase().contains("crack")) return "裂纹";
        return null;
    }

    private boolean isBatchTraceQuestion(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return false;
        String text = userPrompt.toLowerCase();
        return text.contains("批次")
                && (text.contains("追溯")
                || text.contains("报告")
                || text.contains("查询")
                || text.contains("查看")
                || text.contains("统计")
                || text.contains("闭环")
                || text.contains("缺陷"));
    }

    private String extractBatchNo(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        String text = userPrompt.trim();
        Matcher afterBatch = Pattern.compile("批次(?:号|编号)?[：:\\s]*([A-Za-z0-9_\\-.]+)").matcher(text);
        if (afterBatch.find()) {
            return afterBatch.group(1);
        }
        Matcher quoted = Pattern.compile("[「『“\\\"]([^」』”\\\"]{3,80})[」』”\\\"]").matcher(text);
        if (quoted.find()) {
            String candidate = quoted.group(1).trim();
            if (candidate.matches("[A-Za-z0-9_\\-.]+")) {
                return candidate;
            }
        }
        Matcher token = Pattern.compile("\\b([A-Za-z0-9]+(?:[_\\-.][A-Za-z0-9]+){1,8})\\b").matcher(text);
        while (token.find()) {
            String candidate = token.group(1);
            if (!candidate.startsWith("det_") && !UUID_PATTERN.matcher(candidate).matches()) {
                return candidate;
            }
        }
        return null;
    }

    private boolean isWorkOrderTraceQuestion(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return false;
        String text = userPrompt.toLowerCase();
        return (text.contains("工单") || text.contains("work order") || text.contains("workorder"))
                && (text.contains("追溯")
                || text.contains("报告")
                || text.contains("查询")
                || text.contains("查看")
                || text.contains("统计")
                || text.contains("闭环")
                || text.contains("缺陷"));
    }

    private String extractWorkOrderNo(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) return null;
        String text = userPrompt.trim();
        Matcher afterWorkOrder = Pattern.compile("(?:工单编号|工单号|工单|work\\s*order|workorder)[：:\\s]*([A-Za-z0-9_\\-.]+)",
                Pattern.CASE_INSENSITIVE).matcher(text);
        if (afterWorkOrder.find()) {
            return afterWorkOrder.group(1);
        }
        Matcher token = Pattern.compile("\\b(WO[A-Za-z0-9_\\-.]*|ORDER[A-Za-z0-9_\\-.]*)\\b",
                Pattern.CASE_INSENSITIVE).matcher(text);
        if (token.find()) {
            return token.group(1);
        }
        return null;
    }

    private List<DetectionTask> queryQualityWorkflowTasks() {
        return selectAccessibleList(new LambdaQueryWrapper<DetectionTask>()
                .and(wrapper -> wrapper
                        .in(DetectionTask::getStatus, List.of("COMPLETED", "PARTIAL_FAILED", "FAILED"))
                        .or()
                        .in(DetectionTask::getFlowStatus, List.of("PENDING_REVIEW", "REVIEWING", "CONFIRMED",
                                "REWORK_REQUIRED", "RECHECK_REQUIRED", "HOLD", "FAILED"))
                        .or()
                        .eq(DetectionTask::getReviewStatus, "PENDING")
                        .or()
                        .eq(DetectionTask::getDispositionStatus, "PENDING"))
                .orderByDesc(DetectionTask::getUpdatedAt)
                .last("limit 20"));
    }

    private DetectionTask selectAccessibleOne(LambdaQueryWrapper<DetectionTask> wrapper) {
        applyOwnerFilter(wrapper);
        DetectionTask task = detectionTaskMapper.selectOne(wrapper);
        if (task != null) {
            detectionTaskAccessPolicy.assertCanAccess(task, currentAuthentication());
        }
        return task;
    }

    private List<DetectionTask> selectAccessibleList(LambdaQueryWrapper<DetectionTask> wrapper) {
        applyOwnerFilter(wrapper);
        List<DetectionTask> tasks = detectionTaskMapper.selectList(wrapper);
        if (tasks != null) {
            Authentication authentication = currentAuthentication();
            tasks.forEach(task -> detectionTaskAccessPolicy.assertCanAccess(task, authentication));
        }
        return tasks;
    }

    private void applyOwnerFilter(LambdaQueryWrapper<DetectionTask> wrapper) {
        Authentication authentication = currentAuthentication();
        detectionTaskAccessPolicy.assertAuthenticated(authentication);
    }

    private Authentication currentAuthentication() {
        return SecurityContextHolder.getContext().getAuthentication();
    }

    private String buildQualityWorkflowContext(List<DetectionTask> tasks) {
        if (tasks == null || tasks.isEmpty()) {
            return "当前没有待处理的质检闭环任务。";
        }
        long pendingReview = tasks.stream().filter(t -> "PENDING".equals(t.getReviewStatus())).count();
        long pendingDisposition = tasks.stream()
                .filter(t -> "REVIEWED".equals(t.getReviewStatus())
                        && (!StringUtils.hasText(t.getDispositionStatus()) || "PENDING".equals(t.getDispositionStatus())))
                .count();
        long reworkRequired = tasks.stream().filter(t -> "REWORK_REQUIRED".equals(t.getFlowStatus())).count();
        long recheckRequired = tasks.stream().filter(t -> "RECHECK_REQUIRED".equals(t.getFlowStatus()) || Boolean.TRUE.equals(t.getRecheckRequired())).count();
        long failed = tasks.stream().filter(t -> "FAILED".equals(t.getStatus()) || "FAILED".equals(t.getFlowStatus())).count();

        StringBuilder sb = new StringBuilder();
        sb.append("质检闭环队列摘要：\n");
        sb.append("- 待复核：").append(pendingReview).append("\n");
        sb.append("- 待处置：").append(pendingDisposition).append("\n");
        sb.append("- 待返工：").append(reworkRequired).append("\n");
        sb.append("- 待复检：").append(recheckRequired).append("\n");
        sb.append("- 失败待处理：").append(failed).append("\n\n");
        sb.append("最近任务：\n");
        tasks.stream().limit(10).forEach(t -> sb.append("  - ").append(t.getTaskId())
                .append("，工单：").append(defaultText(t.getWorkOrderNo()))
                .append("，批次：").append(defaultText(t.getBatchNo()))
                .append("，状态：").append(defaultText(t.getStatus()))
                .append("，流转：").append(defaultText(t.getFlowStatus()))
                .append("，复核：").append(defaultText(t.getReviewStatus()))
                .append("，处置：").append(defaultText(t.getDispositionAction()))
                .append("，责任人：").append(defaultText(t.getAssignee()))
                .append("，缺陷：").append(defaultInt(t.getDefectCount()))
                .append("，最高等级：").append(defaultText(t.getMaxDefectSeverity()))
                .append("\n"));
        return sb.toString();
    }

    private String buildBatchTraceCard(String batchNo) {
        Map<String, Object> report = detectionTaskService.getBatchTraceReport(batchNo);
        Map<String, Object> summary = asMap(report.get("summary"));
        Map<String, Object> inspection = asMap(report.get("inspection"));
        Map<String, Object> quality = asMap(report.get("quality"));

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("type", "batch-trace");
        payload.put("title", "批次追溯报告");
        payload.put("description", "已汇总该批次的任务、缺陷、质检闭环、设备模型和时间链路。");
        payload.put("sources", traceSources());
        payload.put("batchNo", report.getOrDefault("batchNo", batchNo));
        payload.put("route", "#/detection?tab=batch-trace&batchNo=" + encodeUrl(String.valueOf(report.getOrDefault("batchNo", batchNo))));
        payload.put("metrics", List.of(
                Map.of("label", "任务数", "value", numberValue(summary.get("taskCount")), "tone", "blue"),
                Map.of("label", "图片总数", "value", numberValue(inspection.get("totalImages")), "tone", "indigo"),
                Map.of("label", "缺陷数", "value", numberValue(inspection.get("defectCount")), "tone", "red"),
                Map.of("label", "确认缺陷", "value", numberValue(inspection.get("confirmedDefectCount")), "tone", "rose"),
                Map.of("label", "缺陷率", "value", percentText(inspection.get("defectRate")), "tone", "orange"),
                Map.of("label", "闭环率", "value", percentText(quality.get("closureRate")), "tone", "amber")
        ));
        payload.put("summary", summary);
        payload.put("inspection", inspection);
        payload.put("quality", quality);
        payload.put("distribution", report.get("distribution"));
        payload.put("timeRange", report.get("timeRange"));
        payload.put("records", report.get("records"));
        payload.put("actions", List.of(
                "分析批次 " + batchNo + " 的主要缺陷",
                "查看批次 " + batchNo + " 的质检闭环",
                "定位批次 " + batchNo + " 的高严重等级任务"
        ));
        payload.put("note", "卡片展示批次核心追溯指标；进入检测页面可查看任务明细、缺陷分布和证据链。");
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new BusinessException("批次追溯卡片序列化失败");
        }
    }

    private String buildWorkOrderTraceCard(String workOrderNo) {
        Map<String, Object> report = detectionTaskService.getWorkOrderTraceReport(workOrderNo);
        Map<String, Object> summary = asMap(report.get("summary"));
        Map<String, Object> inspection = asMap(report.get("inspection"));
        Map<String, Object> quality = asMap(report.get("quality"));

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("type", "work-order-trace");
        payload.put("title", "工单追溯报告");
        payload.put("description", "已汇总该工单覆盖的批次、设备、缺陷检测和质检流转闭环。");
        payload.put("sources", traceSources());
        payload.put("workOrderNo", report.getOrDefault("workOrderNo", workOrderNo));
        payload.put("route", "#/detection?tab=work-order-trace&workOrderNo="
                + encodeUrl(String.valueOf(report.getOrDefault("workOrderNo", workOrderNo))));
        payload.put("metrics", List.of(
                Map.of("label", "任务数", "value", numberValue(summary.get("taskCount")), "tone", "blue"),
                Map.of("label", "图片总数", "value", numberValue(inspection.get("totalImages")), "tone", "indigo"),
                Map.of("label", "缺陷数", "value", numberValue(inspection.get("defectCount")), "tone", "red"),
                Map.of("label", "确认缺陷", "value", numberValue(inspection.get("confirmedDefectCount")), "tone", "rose"),
                Map.of("label", "缺陷率", "value", percentText(inspection.get("defectRate")), "tone", "orange"),
                Map.of("label", "闭环率", "value", percentText(quality.get("closureRate")), "tone", "amber")
        ));
        payload.put("summary", summary);
        payload.put("inspection", inspection);
        payload.put("quality", quality);
        payload.put("distribution", report.get("distribution"));
        payload.put("timeRange", report.get("timeRange"));
        payload.put("records", report.get("records"));
        payload.put("actions", List.of(
                "分析工单 " + workOrderNo + " 的缺陷原因",
                "查看工单 " + workOrderNo + " 的待处理任务",
                "统计工单 " + workOrderNo + " 的批次分布"
        ));
        payload.put("note", "卡片展示工单级闭环指标；进入检测记录可按工单号筛选完整任务列表。");
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new BusinessException("工单追溯卡片序列化失败");
        }
    }

    private String buildQualityWorkflowCard(List<DetectionTask> tasks) {
        List<DetectionTask> safeTasks = tasks == null ? List.of() : tasks;
        long pendingReview = safeTasks.stream().filter(t -> "PENDING".equals(t.getReviewStatus())).count();
        long pendingDisposition = safeTasks.stream()
                .filter(t -> "REVIEWED".equals(t.getReviewStatus())
                        && (!StringUtils.hasText(t.getDispositionStatus()) || "PENDING".equals(t.getDispositionStatus())))
                .count();
        long reworkRequired = safeTasks.stream().filter(t -> "REWORK_REQUIRED".equals(t.getFlowStatus())).count();
        long recheckRequired = safeTasks.stream()
                .filter(t -> "RECHECK_REQUIRED".equals(t.getFlowStatus()) || Boolean.TRUE.equals(t.getRecheckRequired()))
                .count();
        long failed = safeTasks.stream().filter(t -> "FAILED".equals(t.getStatus()) || "FAILED".equals(t.getFlowStatus())).count();
        long severe = safeTasks.stream().filter(t -> isSevere(t.getMaxDefectSeverity())).count();

        List<Map<String, Object>> taskCards = safeTasks.stream().limit(8).map(t -> {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("taskId", defaultText(t.getTaskId()));
            item.put("workOrderNo", defaultText(t.getWorkOrderNo()));
            item.put("batchNo", defaultText(t.getBatchNo()));
            item.put("status", defaultText(t.getStatus()));
            item.put("flowStatus", defaultText(t.getFlowStatus()));
            item.put("reviewStatus", defaultText(t.getReviewStatus()));
            item.put("dispositionStatus", defaultText(t.getDispositionStatus()));
            item.put("assignee", defaultText(t.getAssignee()));
            item.put("defectCount", defaultInt(t.getDefectCount()));
            item.put("severity", defaultText(t.getMaxDefectSeverity()));
            item.put("primaryDefectType", defaultText(t.getPrimaryDefectType()));
            item.put("route", "#/detection?taskId=" + defaultText(t.getTaskId()));
            return item;
        }).toList();

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("type", "quality-queue");
        payload.put("title", "质检闭环队列");
        payload.put("description", safeTasks.isEmpty()
                ? "当前没有待处理的质检闭环任务。"
                : "已汇总待复核、处置、返工、复检和失败任务，建议优先处理高严重等级与失败项。");
        payload.put("sources", List.of(source("系统数据", "检测任务、质检复核、处置流转")));
        payload.put("route", "#/detection?tab=quality");
        payload.put("metrics", List.of(
                Map.of("label", "待复核", "value", pendingReview, "tone", "blue"),
                Map.of("label", "待处置", "value", pendingDisposition, "tone", "amber"),
                Map.of("label", "待返工", "value", reworkRequired, "tone", "orange"),
                Map.of("label", "待复检", "value", recheckRequired, "tone", "indigo"),
                Map.of("label", "失败待处理", "value", failed, "tone", "red"),
                Map.of("label", "高严重等级", "value", severe, "tone", "rose")
        ));
        payload.put("tasks", taskCards);
        payload.put("actions", List.of(
                "优先复核高严重等级任务",
                "查看返工复检任务",
                "统计本周质检工作量"
        ));
        payload.put("note", "卡片仅展示最近 8 条关键任务；进入检测页面可查看完整队列和缺陷证据。");
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new BusinessException("质检队列卡片序列化失败");
        }
    }

    private String buildDefectGalleryCard(DefectGalleryCriteria criteria) {
        Map<String, Object> gallery = detectionTaskService.listDefectGallery(
                criteria.defectType(),
                criteria.severityLevel(),
                criteria.deviceName(),
                criteria.batchNo(),
                null,
                1,
                8
        );
        List<Map<String, Object>> records = normalizeRecordMaps(gallery.get("records"));
        long criticalCount = records.stream()
                .filter(record -> "CRITICAL".equalsIgnoreCase(String.valueOf(record.getOrDefault("maxDefectSeverity", ""))))
                .count();
        long pendingReview = records.stream()
                .filter(record -> "PENDING".equalsIgnoreCase(String.valueOf(record.getOrDefault("reviewStatus", ""))))
                .count();
        long evidenceCount = records.stream()
                .mapToLong(record -> {
                    Object evidence = record.get("defectEvidence");
                    return evidence instanceof List<?> list ? list.size() : 0;
                })
                .sum();

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("type", "defect-gallery");
        payload.put("title", "缺陷证据库");
        payload.put("description", "已按缺陷类型、严重等级、设备和批次筛选证据链，便于快速定位复核。");
        payload.put("sources", List.of(
                source("模型结果", "缺陷类型、置信度、严重等级和证据图"),
                source("系统数据", "关联任务、批次、工单和设备")
        ));
        payload.put("route", buildDefectGalleryRoute(criteria));
        payload.put("filters", Map.of(
                "defectType", filterText(criteria.defectType()),
                "severityLevel", filterText(criteria.severityLevel()),
                "deviceName", filterText(criteria.deviceName()),
                "batchNo", filterText(criteria.batchNo())
        ));
        payload.put("metrics", List.of(
                Map.of("label", "证据任务", "value", numberValue(gallery.get("total")), "tone", "blue"),
                Map.of("label", "本页证据", "value", evidenceCount, "tone", "indigo"),
                Map.of("label", "严重任务", "value", criticalCount, "tone", "red"),
                Map.of("label", "待复核", "value", pendingReview, "tone", "amber")
        ));
        payload.put("records", records);
        payload.put("actions", List.of(
                "查看严重缺陷证据",
                "按设备统计缺陷证据",
                "打开待复核缺陷任务"
        ));
        payload.put("note", "卡片展示前 8 条证据任务；进入缺陷证据库可继续按模型、设备、批次和等级过滤。");
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new BusinessException("缺陷证据卡片序列化失败");
        }
    }

    private String buildDefectGalleryRoute(DefectGalleryCriteria criteria) {
        StringBuilder route = new StringBuilder("#/detection?tab=defect-gallery");
        appendRouteParam(route, "defectType", criteria.defectType());
        appendRouteParam(route, "severityLevel", criteria.severityLevel());
        appendRouteParam(route, "deviceName", criteria.deviceName());
        appendRouteParam(route, "batchNo", criteria.batchNo());
        return route.toString();
    }

    private void appendRouteParam(StringBuilder route, String key, String value) {
        if (StringUtils.hasText(value)) {
            route.append('&').append(key).append('=').append(encodeUrl(value));
        }
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> normalizeRecordMaps(Object records) {
        if (!(records instanceof List<?> list)) {
            return List.of();
        }
        return list.stream()
                .map(item -> item instanceof Map<?, ?>
                        ? (Map<String, Object>) item
                        : objectMapper.convertValue(item, new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {}))
                .limit(8)
                .toList();
    }

    private record DefectGalleryCriteria(String defectType, String severityLevel, String deviceName, String batchNo) {
    }

    private record QualityDispositionAction(String targetNo, String dispositionAction, String displayName) {
    }

    private QualityDispositionAction detectQualityDispositionAction(String userPrompt) {
        if (!StringUtils.hasText(userPrompt)) {
            return null;
        }
        String workOrderNo = extractWorkOrderNo(userPrompt);
        if (!StringUtils.hasText(workOrderNo)) {
            return null;
        }
        String text = userPrompt.toLowerCase(Locale.ROOT);
        if (text.contains("返工") || text.contains("rework")) {
            return new QualityDispositionAction(workOrderNo, "REWORK", "返工");
        }
        if (text.contains("放行") || text.contains("release")) {
            return new QualityDispositionAction(workOrderNo, "RELEASE", "放行");
        }
        if (text.contains("复检") || text.contains("recheck")) {
            return new QualityDispositionAction(workOrderNo, "RECHECK", "复检");
        }
        if (text.contains("报废") || text.contains("scrap")) {
            return new QualityDispositionAction(workOrderNo, "SCRAP", "报废");
        }
        if (text.contains("挂起") || text.contains("hold")) {
            return new QualityDispositionAction(workOrderNo, "HOLD", "挂起");
        }
        return null;
    }

    private List<Map<String, String>> traceSources() {
        return List.of(
                source("系统数据", "检测任务、批次、工单、设备和质检流转"),
                source("模型结果", "缺陷数量、缺陷类型、置信度和严重等级")
        );
    }

    private Map<String, String> source(String type, String detail) {
        return Map.of("type", type, "detail", detail);
    }

    private boolean isSevere(String severity) {
        if (!StringUtils.hasText(severity)) {
            return false;
        }
        String text = severity.toUpperCase();
        return text.contains("HIGH") || text.contains("CRITICAL") || text.contains("严重") || text.contains("高");
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> asMap(Object value) {
        return value instanceof Map<?, ?> ? (Map<String, Object>) value : Map.of();
    }

    private long numberValue(Object value) {
        return value instanceof Number number ? number.longValue() : 0L;
    }

    private String percentText(Object value) {
        double ratio = value instanceof Number number ? number.doubleValue() : 0D;
        return String.format(java.util.Locale.ROOT, "%.1f%%", ratio * 100D);
    }

    private String encodeUrl(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    private String fallbackQualityWorkflowAnswer(List<DetectionTask> tasks) {
        return buildQualityWorkflowContext(tasks);
    }

    private int defaultInt(Integer value) {
        return value == null ? 0 : value;
    }

    private String buildContentWithLLM(String userPrompt, String dataContext,
            java.util.function.Supplier<String> llmCaller,
            java.util.function.Supplier<String> fallback) {
        try {
            return llmCaller.get();
        } catch (Exception e) {
            log.warn("DeepSeek 回复生成失败，使用模板回复", e);
            return fallback.get();
        }
    }
}
