package com.ruanzhu.doorhandle.module.ai.eval;

import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;

/** Private opt-in test configuration. Never serialise or copy credentials into reports. */
final class LiveProviderConfig {
    static AgentModelProperties load(Path project,String provider) throws Exception {
        if(!Set.of("deepseek","dashscope").contains(provider))throw new IllegalArgumentException("Explicit supported provider required");
        Map<String,String> values=new HashMap<>();
        Set<String> keys=Set.of("DEEPSEEK_API_KEY","DEEPSEEK_BASE_URL","DEEPSEEK_MODEL","DASHSCOPE_API_KEY","DASHSCOPE_BASE_URL","DASHSCOPE_MODEL","AGENT_MODEL_PROXY_URL");
        for(String line:Files.readAllLines(project.resolve(".env"))) {
            int equals=line.indexOf('=');if(equals<1||!keys.contains(line.substring(0,equals)))continue;
            String value=line.substring(equals+1).trim();if(value.length()>1&&((value.startsWith("\"")&&value.endsWith("\""))||(value.startsWith("'")&&value.endsWith("'"))))value=value.substring(1,value.length()-1);
            values.put(line.substring(0,equals),value);
        }
        var config=new AgentModelProperties();config.setMaxRetries(0);config.setFallbackEnabled(false);config.setMaxOutputTokens(1536);
        config.setTimeout(Duration.ofSeconds(55));config.setFirstTokenTimeout(Duration.ofSeconds(25));config.setProxyUrl(values.getOrDefault("AGENT_MODEL_PROXY_URL",""));
        var connection=provider.equals("deepseek")?config.getDeepseek():config.getDashscope();String prefix=provider.toUpperCase(Locale.ROOT);
        connection.setApiKey(values.get(prefix+"_API_KEY"));connection.setBaseUrl(values.getOrDefault(prefix+"_BASE_URL",connection.getBaseUrl()));
        connection.setModel(values.getOrDefault(prefix+"_MODEL",connection.getModel()));
        if(connection.getApiKey()==null||connection.getApiKey().isBlank())throw new IllegalStateException("Selected provider credential is absent");
        return config;
    }
}
