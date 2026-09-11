package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.dto.chat.ChatProjectRequest;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatProjectResponse;

import java.util.List;

public interface ChatProjectService {

    /** 获取用户的所有项目 */
    List<ChatProjectResponse> listUserProjects(String username);

    /** 创建项目 */
    ChatProjectResponse createProject(String username, ChatProjectRequest request);

    /** 更新项目 */
    ChatProjectResponse updateProject(String username, String projectId, ChatProjectRequest request);

    /** 删除项目 */
    void deleteProject(String username, String projectId);

    /** 将会话移动到项目 */
    void moveSessionToProject(String username, String sessionId, String projectId);

    /** 将会话从项目移除 */
    void removeSessionFromProject(String username, String sessionId);
}
