package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.service.SpeechTranscriptionService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;

import java.net.URI;
import java.util.List;
import java.util.Locale;

@Slf4j
@Service
public class SpeechTranscriptionServiceImpl implements SpeechTranscriptionService {

    private static final List<String> SUPPORTED_CONTENT_TYPES = List.of(
            "audio/webm",
            "audio/wav",
            "audio/wave",
            "audio/x-wav",
            "audio/mpeg",
            "audio/mp4",
            "audio/ogg"
    );

    private final ChatAssistantProperties properties;
    private final ObjectMapper objectMapper;
    private final RestTemplate restTemplate;

    @Autowired
    public SpeechTranscriptionServiceImpl(ChatAssistantProperties properties) {
        this(properties, new ObjectMapper(), null);
    }

    SpeechTranscriptionServiceImpl(ChatAssistantProperties properties, ObjectMapper objectMapper, RestTemplate restTemplate) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.restTemplate = restTemplate;
    }

    @Override
    public String transcribe(MultipartFile file) {
        validateAudio(file);
        if (!StringUtils.hasText(properties.getVoiceTranscribeUrl())) {
            throw new BusinessException("语音识别服务未配置，请先配置 chat-assistant.voice-transcribe-url");
        }
        URI transcribeUri = validateTranscribeUrl();
        try {
            ResponseEntity<String> response = restTemplate().postForEntity(
                    transcribeUri.toString(),
                    new HttpEntity<>(body(file), multipartHeaders()),
                    String.class
            );
            String text = extractText(response.getBody());
            if (!StringUtils.hasText(text)) {
                throw new BusinessException("语音识别服务未返回有效文本");
            }
            return text.trim();
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.warn("语音识别调用失败: {}", e.getMessage());
            throw new BusinessException("语音识别失败，请稍后重试");
        }
    }

    private URI validateTranscribeUrl() {
        try {
            URI uri = URI.create(properties.getVoiceTranscribeUrl().trim());
            String scheme = uri.getScheme();
            String host = uri.getHost();
            if (!"http".equalsIgnoreCase(scheme) && !"https".equalsIgnoreCase(scheme)) {
                throw new BusinessException("语音识别服务地址仅支持 http 或 https");
            }
            if (!StringUtils.hasText(host) || StringUtils.hasText(uri.getUserInfo())) {
                throw new BusinessException("语音识别服务地址格式不安全");
            }
            if (!isAllowedTranscribeHost(host)) {
                throw new BusinessException("语音识别服务地址不在允许主机白名单内");
            }
            return uri;
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            throw new BusinessException("语音识别服务地址格式不正确");
        }
    }

    private boolean isAllowedTranscribeHost(String host) {
        List<String> allowedHosts = properties.getVoiceTranscribeAllowedHosts();
        if (allowedHosts == null || allowedHosts.isEmpty()) {
            return false;
        }
        String normalizedHost = host.toLowerCase(Locale.ROOT);
        return allowedHosts.stream()
                .filter(StringUtils::hasText)
                .map(item -> item.trim().toLowerCase(Locale.ROOT))
                .anyMatch(allowedHost -> allowedHost.equals(normalizedHost));
    }

    private void validateAudio(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new BusinessException("语音文件不能为空");
        }
        long maxBytes = properties.getVoiceMaxBytes() == null ? 10 * 1024 * 1024L : properties.getVoiceMaxBytes();
        if (file.getSize() > maxBytes) {
            throw new BusinessException("语音文件过大，请控制在 " + (maxBytes / 1024 / 1024) + "MB 以内");
        }
        String contentType = file.getContentType();
        String normalizedContentType = StringUtils.hasText(contentType)
                ? contentType.split(";", 2)[0].trim().toLowerCase(Locale.ROOT)
                : "";
        if (StringUtils.hasText(normalizedContentType)
                && SUPPORTED_CONTENT_TYPES.stream().noneMatch(normalizedContentType::equals)) {
            throw new BusinessException("暂不支持该语音格式，请使用 webm、wav、mp3、mp4 或 ogg");
        }
    }

    private MultiValueMap<String, Object> body(MultipartFile file) throws Exception {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        ByteArrayResource resource = new ByteArrayResource(file.getBytes()) {
            @Override
            public String getFilename() {
                return StringUtils.hasText(file.getOriginalFilename()) ? file.getOriginalFilename() : "voice.webm";
            }
        };
        body.add("file", resource);
        body.add("language", "zh");
        return body;
    }

    private HttpHeaders multipartHeaders() {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.MULTIPART_FORM_DATA);
        return headers;
    }

    private RestTemplate restTemplate() {
        if (restTemplate != null) {
            return restTemplate;
        }
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        int connectTimeout = properties.getVoiceConnectTimeoutMs() == null ? 1500 : properties.getVoiceConnectTimeoutMs();
        int readTimeout = properties.getVoiceReadTimeoutMs() == null ? 15000 : properties.getVoiceReadTimeoutMs();
        factory.setConnectTimeout(Math.max(200, connectTimeout));
        factory.setReadTimeout(Math.max(1000, readTimeout));
        return new RestTemplate(factory);
    }

    private String extractText(String body) throws Exception {
        if (!StringUtils.hasText(body)) {
            return "";
        }
        JsonNode root = objectMapper.readTree(body);
        if (StringUtils.hasText(root.path("text").asText())) {
            return root.path("text").asText();
        }
        if (StringUtils.hasText(root.path("transcript").asText())) {
            return root.path("transcript").asText();
        }
        return root.path("data").path("text").asText("");
    }
}
