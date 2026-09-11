package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class SpeechTranscriptionServiceImplTest {

    @Test
    void shouldRejectEmptyAudioFile() {
        SpeechTranscriptionServiceImpl service = new SpeechTranscriptionServiceImpl(new ChatAssistantProperties());
        MockMultipartFile file = new MockMultipartFile("file", "empty.webm", "audio/webm", new byte[0]);

        assertThatThrownBy(() -> service.transcribe(file))
                .isInstanceOf(BusinessException.class)
                .hasMessage("语音文件不能为空");
    }

    @Test
    void shouldExplainWhenAsrServiceIsNotConfigured() {
        SpeechTranscriptionServiceImpl service = new SpeechTranscriptionServiceImpl(new ChatAssistantProperties());
        MockMultipartFile file = new MockMultipartFile("file", "voice.webm", "audio/webm", "voice".getBytes());

        assertThatThrownBy(() -> service.transcribe(file))
                .isInstanceOf(BusinessException.class)
                .hasMessage("语音识别服务未配置，请先配置 chat-assistant.voice-transcribe-url");
    }

    @Test
    void shouldParseTextFromAsrServiceResponse() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setVoiceTranscribeUrl("http://asr.local/transcribe");
        properties.setVoiceTranscribeAllowedHosts(List.of("asr.local"));
        RestTemplate restTemplate = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.bindTo(restTemplate).build();
        server.expect(requestTo("http://asr.local/transcribe"))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withSuccess("{\"data\":{\"text\":\"查看待复核质检队列\"}}", MediaType.APPLICATION_JSON));
        SpeechTranscriptionServiceImpl service = new SpeechTranscriptionServiceImpl(properties, new ObjectMapper(), restTemplate);
        MockMultipartFile file = new MockMultipartFile("file", "voice.webm", "audio/webm", "voice".getBytes());

        String text = service.transcribe(file);

        assertThat(text).isEqualTo("查看待复核质检队列");
        server.verify();
    }

    @Test
    void shouldAcceptWebmContentTypeWithCodecParameters() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setVoiceTranscribeUrl("http://asr.local/transcribe");
        properties.setVoiceTranscribeAllowedHosts(List.of("asr.local"));
        RestTemplate restTemplate = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.bindTo(restTemplate).build();
        server.expect(requestTo("http://asr.local/transcribe"))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withSuccess("{\"text\":\"查询上海质检队列\"}", MediaType.APPLICATION_JSON));
        SpeechTranscriptionServiceImpl service = new SpeechTranscriptionServiceImpl(
                properties, new ObjectMapper(), restTemplate);
        MockMultipartFile file = new MockMultipartFile(
                "file", "voice.webm", "audio/webm;codecs=opus", "voice".getBytes());

        String text = service.transcribe(file);

        assertThat(text).isEqualTo("查询上海质检队列");
        server.verify();
    }

    @Test
    void shouldRejectAsrServiceOutsideAllowedHosts() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setVoiceTranscribeUrl("http://169.254.169.254/latest/meta-data");
        SpeechTranscriptionServiceImpl service = new SpeechTranscriptionServiceImpl(properties);
        MockMultipartFile file = new MockMultipartFile("file", "voice.webm", "audio/webm", "voice".getBytes());

        assertThatThrownBy(() -> service.transcribe(file))
                .isInstanceOf(BusinessException.class)
                .hasMessage("语音识别服务地址不在允许主机白名单内");
    }

    @Test
    void shouldRejectAsrServiceWithUnsafeProtocol() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setVoiceTranscribeUrl("file:///C:/Users/19771/.ssh/id_rsa");
        SpeechTranscriptionServiceImpl service = new SpeechTranscriptionServiceImpl(properties);
        MockMultipartFile file = new MockMultipartFile("file", "voice.webm", "audio/webm", "voice".getBytes());

        assertThatThrownBy(() -> service.transcribe(file))
                .isInstanceOf(BusinessException.class)
                .hasMessage("语音识别服务地址仅支持 http 或 https");
    }
}
