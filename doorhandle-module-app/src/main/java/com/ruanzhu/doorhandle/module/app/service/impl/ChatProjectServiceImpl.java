package com.ruanzhu.doorhandle.module.app.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatProjectRequest;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatProjectResponse;
import com.ruanzhu.doorhandle.module.app.entity.ChatProject;
import com.ruanzhu.doorhandle.module.app.entity.ChatSession;
import com.ruanzhu.doorhandle.module.app.mapper.ChatProjectMapper;
import com.ruanzhu.doorhandle.module.app.mapper.ChatSessionMapper;
import com.ruanzhu.doorhandle.module.app.service.ChatProjectService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.security.core.context.SecurityContextHolder;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class ChatProjectServiceImpl implements ChatProjectService {

    private static final DateTimeFormatter TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final ChatProjectMapper chatProjectMapper;
    private final ChatSessionMapper chatSessionMapper;

    @Override
    public List<ChatProjectResponse> listUserProjects(String username) {
        LambdaQueryWrapper<ChatProject> query = new LambdaQueryWrapper<>();
        Long userId = currentUserId();
        if (userId != null) query.eq(ChatProject::getUserId, userId);
        else query.eq(ChatProject::getUsername, username);
        List<ChatProject> projects = chatProjectMapper.selectList(query
                .orderByAsc(ChatProject::getSortOrder)
                .orderByDesc(ChatProject::getCreatedAt));

        return projects.stream()
                .map(this::buildProjectResponse)
                .collect(Collectors.toList());
    }

    @Override
    public ChatProjectResponse createProject(String username, ChatProjectRequest request) {
        String projectId = "proj_" + username + "_" + UUID.randomUUID().toString().substring(0, 8);

        ChatProject project = new ChatProject();
        project.setProjectId(projectId);
        project.setUsername(username);
        project.setUserId(currentUserId());
        project.setName(request.getName());
        project.setDescription(request.getDescription());
        project.setColor(request.getColor() != null ? request.getColor() : "#4f6ef7");
        project.setSortOrder(0);
        project.setCreatedAt(LocalDateTime.now());
        project.setUpdatedAt(LocalDateTime.now());

        chatProjectMapper.insert(project);
        return buildProjectResponse(project);
    }

    @Override
    public ChatProjectResponse updateProject(String username, String projectId, ChatProjectRequest request) {
        ChatProject project = getProjectOwnedByUser(username, projectId);

        project.setName(request.getName());
        project.setDescription(request.getDescription());
        if (request.getColor() != null) {
            project.setColor(request.getColor());
        }
        project.setUpdatedAt(LocalDateTime.now());

        chatProjectMapper.updateById(project);
        return buildProjectResponse(project);
    }

    @Override
    public void deleteProject(String username, String projectId) {
        ChatProject project = getProjectOwnedByUser(username, projectId);

        // 将项目中的会话移出项目
        LambdaQueryWrapper<ChatSession> sessionQuery = new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getProjectId, projectId);
        Long userId = currentUserId();
        if (userId != null) sessionQuery.eq(ChatSession::getUserId, userId);
        else sessionQuery.eq(ChatSession::getUsername, username);
        List<ChatSession> sessions = chatSessionMapper.selectList(sessionQuery);

        for (ChatSession session : sessions) {
            boolean owned = userId != null
                    ? userId.equals(session.getUserId())
                    : username.equals(session.getUsername());
            if (!owned) continue;
            session.setProjectId(null);
            session.setUpdatedAt(LocalDateTime.now());
            chatSessionMapper.updateById(session);
        }

        // 删除项目
        chatProjectMapper.deleteById(project.getId());
    }

    @Override
    public void moveSessionToProject(String username, String sessionId, String projectId) {
        LambdaQueryWrapper<ChatSession> query = new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getSessionId, sessionId);
        Long userId = currentUserId();
        if (userId != null) query.eq(ChatSession::getUserId, userId);
        else query.eq(ChatSession::getUsername, username);
        ChatSession session = chatSessionMapper.selectOne(query.last("limit 1"));

        if (session == null) {
            throw new BusinessException(404, "会话不存在");
        }

        if (projectId != null) {
            // 校验目标项目属于当前用户
            getProjectOwnedByUser(username, projectId);
        }

        session.setProjectId(projectId);
        session.setUpdatedAt(LocalDateTime.now());
        chatSessionMapper.updateById(session);
    }

    @Override
    public void removeSessionFromProject(String username, String sessionId) {
        moveSessionToProject(username, sessionId, null);
    }

    /**
     * 获取项目并校验所有权
     */
    private ChatProject getProjectOwnedByUser(String username, String projectId) {
        LambdaQueryWrapper<ChatProject> query = new LambdaQueryWrapper<ChatProject>()
                .eq(ChatProject::getProjectId, projectId);
        Long userId = currentUserId();
        if (userId != null) query.eq(ChatProject::getUserId, userId);
        else query.eq(ChatProject::getUsername, username);
        ChatProject project = chatProjectMapper.selectOne(query.last("limit 1"));

        if (project == null) {
            throw new BusinessException(404, "项目不存在");
        }

        return project;
    }

    private ChatProjectResponse buildProjectResponse(ChatProject project) {
        ChatProjectResponse response = new ChatProjectResponse();
        response.setProjectId(project.getProjectId());
        response.setName(project.getName());
        response.setDescription(project.getDescription());
        response.setColor(project.getColor());
        response.setSortOrder(project.getSortOrder());
        response.setCreatedAt(project.getCreatedAt() == null ? null : project.getCreatedAt().format(TIME_FORMATTER));
        response.setUpdatedAt(project.getUpdatedAt() == null ? null : project.getUpdatedAt().format(TIME_FORMATTER));

        // 统计项目中的会话数
        LambdaQueryWrapper<ChatSession> countQuery = new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getProjectId, project.getProjectId());
        if (project.getUserId() != null) countQuery.eq(ChatSession::getUserId, project.getUserId());
        else countQuery.eq(ChatSession::getUsername, project.getUsername());
        Long count = chatSessionMapper.selectCount(countQuery.eq(ChatSession::getStatus, "ACTIVE"));
        response.setSessionCount(count != null ? count.intValue() : 0);

        return response;
    }

    private Long currentUserId() {
        Object principal = SecurityContextHolder.getContext().getAuthentication() == null
                ? null : SecurityContextHolder.getContext().getAuthentication().getPrincipal();
        return principal instanceof TenantPrincipal tenantPrincipal ? tenantPrincipal.userId() : null;
    }
}
