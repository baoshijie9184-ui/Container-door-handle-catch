package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.DefaultResourceLoader;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RagKnowledgeServiceTest {

    @TempDir
    Path tempDir;

    @Test
    void retrieveContextReturnsRelevantSystemGuideChunks() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setChromaEnabled(false);
        properties.setRagSources(List.of("classpath:rag/system-user-guide.md"));
        properties.setRagTopK(2);
        properties.setRagMaxContextChars(1200);

        DeepSeekClient deepSeekClient = mock(DeepSeekClient.class);
        when(deepSeekClient.rewriteRagQuery(any())).thenAnswer(invocation -> invocation.getArgument(0));
        when(deepSeekClient.rerankRagCandidates(any(), any(), anyInt())).thenReturn(List.of(0, 1));
        RagKnowledgeService service = new RagKnowledgeService(properties, new DefaultResourceLoader(), mock(ChromaRagStoreService.class), deepSeekClient);
        service.loadKnowledgeBase();

        String context = service.retrieveContext("质检队列有哪些状态，应该怎么处理返工复检");

        assertThat(service.chunkCount()).isGreaterThan(0);
        assertThat(context).contains("系统知识库检索结果");
        assertThat(context).contains("质检队列");
        assertThat(context).contains("返工");
    }

    @Test
    void retrieveContextCanExplainBusinessSeedDataImport() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setChromaEnabled(false);
        properties.setRagSources(List.of("classpath:rag/system-user-guide.md"));
        properties.setRagTopK(2);
        properties.setRagMaxContextChars(1600);

        DeepSeekClient deepSeekClient = mock(DeepSeekClient.class);
        when(deepSeekClient.rewriteRagQuery(any())).thenAnswer(invocation -> invocation.getArgument(0));
        when(deepSeekClient.rerankRagCandidates(any(), any(), anyInt())).thenReturn(List.of(0, 1));
        RagKnowledgeService service = new RagKnowledgeService(properties, new DefaultResourceLoader(), mock(ChromaRagStoreService.class), deepSeekClient);
        service.loadKnowledgeBase();

        String context = service.retrieveContext("首次验收没有工单批次质检数据怎么办");

        assertThat(context).contains("业务预置数据");
        assertThat(context).contains("APP_BUSINESS_SEED_ENABLED");
        assertThat(context).contains("mvnw.cmd spring-boot:run");
    }

    @Test
    void retrieveContextReturnsEmptyWhenDisabled() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setRagEnabled(false);
        properties.setChromaEnabled(false);

        RagKnowledgeService service = new RagKnowledgeService(properties, new DefaultResourceLoader(), mock(ChromaRagStoreService.class), mock(DeepSeekClient.class));
        service.loadKnowledgeBase();

        assertThat(service.retrieveContext("模型管理在哪里")).isEmpty();
    }

    @Test
    void retrieveContextUsesQueryRewriteAndRerankWhenAvailable() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setChromaEnabled(false);
        properties.setRagSources(List.of("classpath:rag/assistant-rag-guide.md"));
        properties.setRagTopK(1);
        properties.setRagCandidateMultiplier(4);
        properties.setRagMaxContextChars(1600);

        DeepSeekClient deepSeekClient = mock(DeepSeekClient.class);
        when(deepSeekClient.rewriteRagQuery("助手文档怎么向量化")).thenReturn("智能助手 RAG Chroma 向量文档 查询重写 rerank");
        when(deepSeekClient.rerankRagCandidates(any(), any(), anyInt())).thenReturn(List.of(0));

        RagKnowledgeService service = new RagKnowledgeService(properties, new DefaultResourceLoader(), mock(ChromaRagStoreService.class), deepSeekClient);
        service.loadKnowledgeBase();

        String context = service.retrieveContext("助手文档怎么向量化");

        assertThat(context).contains("检索重写：智能助手 RAG Chroma 向量文档 查询重写 rerank");
        assertThat(context).contains("Rerank");
        assertThat(context).contains("向量文档");
    }

    @Test
    void rerankKeepsOriginalCandidatesWhenLlmReturnsTooFewIndices() throws Exception {
        Path guide = tempDir.resolve("guide.md");
        Files.writeString(guide, """
                # 平台入口
                平台可以进入检测工作台、质检队列和模型管理，用于工业缺陷检测业务。

                # 质检队列
                平台质检队列支持待复核、已确认、返工和复检状态处理。

                # 模型管理
                平台模型管理支持模型上传、校验、发布、默认模型和回滚。

                # 设备管理
                平台设备管理支持在线状态、采集告警和设备绑定。
                """);

        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setChromaEnabled(false);
        properties.setRagSources(List.of(guide.toUri().toString()));
        properties.setRagTopK(3);
        properties.setRagCandidateMultiplier(2);
        properties.setRagMaxContextChars(2000);

        DeepSeekClient deepSeekClient = mock(DeepSeekClient.class);
        when(deepSeekClient.rewriteRagQuery(any())).thenAnswer(invocation -> invocation.getArgument(0));
        when(deepSeekClient.rerankRagCandidates(any(), any(), anyInt())).thenReturn(List.of(1));

        RagKnowledgeService service = new RagKnowledgeService(properties, new DefaultResourceLoader(), mock(ChromaRagStoreService.class), deepSeekClient);
        service.loadKnowledgeBase();

        String context = service.retrieveContext("平台检测质检模型设备管理入口");

        assertThat(context.split("- 来源：", -1).length - 1).isEqualTo(3);
        assertThat(context).contains("质检队列");
        assertThat(context).contains("模型管理");
    }

    @Test
    void retrieveContextCachesRepeatedQueriesToAvoidDuplicateLlmAuxiliaryCalls() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setChromaEnabled(false);
        properties.setRagSources(List.of("classpath:rag/system-user-guide.md"));
        properties.setRagTopK(2);
        properties.setRagContextCacheTtlSeconds(60);

        DeepSeekClient deepSeekClient = mock(DeepSeekClient.class);
        when(deepSeekClient.rewriteRagQuery(any())).thenAnswer(invocation -> invocation.getArgument(0));
        when(deepSeekClient.rerankRagCandidates(any(), any(), anyInt())).thenReturn(List.of(0, 1));

        RagKnowledgeService service = new RagKnowledgeService(properties, new DefaultResourceLoader(), mock(ChromaRagStoreService.class), deepSeekClient);
        service.loadKnowledgeBase();

        String first = service.retrieveContext("质检队列返工怎么处理");
        String second = service.retrieveContext("质检队列返工怎么处理");

        assertThat(second).isEqualTo(first);
        verify(deepSeekClient, times(1)).rewriteRagQuery("质检队列返工怎么处理");
        verify(deepSeekClient, times(1)).rerankRagCandidates(any(), any(), anyInt());
    }
}
