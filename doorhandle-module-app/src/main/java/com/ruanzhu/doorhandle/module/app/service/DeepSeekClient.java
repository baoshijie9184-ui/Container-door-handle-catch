package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.app.config.properties.DeepSeekProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.AgentRouteDecision;
import com.ruanzhu.doorhandle.module.app.dto.chat.MultiTurnIntentResult;
import com.ruanzhu.doorhandle.module.system.security.SensitiveDataSanitizer;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.*;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.function.Consumer;

@Slf4j
@Service
@RequiredArgsConstructor
public class DeepSeekClient {

    private final DeepSeekProperties properties;
    private final ObjectMapper objectMapper;
    private final SensitiveDataSanitizer sensitiveDataSanitizer;

    private static final String ANSWER_GROUNDING_RULES =
            "\n\n【强制真实性规则】\n"
            + "1. 只能依据用户问题、当前系统数据、RAG 知识库片段和对话上下文回答。\n"
            + "2. 不得编造不存在的页面入口、按钮名称、模型版本、任务编号、工单号、批次号、统计数值、设备状态或人员信息。\n"
            + "3. 如果上下文没有足够依据，请明确回答“我没有在当前系统数据或知识库中找到足够依据”，然后给出下一步可查询的模块或需要用户补充的信息。\n"
            + "4. 当实时数据与知识库说明冲突时，以实时系统数据为准，并说明知识库可能不是最新状态。\n"
            + "5. 不要把推测说成事实；推测必须标注为“可能”。";

    // Route system prompt
    private static final String ROUTE_SYSTEM_PROMPT =
            "你是一个多Agent智能助手路由系统。根据用户的输入内容，判断用户意图并路由到对应的专业Agent。\n\n"
            + "可用Agent及其职责：\n"
            + "- DETECTION：处理检测任务和质检闭环（图片检测、检测结果、任务进度、漏检、结果图、质检队列、人工复核、缺陷确认、处置、返工、复检、工单、批次、缺陷证据）\n"
            + "- RESOURCE：处理资源和模型管理（设备列表、设备在线/采集告警、人员管理、员工信息、设备绑定、模型信息、模型评估指标、发布、默认模型、灰度、A/B、回滚）\n"
            + "- REPORT：处理报表统计相关（日报、周报、检测统计、质量处置统计、质检工作量、趋势分析、汇总、摘要）\n"
            + "- OPS：处理系统运维和业务导航相关（OSS连接状态、Kafka运行、Worker健康检查、服务器状态、系统状态、功能入口、页面位置、业务地图、下一步建议）\n\n"
            + "intent 判断规则：\n"
            + "- 查询/查看/了解类意图 -> QUERY\n"
            + "- 身份和能力问题（你是谁、你是什么模型、大语言模型、LLM）必须路由到 OPS QUERY，不得当作设备或业务模型管理查询。\n"
            + "- 创建/修改/删除/执行/开始/发起/新增类意图 -> ACTION\n\n"
            + "特殊规则：用户问某功能在哪、入口、页面、菜单、导航、下一步时，targetAgent 必须为 OPS，intent 为 QUERY。\n\n"
            + "请严格按JSON格式返回，不返回其他任何内容：\n"
            + "{\"targetAgent\":\"DETECTION|RESOURCE|REPORT|OPS\",\"intent\":\"QUERY|ACTION\"}";

    // Agent system prompts
    private static final String DETECTION_AGENT_PROMPT =
            "你是[检测任务与质检闭环]领域的智能助手，帮助用户查询和管理集装箱门把手检测任务、质检复核、缺陷确认、处置、返工、复检、工单批次与证据链。\n"
            + "你的回应应该：友好、专业、使用中文，基于提供的数据如实回答。如果数据不足以回答问题，请诚实地说明。"
            + ANSWER_GROUNDING_RULES;

    private static final String RESOURCE_AGENT_PROMPT =
            "你是[资源与模型管理]领域的智能助手，帮助用户管理设备、人员、设备绑定、采集告警、模型版本、评估指标、发布、默认模型、灰度、A/B 和回滚。\n"
            + "你的回应应该：友好、专业、使用中文，基于提供的数据如实回答。如果数据不足以回答问题，请诚实地说明。"
            + ANSWER_GROUNDING_RULES;

    private static final String REPORT_AGENT_PROMPT =
            "你是[数据报表]领域的智能助手，帮助用户生成和解读检测统计、质量处置、质检工作量、设备/人员/模型表现、日报周报和趋势分析。\n"
            + "你的回应应该：友好、专业、使用中文，基于提供的数据如实回答。如果数据不足以回答问题，请诚实地说明。"
            + ANSWER_GROUNDING_RULES;

    private static final String OPS_AGENT_PROMPT =
            "你是[系统运维]领域的智能助手，帮助用户检查和了解系统运行状态。对于‘你是什么模型/大语言模型/你是谁’等身份问题，直接说明当前配置的 Agent 大语言模型，不要返回设备数据。\n"
            + "你的回应应该：友好、专业、使用中文，基于提供的数据如实回答。如果数据不足以回答问题，请诚实地说明。"
            + ANSWER_GROUNDING_RULES;

    // 上传参数提取 prompt
    private static final String UPLOAD_PARAMS_PROMPT =
            "从用户的自然语言输入中提取图片上传相关参数。\n\n"
            + "需要提取的字段：\n"
            + "- folderPath: 本地图片文件夹的完整路径（Windows路径）\n"
            + "- captureDate: 采集日期（如从文件夹名中提取，格式 YYYY-MM-DD）\n"
            + "- region: 地区（如 上海、北京）\n"
            + "- collector: 采集员姓名\n"
            + "- batchName: 批次名称\n\n"
            + "如果某些字段无法从输入中提取，设置为 null。\n"
            + "请严格按JSON格式返回，不返回其他任何内容：\n"
            + "{\"folderPath\":\"...\",\"captureDate\":\"...\",\"region\":\"...\",\"collector\":\"...\",\"batchName\":\"...\"}";

    // 文件夹选择 prompt
    private static final String FOLDER_PICK_PROMPT =
            "用户想打开一个文件夹，但输入的文件夹名不完全匹配。请从候选文件夹列表中选择最匹配用户意图的一个。\n\n"
            + "只返回选中文件夹的名称（或序号），不要返回其他内容。如果没有合适的匹配，返回 \"none\"。";

    /**
     * 调用 DeepSeek 进行意图路由识别
     */
    public AgentRouteDecision routeIntent(String userPrompt) {
        String response = chat(ROUTE_SYSTEM_PROMPT, userPrompt, properties.getTemperature(), properties.getMaxTokens());
        return parseRouteDecision(response, userPrompt);
    }

    /**
     * 调用 DeepSeek 为检测 Agent 生成回复
     */
    public String generateDetectionResponse(String userPrompt, String dataContext) {
        String userMsg = buildGroundedUserMessage(userPrompt, "当前检测与质检系统数据", dataContext);
        return chat(DETECTION_AGENT_PROMPT, userMsg, properties.getChatTemperature(), properties.getMaxTokens());
    }

    /**
     * 调用 DeepSeek 为资源 Agent 生成回复
     */
    public String generateResourceResponse(String userPrompt, String dataContext) {
        String userMsg = buildGroundedUserMessage(userPrompt, "当前资源与模型系统数据", dataContext);
        return chat(RESOURCE_AGENT_PROMPT, userMsg, properties.getChatTemperature(), properties.getMaxTokens());
    }

    /**
     * 调用 DeepSeek 为报表 Agent 生成回复
     */
    public String generateReportResponse(String userPrompt, String dataContext) {
        String userMsg = buildGroundedUserMessage(userPrompt, "当前报表统计系统数据", dataContext);
        return chat(REPORT_AGENT_PROMPT, userMsg, properties.getChatTemperature(), properties.getMaxTokens());
    }

    /**
     * 调用 DeepSeek 为运维 Agent 生成回复
     */
    public String generateOpsResponse(String userPrompt, String dataContext) {
        String userMsg = buildGroundedUserMessage(userPrompt, "当前系统健康与导航数据", dataContext);
        return chat(OPS_AGENT_PROMPT, userMsg, properties.getChatTemperature(), properties.getMaxTokens());
    }

    public String generateDetectionResponseStream(String userPrompt, String dataContext, Consumer<String> tokenConsumer) {
        String userMsg = buildGroundedUserMessage(userPrompt, "当前检测与质检系统数据", dataContext);
        return chatStream(DETECTION_AGENT_PROMPT, userMsg, properties.getChatTemperature(), properties.getMaxTokens(), tokenConsumer);
    }

    public String generateResourceResponseStream(String userPrompt, String dataContext, Consumer<String> tokenConsumer) {
        String userMsg = buildGroundedUserMessage(userPrompt, "当前资源与模型系统数据", dataContext);
        return chatStream(RESOURCE_AGENT_PROMPT, userMsg, properties.getChatTemperature(), properties.getMaxTokens(), tokenConsumer);
    }

    public String generateReportResponseStream(String userPrompt, String dataContext, Consumer<String> tokenConsumer) {
        String userMsg = buildGroundedUserMessage(userPrompt, "当前报表统计系统数据", dataContext);
        return chatStream(REPORT_AGENT_PROMPT, userMsg, properties.getChatTemperature(), properties.getMaxTokens(), tokenConsumer);
    }

    public String generateOpsResponseStream(String userPrompt, String dataContext, Consumer<String> tokenConsumer) {
        String userMsg = buildGroundedUserMessage(userPrompt, "当前系统健康与导航数据", dataContext);
        return chatStream(OPS_AGENT_PROMPT, userMsg, properties.getChatTemperature(), properties.getMaxTokens(), tokenConsumer);
    }

    /**
     * 从用户自然语言中提取上传参数（文件夹路径、采集信息等）
     */
    public String extractUploadParams(String userPrompt) {
        return chat(UPLOAD_PARAMS_PROMPT, userPrompt, properties.getTemperature(), properties.getMaxTokens());
    }

    /**
     * 从候选文件夹列表中选出与用户意图最匹配的文件夹
     */
    public String pickBestFolder(String userPrompt, String typedName, String candidateContext) {
        String userMsg = "用户想要打开的文件夹名: " + typedName
                + "\n用户原始输入: " + userPrompt + "\n\n" + candidateContext;
        String response = chat(FOLDER_PICK_PROMPT, userMsg, properties.getTemperature(), properties.getMaxTokens());
        if (response == null) return null;
        String trimmed = response.trim();
        if ("none".equalsIgnoreCase(trimmed)) return null;
        return trimmed;
    }

    // ---- 多轮意图分类 ----

    private static final String INTENT_CLASSIFY_PROMPT =
            "你是一个多轮对话意图分类器。根据对话上下文和当前用户输入，判断意图类型并提取槽位信息。\n\n"
            + "意图类型（intent）：\n"
            + "- NEW_TASK: 用户发起全新任务（可能信息完整或不完整）\n"
            + "- SUPPLEMENT: 用户在补充上一轮缺失的信息\n"
            + "- MODIFY: 用户要修改之前的参数或条件\n"
            + "- FOLLOWUP: 用户对上一轮结果进行追问或要求进一步操作\n"
            + "- CHITCHAT: 闲聊、问候、感谢等\n\n"
            + "targetAgent 路由规则（严格区分）：\n"
            + "- DETECTION：检测任务和质检闭环（图片检测、检测结果、任务进度、漏检、结果图、上传图片到OSS检测、按采集人/采集员查检测记录、XXX采集了多少图片、按设备编号查检测记录、DEV-0001采集了多少、质检队列、复核、缺陷确认、处置、返工、复检、工单、批次、缺陷证据链）\n"
            + "- RESOURCE：业务资源和模型管理（设备编号列表如DEV-0001、设备在线状态、采集告警、人员/员工信息如员工编号和部门、设备绑定、模型版本信息、模型评估指标、发布/默认模型/灰度/A/B/回滚）\n"
            + "- REPORT：数据统计报表（日报、周报、全局检测统计、质量处置统计、质检工作量、漏检率趋势分析、汇总报告）\n"
            + "- OPS：系统基础设施状态和业务导航（OSS连接、Kafka消息队列、远程Worker进程、服务器运行状态、功能在哪、页面入口、菜单导航、业务地图、下一步建议）\n\n"
            + "关键区分：\n"
            + "- \"张三采集了多少图片\"\"XXX的检测记录\"→DETECTION（按采集人查检测任务）\n"
            + "- \"DEV-0001采集了多少\"\"设备DEV-0001的检测记录\"→DETECTION（按设备编号查检测任务）\n"
            + "- \"今天的检测统计报表\"\"漏检率趋势\"→REPORT（全局统计报表）\n"
            + "- \"质检队列\"\"返工复检\"\"缺陷证据\"→DETECTION（检测质检闭环）\n"
            + "- \"模型评估\"\"模型灰度\"\"模型回滚\"→RESOURCE（模型资源管理）\n"
            + "- \"有哪些设备\"\"设备列表\"\"人员列表\"→RESOURCE（业务资源）\n"
            + "- \"模型管理在哪\"\"质检队列入口\"\"检测报表页面\"→OPS（业务导航地图）\n"
            + "- \"系统状态\"\"Kafka\"\"Worker\"\"OSS\"→OPS（基础设施）\n\n"
            + "isAction 判断：\n"
            + "- true: 上传图片、创建任务、开始检测、修改数据等写操作\n"
            + "- false: 查询、查看、了解等读操作\n\n"
            + "槽位（slotUpdates）: 从用户输入中提取的结构化参数\n"
            + "- folderPath: 用户提供了本地文件夹路径（用于上传新图片）\n"
            + "- taskId: 用户指定了任务ID（用于启动已有任务的检测）\n\n"
            + "请仅输出 JSON：{\"intent\":\"...\",\"slotUpdates\":{...},\"targetAgent\":\"...\",\"isAction\":false}";

    /**
     * 多轮意图分类 — 从对话上下文和用户输入中识别意图并提取槽位。
     *
     * @return JSON: {"intent","slotUpdates","targetAgent","isAction"}
     */
    public String classifyIntent(String contextWithCurrentInput) {
        return chat(INTENT_CLASSIFY_PROMPT, contextWithCurrentInput, properties.getTemperature(), 512);
    }

    /**
     * 解析多轮意图分类结果。
     */
    public MultiTurnIntentResult parseMultiTurnIntent(String llmResponse) {
        if (llmResponse == null || llmResponse.isBlank()) {
            return MultiTurnIntentResult.defaultResult();
        }
        String jsonStr = extractJson(llmResponse);
        try {
            JsonNode node = objectMapper.readTree(jsonStr);
            MultiTurnIntentResult result = new MultiTurnIntentResult();

            String intent = node.path("intent").asText("CHITCHAT").toUpperCase();
            result.setIntent(intent);

            String targetAgent = node.path("targetAgent").asText("OPS").toUpperCase();
            if (!List.of("DETECTION", "RESOURCE", "REPORT", "OPS").contains(targetAgent)) {
                targetAgent = "OPS";
            }
            result.setTargetAgent(targetAgent);

            result.setAction(node.path("isAction").asBoolean(false));

            @SuppressWarnings("unchecked")
            Map<String, Object> slotUpdates = objectMapper.convertValue(
                    node.path("slotUpdates"), Map.class);
            result.setSlotUpdates(slotUpdates != null ? slotUpdates : Collections.emptyMap());

            return result;
        } catch (Exception e) {
            log.warn("多轮意图 JSON 解析失败: {}", llmResponse);
            return MultiTurnIntentResult.defaultResult();
        }
    }

    /**
     * 根据缺失槽位生成自然追问文本。
     */
    public String generateSlotQuestion(String slotContext) {
        return chat(SLOT_QUESTION_PROMPT, slotContext, properties.getChatTemperature(), 256);
    }

    private static final String SLOT_QUESTION_PROMPT =
            "你需要向用户追问缺失的信息。请用一句自然、友好的中文提问，不要重复用户已经提供的信息。\n"
            + "只输出问题文本，不要加前缀或后缀。";

    private static final String RAG_QUERY_REWRITE_PROMPT =
            "你是工业检测系统 RAG 检索查询重写器。请把用户原始问题改写成更适合检索系统知识库的中文查询。\n"
            + "要求：保留用户真实意图；补充同义业务词；不要编造具体工单号、批次号、人员名；只输出一行查询文本。\n"
            + "系统关键词包括：图像采集上传、检测工作台、检测记录、质检队列、缺陷证据库、工单追溯、批次追溯、模型管理、上传模型、设备管理、人员管理、智能助手、RAG、Chroma、查询重写、rerank。";

    private static final String RAG_RERANK_PROMPT =
            "你是 RAG 候选片段重排器。根据用户问题，从候选片段中选出最能直接回答问题的片段。\n"
            + "优先选择包含功能入口、操作流程、状态含义、故障排查步骤的片段。只输出 JSON，不要解释：{\"indices\":[0,1,2]}";

    public String rewriteRagQuery(String userPrompt) {
        if (!isChatAvailable() || !StringUtils.hasText(userPrompt)) {
            return userPrompt;
        }
        try {
            String rewritten = chat(RAG_QUERY_REWRITE_PROMPT, userPrompt, properties.getTemperature(), 256, properties.getRagReadTimeoutMs(), false);
            return StringUtils.hasText(rewritten) ? rewritten.replaceAll("[\\r\\n]+", " ").trim() : userPrompt;
        } catch (Exception e) {
            log.warn("RAG 查询重写失败，使用原始问题: {}", e.getMessage());
            return userPrompt;
        }
    }

    public List<Integer> rerankRagCandidates(String userPrompt, List<String> candidates, int topK) {
        if (!isChatAvailable() || candidates == null || candidates.isEmpty()) {
            return defaultRerankOrder(candidates == null ? 0 : candidates.size(), topK);
        }
        try {
            StringBuilder userMsg = new StringBuilder();
            userMsg.append("用户问题：").append(userPrompt).append("\n\n候选片段：\n");
            for (int i = 0; i < candidates.size(); i++) {
                userMsg.append("[").append(i).append("] ").append(truncate(candidates.get(i), 700)).append("\n");
            }
            userMsg.append("\n最多选择 ").append(topK).append(" 个片段。");
            String response = chat(RAG_RERANK_PROMPT, userMsg.toString(), 0.1D, 256, properties.getRagReadTimeoutMs(), false);
            return parseRerankIndices(response, candidates.size(), topK);
        } catch (Exception e) {
            log.warn("RAG rerank 失败，使用原始检索顺序: {}", e.getMessage());
            return defaultRerankOrder(candidates.size(), topK);
        }
    }

    // Core API call

    private String chat(String systemPrompt, String userPrompt, double temperature, int maxTokens) {
        return chat(systemPrompt, userPrompt, temperature, maxTokens, properties.getReadTimeoutMs(), true);
    }

    private String chat(String systemPrompt,
                        String userPrompt,
                        double temperature,
                        int maxTokens,
                        int readTimeoutMs,
                        boolean logAsError) {
        String url = properties.getBaseUrl() + "/v1/chat/completions";
        RestTemplate restTemplate = buildRestTemplate(readTimeoutMs);

        Map<String, Object> requestBody = new LinkedHashMap<>();
        requestBody.put("model", properties.getModel());
        requestBody.put("messages", List.of(
                Map.of("role", "system", "content", systemPrompt),
                Map.of("role", "user", "content", sensitiveDataSanitizer.sanitize(userPrompt))
        ));
        requestBody.put("temperature", temperature);
        requestBody.put("max_tokens", maxTokens);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(properties.getApiKey());

        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(requestBody, headers);

        try {
            ResponseEntity<String> response = restTemplate.exchange(url, HttpMethod.POST, entity, String.class);
            if (!response.getStatusCode().is2xxSuccessful() || response.getBody() == null) {
                throw new BusinessException("DeepSeek API returned status: " + response.getStatusCode());
            }
            JsonNode root = objectMapper.readTree(response.getBody());
            JsonNode choices = root.path("choices");
            if (choices.isArray() && !choices.isEmpty()) {
                return choices.get(0).path("message").path("content").asText("");
            }
            throw new BusinessException("DeepSeek API response has no choices");
        } catch (RestClientException | JsonProcessingException e) {
            if (logAsError) {
                log.error("DeepSeek API call failed", e);
            } else {
                log.debug("DeepSeek auxiliary API call failed: {}", e.getMessage());
            }
            throw new BusinessException("DeepSeek API call failed: " + e.getMessage());
        }
    }

    private String chatStream(String systemPrompt,
                              String userPrompt,
                              double temperature,
                              int maxTokens,
                              Consumer<String> tokenConsumer) {
        if (!isChatAvailable()) {
            throw new BusinessException("DeepSeek API is not configured");
        }
        String url = properties.getBaseUrl() + "/v1/chat/completions";
        RestTemplate restTemplate = buildRestTemplate();

        Map<String, Object> requestBody = new LinkedHashMap<>();
        requestBody.put("model", properties.getModel());
        requestBody.put("messages", List.of(
                Map.of("role", "system", "content", systemPrompt),
                Map.of("role", "user", "content", sensitiveDataSanitizer.sanitize(userPrompt))
        ));
        requestBody.put("temperature", temperature);
        requestBody.put("max_tokens", maxTokens);
        requestBody.put("stream", true);

        try {
            return restTemplate.execute(url, HttpMethod.POST, request -> {
                request.getHeaders().setContentType(MediaType.APPLICATION_JSON);
                request.getHeaders().setBearerAuth(properties.getApiKey());
                objectMapper.writeValue(request.getBody(), requestBody);
            }, response -> {
                if (!response.getStatusCode().is2xxSuccessful()) {
                    throw new BusinessException("DeepSeek stream API returned status: " + response.getStatusCode());
                }
                StringBuilder content = new StringBuilder();
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(response.getBody(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        String token = parseStreamToken(line);
                        if (token == null) {
                            continue;
                        }
                        content.append(token);
                        if (tokenConsumer != null) {
                            tokenConsumer.accept(token);
                        }
                    }
                }
                return content.toString();
            });
        } catch (RestClientException e) {
            log.error("DeepSeek stream API call failed", e);
            throw new BusinessException("DeepSeek stream API call failed: " + e.getMessage());
        }
    }

    private String parseStreamToken(String line) {
        if (!StringUtils.hasText(line) || !line.startsWith("data:")) {
            return null;
        }
        String data = line.substring(5).trim();
        if ("[DONE]".equals(data)) {
            return null;
        }
        try {
            JsonNode root = objectMapper.readTree(data);
            JsonNode choice = root.path("choices").path(0);
            String delta = choice.path("delta").path("content").asText("");
            if (StringUtils.hasText(delta)) {
                return delta;
            }
            String message = choice.path("message").path("content").asText("");
            return StringUtils.hasText(message) ? message : null;
        } catch (Exception e) {
            log.debug("忽略无法解析的 DeepSeek 流式片段: {}", data);
            return null;
        }
    }

    private RestTemplate buildRestTemplate() {
        return buildRestTemplate(properties.getReadTimeoutMs());
    }

    private RestTemplate buildRestTemplate(int readTimeoutMs) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(properties.getConnectTimeoutMs());
        factory.setReadTimeout(Math.max(100, readTimeoutMs));
        return new RestTemplate(factory);
    }

    private String buildGroundedUserMessage(String userPrompt, String contextTitle, String dataContext) {
        String safeContext = StringUtils.hasText(dataContext) ? dataContext : "当前没有可用系统数据或知识库片段。";
        return "用户问题：\n" + userPrompt
                + "\n\n" + contextTitle + "：\n" + safeContext
                + "\n\n回答要求：\n"
                + "- 先判断上述数据是否足够回答。\n"
                + "- 足够时，基于数据直接回答，不要添加未出现的具体事实。\n"
                + "- 不足时，不要硬猜；请说明缺少哪些依据，并建议用户查看哪个模块或补充哪个字段。\n"
                + "- 如需给操作建议，只能给通用步骤，不要编造已经发生的检测结果或系统状态。";
    }

    private boolean isChatAvailable() {
        return properties.isEnabled() && StringUtils.hasText(properties.getApiKey());
    }

    // Route decision parsing

    private AgentRouteDecision parseRouteDecision(String llmResponse, String userPrompt) {
        String jsonStr = extractJson(llmResponse);
        try {
            JsonNode node = objectMapper.readTree(jsonStr);
            String targetAgent = node.path("targetAgent").asText("OPS").toUpperCase();
            String intent = node.path("intent").asText("QUERY").toUpperCase();

            if (!List.of("DETECTION", "RESOURCE", "REPORT", "OPS").contains(targetAgent)) {
                targetAgent = "OPS";
            }
            if (!List.of("QUERY", "ACTION").contains(intent)) {
                intent = "QUERY";
            }

            AgentRouteDecision decision = new AgentRouteDecision();
            decision.setTargetAgent(targetAgent);
            decision.setIntent(targetAgent + "_" + intent);
            decision.setConfirmationRequired("ACTION".equals(intent));
            decision.setNormalizedUserPrompt(userPrompt.trim().toLowerCase());
            log.info("DeepSeek route decision: agent={} intent={} confirm={}",
                    targetAgent, decision.getIntent(), decision.isConfirmationRequired());
            return decision;
        } catch (JsonProcessingException e) {
            log.warn("DeepSeek JSON parse failed, fallback to OPS: {}", llmResponse);
            AgentRouteDecision decision = new AgentRouteDecision();
            decision.setTargetAgent("OPS");
            decision.setIntent("OPS_QUERY");
            decision.setConfirmationRequired(false);
            decision.setNormalizedUserPrompt(userPrompt.trim().toLowerCase());
            return decision;
        }
    }

    /**
     * Extract JSON from LLM response, handling possible markdown wrapping
     */
    private String extractJson(String text) {
        if (text == null) return "{}";
        String t = text.trim();
        if (t.startsWith("```")) {
            int start = t.indexOf("\n");
            int end = t.lastIndexOf("```");
            if (start > 0 && end > start) {
                t = t.substring(start, end).trim();
            } else if (start > 0) {
                t = t.substring(start).trim();
            }
        }
        int braceStart = t.indexOf('{');
        int braceEnd = t.lastIndexOf('}');
        if (braceStart >= 0 && braceEnd > braceStart) {
            return t.substring(braceStart, braceEnd + 1);
        }
        return t;
    }

    private List<Integer> parseRerankIndices(String llmResponse, int candidateCount, int topK) {
        try {
            JsonNode node = objectMapper.readTree(extractJson(llmResponse));
            JsonNode indicesNode = node.path("indices");
            List<Integer> indices = new ArrayList<>();
            if (indicesNode.isArray()) {
                for (JsonNode item : indicesNode) {
                    int index = item.asInt(-1);
                    if (index >= 0 && index < candidateCount && !indices.contains(index)) {
                        indices.add(index);
                    }
                    if (indices.size() >= topK) {
                        break;
                    }
                }
            }
            if (indices.isEmpty()) {
                return defaultRerankOrder(candidateCount, topK);
            }
            return indices;
        } catch (Exception e) {
            return defaultRerankOrder(candidateCount, topK);
        }
    }

    private List<Integer> defaultRerankOrder(int candidateCount, int topK) {
        List<Integer> indices = new ArrayList<>();
        for (int i = 0; i < Math.min(candidateCount, topK); i++) {
            indices.add(i);
        }
        return indices;
    }

    private String truncate(String text, int maxLength) {
        if (text == null || text.length() <= maxLength) {
            return text;
        }
        return text.substring(0, maxLength) + "...";
    }
}
