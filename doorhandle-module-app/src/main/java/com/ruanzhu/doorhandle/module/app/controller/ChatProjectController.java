package com.ruanzhu.doorhandle.module.app.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatProjectRequest;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatProjectResponse;
import com.ruanzhu.doorhandle.module.app.service.ChatProjectService;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/chat-projects")
@RequiredArgsConstructor
@Tag(name = "聊天项目", description = "聊天项目管理接口")
public class ChatProjectController {

    private final ChatProjectService chatProjectService;

    @GetMapping
    public Result<List<ChatProjectResponse>> listProjects(Authentication authentication) {
        return Result.success(chatProjectService.listUserProjects(authentication.getName()));
    }

    @PostMapping
    public Result<ChatProjectResponse> createProject(Authentication authentication,
                                                     @Valid @RequestBody ChatProjectRequest request) {
        return Result.success(chatProjectService.createProject(authentication.getName(), request));
    }

    @PutMapping("/{projectId}")
    public Result<ChatProjectResponse> updateProject(Authentication authentication,
                                                     @PathVariable String projectId,
                                                     @Valid @RequestBody ChatProjectRequest request) {
        return Result.success(chatProjectService.updateProject(authentication.getName(), projectId, request));
    }

    @DeleteMapping("/{projectId}")
    public Result<Void> deleteProject(Authentication authentication,
                                      @PathVariable String projectId) {
        chatProjectService.deleteProject(authentication.getName(), projectId);
        return Result.success(null);
    }

    @PutMapping("/sessions/{sessionId}/move/{projectId}")
    public Result<Void> moveSessionToProject(Authentication authentication,
                                             @PathVariable String sessionId,
                                             @PathVariable String projectId) {
        chatProjectService.moveSessionToProject(authentication.getName(), sessionId, projectId);
        return Result.success(null);
    }

    @PutMapping("/sessions/{sessionId}/remove")
    public Result<Void> removeSessionFromProject(Authentication authentication,
                                                 @PathVariable String sessionId) {
        chatProjectService.removeSessionFromProject(authentication.getName(), sessionId);
        return Result.success(null);
    }
}
