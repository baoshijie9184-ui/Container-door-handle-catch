package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.DetectionModelSelectionApi;
import com.ruanzhu.doorhandle.module.detection.dto.detection.ModelMaintenance;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

@Service
public class SingleImagePreviewService {
    private static final int MAX_IMAGE_BYTES = 10 * 1024 * 1024;

    private final ObjectMapper json;
    private final DetectionModelSelectionApi models;
    private final HttpClient worker = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(4)).build();
    private final String url;
    private final String token;
    private final int primaryModelId;

    public SingleImagePreviewService(ObjectMapper json, DetectionModelSelectionApi models,
                                     @Value("${detection.preview.url:}") String url,
                                     @Value("${detection.preview.token:}") String token,
                                     @Value("${DETECTION_PRIMARY_MODEL_ID:0}") int primaryModelId) {
        this.json = json;
        this.models = models;
        this.url = url;
        this.token = token;
        this.primaryModelId = primaryModelId;
    }

    public record Preview(int modelId, String modelName, String version, String category, Double confidence,
                          int targetCount, ModelMaintenance modelMaintenance, String annotationBase64) {}

    private record WorkerResult(int modelId, String category, Double confidence, int targetCount,
                                Map<String, Integer> classCounts, String annotationBase64) {}

    public Preview detect(InputStream input, long contentLength, Integer modelId, double threshold) {
        if (url.isBlank() || token.isBlank()) throw new BusinessException(503, "单图检测服务尚未启用");
        if (contentLength > MAX_IMAGE_BYTES) throw imageSizeError();
        if (!Double.isFinite(threshold) || threshold < 0 || threshold > 1) {
            throw new BusinessException(400, "置信度阈值须介于 0 和 1 之间");
        }
        var model = models.select(modelId == null && primaryModelId > 0 ? primaryModelId : modelId);
        try {
            byte[] image = input.readNBytes(MAX_IMAGE_BYTES + 1);
            if (image.length == 0 || image.length > MAX_IMAGE_BYTES) throw imageSizeError();
            var inference = HttpRequest.newBuilder(URI.create(url + "/preview?modelId=" + model.id() + "&threshold=" + threshold))
                .timeout(Duration.ofSeconds(90))
                .header("Authorization", "Bearer " + token)
                .header("Content-Type", "application/octet-stream")
                .POST(HttpRequest.BodyPublishers.ofByteArray(image)).build();
            var response = worker.send(inference, HttpResponse.BodyHandlers.ofByteArray());
            switch (response.statusCode()) {
                case 400 -> throw new BusinessException(400, "请使用有效的 JPG 或 PNG 图片，像素总数不超过 4,000 万");
                case 404 -> throw new BusinessException(400, "所选检测模型尚未部署");
                case 429 -> throw new BusinessException(429, "单图检测繁忙，请稍后重试");
                case 200 -> { }
                default -> throw unavailable();
            }
            var result = json.readValue(response.body(), WorkerResult.class);
            if (result.modelId() != model.id() || result.classCounts() == null || result.annotationBase64() == null
                    || result.annotationBase64().isBlank()) throw unavailable();
            return new Preview(model.id(), model.name(), model.version(), result.category(), result.confidence(),
                result.targetCount(), ModelMaintenance.from(Map.of("classCounts", result.classCounts())), result.annotationBase64());
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw unavailable();
        } catch (IOException error) {
            throw unavailable();
        }
    }

    private static BusinessException imageSizeError() {
        return new BusinessException(400, "请选择 10 MB 以内的 JPG 或 PNG 图片");
    }

    private static BusinessException unavailable() {
        return new BusinessException(503, "单图检测暂时不可用，请稍后重试");
    }
}
