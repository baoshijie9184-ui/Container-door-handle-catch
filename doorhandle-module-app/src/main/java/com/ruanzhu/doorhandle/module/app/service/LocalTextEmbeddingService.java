package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.nio.charset.StandardCharsets;
import java.util.Locale;

@Service
@RequiredArgsConstructor
public class LocalTextEmbeddingService {

    private final ChatAssistantProperties properties;

    public float[] embed(String text) {
        int dimension = Math.max(32, properties.getChromaEmbeddingDimension() == null
                ? 256
                : properties.getChromaEmbeddingDimension());
        float[] vector = new float[dimension];
        if (!StringUtils.hasText(text)) {
            return vector;
        }

        String normalized = text.toLowerCase(Locale.ROOT);
        addCharacterNgrams(vector, normalized, 2, 1.0f);
        addCharacterNgrams(vector, normalized, 3, 1.35f);
        addTokenFeatures(vector, normalized, 1.75f);
        normalize(vector);
        return vector;
    }

    private void addCharacterNgrams(float[] vector, String text, int size, float weight) {
        if (text.length() < size) {
            return;
        }
        for (int i = 0; i <= text.length() - size; i++) {
            String gram = text.substring(i, i + size);
            if (gram.isBlank()) {
                continue;
            }
            vector[indexFor(gram, vector.length)] += weight;
        }
    }

    private void addTokenFeatures(float[] vector, String text, float weight) {
        for (String token : text.split("[^\\p{IsAlphabetic}\\p{IsDigit}\\u4e00-\\u9fff_-]+")) {
            if (token.length() < 2) {
                continue;
            }
            vector[indexFor(token, vector.length)] += weight;
        }
    }

    private int indexFor(String value, int dimension) {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        int hash = 0x811c9dc5;
        for (byte b : bytes) {
            hash ^= b & 0xff;
            hash *= 0x01000193;
        }
        return Math.floorMod(hash, dimension);
    }

    private void normalize(float[] vector) {
        double sum = 0D;
        for (float value : vector) {
            sum += value * value;
        }
        if (sum <= 0D) {
            return;
        }
        float norm = (float) Math.sqrt(sum);
        for (int i = 0; i < vector.length; i++) {
            vector[i] = vector[i] / norm;
        }
    }
}
