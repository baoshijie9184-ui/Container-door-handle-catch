package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class LocalTextEmbeddingServiceTest {

    @Test
    void embedReturnsDeterministicNormalizedVector() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setChromaEmbeddingDimension(64);
        LocalTextEmbeddingService service = new LocalTextEmbeddingService(properties);

        float[] first = service.embed("质检队列返工复检");
        float[] second = service.embed("质检队列返工复检");

        assertThat(first).hasSize(64);
        assertThat(first).containsExactly(second);
        assertThat(l2Norm(first)).isBetween(0.99D, 1.01D);
    }

    private double l2Norm(float[] vector) {
        double sum = 0D;
        for (float value : vector) {
            sum += value * value;
        }
        return Math.sqrt(sum);
    }
}
