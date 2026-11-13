package com.ruanzhu.doorhandle.framework.semantic;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/** Transport and vector-space settings only; access policy belongs to each content owner. */
@Getter @Setter @Component
@ConfigurationProperties(prefix="app.semantic")
public class SemanticProperties {
    private boolean enabled = true;
    private String qdrantHost = "qdrant";
    private int qdrantGrpcPort = 6334;
    private boolean qdrantTls;
    private String qdrantApiKeyFile = "";
    private int timeoutSeconds = 10;
    private int embeddingTimeoutSeconds = 20;
    private String ragCollection = "doorhandle_rag_bge_m3_v1";
    private String knowledgeCollection = "doorhandle_knowledge_bge_m3_v1";
    private String experienceCollection = "doorhandle_experience_bge_m3_v1";
    private String profile = "siliconflow-bge-m3-v1";
    private String model = "BAAI/bge-m3";
    private int dimensions = 1024;
    private String preprocessing = "utf8-newline-space-v1";
    private String storageGeneration = "qdrant-bge-m3-v1";
}
