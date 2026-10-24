package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import io.agentscope.core.message.UserMessage;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.model.GenerateOptions;
import org.springframework.stereotype.Component;
import java.time.Duration;
import java.util.List;
import java.util.Map;

/** An explicit, single paid attempt. Never retries, falls back, or writes a memory. */
@Component
public class ModelJsonCompatibilityProbe {
    private final ObjectMapper json;

    public ModelJsonCompatibilityProbe(ObjectMapper json) { this.json = json; }

    public boolean check(ModelConfigurationService.Runtime snapshot, String id) {
        var settings = json.convertValue(snapshot.properties(), com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties.class);
        settings.setFallbackEnabled(false);
        settings.setMaxRetries(0);
        settings.setMaxOutputTokens(64);
        settings.setTimeout(Duration.ofSeconds(15));
        settings.setFirstTokenTimeout(Duration.ofSeconds(15));
        var agent = new AgentScopeProperties();
        agent.setModel(id);
        try (var client = new AgentModelService(settings, agent)) {
            var responses = client.resolve(id).stream(
                    List.of(new UserMessage("Return only this JSON object: {\"compatible\":true}")), List.of(),
                    GenerateOptions.builder().stream(false).maxTokens(64)
                            .additionalBodyParam("response_format", Map.of("type", "json_object")).build())
                    .collectList().block(Duration.ofSeconds(20));
            var text = new StringBuilder();
            if (responses == null) return false;
            for (var response : responses) for (var block : response.getContent()) {
                if (block instanceof TextBlock part) text.append(part.getText());
                if (text.length() > 4096) return false;
            }
            var result = json.readTree(text.toString());
            return result != null && result.isObject() && result.size() == 1
                    && result.path("compatible").isBoolean() && result.path("compatible").booleanValue();
        } catch (Exception ignored) {
            // No provider exception or body reaches audit, logs or the HTTP response.
            return false;
        }
    }
}
