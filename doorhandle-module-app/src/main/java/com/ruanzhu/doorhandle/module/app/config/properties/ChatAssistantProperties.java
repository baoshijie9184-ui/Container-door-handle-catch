package com.ruanzhu.doorhandle.module.app.config.properties;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

import java.util.ArrayList;
import java.util.List;

@Data
@Configuration
@ConfigurationProperties(prefix = "chat-assistant")
public class ChatAssistantProperties {

    private Boolean enabled = true;
    private String defaultSessionSuffix = "default";
    private Integer maxHistoryMessages = 30;
    private Integer maxRequestsPerMinute = 30;
    private Integer maxScanDepth = 4;
    private Integer maxScanFiles = 200;
    private String voiceTranscribeUrl = "";
    private Integer voiceConnectTimeoutMs = 1500;
    private Integer voiceReadTimeoutMs = 15000;
    private Long voiceMaxBytes = 10 * 1024 * 1024L;
    private List<String> voiceTranscribeAllowedHosts = new ArrayList<>(List.of("localhost", "127.0.0.1", "::1"));
    private Boolean ragEnabled = true;
    private Boolean ragQueryRewriteEnabled = true;
    private Boolean ragRerankEnabled = true;
    private Integer ragTopK = 4;
    private Integer ragCandidateMultiplier = 3;
    private Integer ragChunkSize = 900;
    private Integer ragMaxContextChars = 2600;
    private Integer ragContextCacheTtlSeconds = 120;
    private Integer ragContextCacheMaxEntries = 128;
    private Boolean chromaEnabled = true;
    private String chromaBaseUrl = "http://localhost:8000";
    private String chromaTenant = "default_tenant";
    private String chromaDatabase = "default_database";
    private String chromaCollection = "door_handle_assistant_knowledge";
    private String chromaToken = "";
    private Integer chromaEmbeddingDimension = 256;
    private Integer chromaConnectTimeoutMs = 1000;
    private Integer chromaReadTimeoutMs = 3000;
    private List<String> ragSources = new ArrayList<>(List.of(
            "classpath:rag/system-user-guide.md",
            "file:docs/system-user-guide.md",
            "file:README.md"
    ));
    private List<String> allowedScanRoots = new ArrayList<>(List.of("${user.dir}/uploads"));
    private List<String> blockedPathKeywords = new ArrayList<>(List.of(
            ".ssh",
            ".gnupg",
            ".aws",
            ".azure",
            ".kube",
            ".docker",
            "appdata",
            "windows",
            "program files",
            "system32",
            "node_modules",
            ".git"
    ));
}
