package com.ruanzhu.doorhandle.module.app.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatConfirmActionRequest;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatMessageResponse;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatSendMessageRequest;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatSessionResponse;
import com.ruanzhu.doorhandle.module.app.dto.chat.CheckpointSnapshotResponse;
import com.ruanzhu.doorhandle.module.app.dto.chat.AgentGraphHealthResponse;
import com.ruanzhu.doorhandle.module.app.service.AgentOrchestratorService;
import com.ruanzhu.doorhandle.module.app.service.AgentGraphRunMonitor;
import com.ruanzhu.doorhandle.module.app.service.ChatSessionService;
import com.ruanzhu.doorhandle.module.app.service.SpeechTranscriptionService;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/chat-assistant")
@RequiredArgsConstructor
@Tag(name = "聊天助手", description = "统一聊天助手接口")
public class ChatAssistantController {

    private final ChatSessionService chatSessionService;
    private final AgentOrchestratorService agentOrchestratorService;
    private final AgentGraphRunMonitor agentGraphRunMonitor;
    private final SpeechTranscriptionService speechTranscriptionService;

    // ---- 会话管理 ----

    @GetMapping("/sessions")
    public Result<List<ChatSessionResponse>> listSessions(Authentication authentication) {
        return Result.success(chatSessionService.listUserSessions(authentication.getName()));
    }

    @PostMapping("/sessions")
    public Result<ChatSessionResponse> createSession(Authentication authentication) {
        return Result.success(chatSessionService.createSession(authentication.getName()));
    }

    @GetMapping("/sessions/{sessionId}")
    public Result<ChatSessionResponse> getSession(Authentication authentication,
                                                  @PathVariable String sessionId) {
        return Result.success(chatSessionService.getSession(authentication.getName(), sessionId));
    }

    @GetMapping("/sessions/{sessionId}/checkpoint")
    public Result<CheckpointSnapshotResponse> getCheckpointSnapshot(Authentication authentication,
                                                                    @PathVariable String sessionId) {
        return Result.success(chatSessionService.getCheckpointSnapshot(authentication.getName(), sessionId));
    }

    @GetMapping("/agent-health")
    public Result<AgentGraphHealthResponse> getAgentGraphHealth() {
        return Result.success(agentGraphRunMonitor.snapshot());
    }

    @GetMapping("/sessions/{sessionId}/messages")
    public Result<List<ChatMessageResponse>> getSessionMessages(Authentication authentication,
                                                                @PathVariable String sessionId) {
        return Result.success(chatSessionService.listMessages(authentication.getName(), sessionId));
    }

    @PutMapping("/sessions/{sessionId}/archive")
    public Result<Void> archiveSession(Authentication authentication,
                                       @PathVariable String sessionId) {
        chatSessionService.archiveSession(authentication.getName(), sessionId);
        return Result.success(null);
    }

    @DeleteMapping("/sessions/{sessionId}")
    public Result<Void> deleteSession(Authentication authentication,
                                      @PathVariable String sessionId) {
        chatSessionService.deleteSession(authentication.getName(), sessionId);
        return Result.success(null);
    }

    @PutMapping("/sessions/{sessionId}/title")
    public Result<Void> renameSession(Authentication authentication,
                                      @PathVariable String sessionId,
                                      @RequestBody java.util.Map<String, String> body) {
        chatSessionService.renameSession(authentication.getName(), sessionId, body.get("title"));
        return Result.success(null);
    }

    @PutMapping("/sessions/{sessionId}/pin")
    public Result<Void> togglePinSession(Authentication authentication,
                                         @PathVariable String sessionId,
                                         @RequestBody java.util.Map<String, Boolean> body) {
        chatSessionService.togglePinSession(authentication.getName(), sessionId, body.getOrDefault("pinned", true));
        return Result.success(null);
    }

    // ---- 原有接口 ----

    @GetMapping("/session")
    public Result<ChatSessionResponse> getSessionLegacy(Authentication authentication) {
        return Result.success(chatSessionService.getOrCreateActiveSession(authentication.getName()));
    }

    @PostMapping("/messages")
    public Result<ChatMessageResponse> sendMessage(Authentication authentication,
                                                   @Valid @RequestBody ChatSendMessageRequest request) {
        return Result.success(agentOrchestratorService.handleUserMessage(authentication.getName(), request));
    }

    @PostMapping(value = "/messages/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamMessage(Authentication authentication,
                                    @Valid @RequestBody ChatSendMessageRequest request) {
        return agentOrchestratorService.streamUserMessage(authentication.getName(), request);
    }

    @PostMapping("/confirm")
    public Result<ChatMessageResponse> confirm(Authentication authentication,
                                               @Valid @RequestBody ChatConfirmActionRequest request) {
        return Result.success(agentOrchestratorService.confirmAction(authentication.getName(), request));
    }

    @PostMapping(value = "/voice/transcribe", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Result<Map<String, String>> transcribeVoice(@RequestParam("file") MultipartFile file) {
        String text = speechTranscriptionService.transcribe(file);
        return Result.success(Map.of("text", text));
    }
}
