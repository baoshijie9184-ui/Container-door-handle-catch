package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.module.app.entity.ChatProject;
import com.ruanzhu.doorhandle.module.app.entity.ChatSession;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatProjectRequest;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.module.app.mapper.ChatProjectMapper;
import com.ruanzhu.doorhandle.module.app.mapper.ChatSessionMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ChatProjectServiceImplTest {

    @BeforeAll
    static void initMetadata() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), ChatProject.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), ChatSession.class);
    }

    private ChatProjectMapper chatProjectMapper;
    private ChatSessionMapper chatSessionMapper;
    private ChatProjectServiceImpl chatProjectService;

    @BeforeEach
    void setUp() {
        chatProjectMapper = mock(ChatProjectMapper.class);
        chatSessionMapper = mock(ChatSessionMapper.class);
        chatProjectService = new ChatProjectServiceImpl(chatProjectMapper, chatSessionMapper);
    }

    @Test
    void shouldDetachOnlyOwnedSessionsWhenDeletingProject() {
        ChatProject project = new ChatProject();
        project.setId(10L);
        project.setProjectId("proj_admin_001");
        project.setUsername("admin");

        ChatSession ownSession = new ChatSession();
        ownSession.setSessionId("sess_admin_001");
        ownSession.setUsername("admin");
        ownSession.setProjectId("proj_admin_001");

        ChatSession otherSession = new ChatSession();
        otherSession.setSessionId("sess_other_001");
        otherSession.setUsername("other");
        otherSession.setProjectId("proj_admin_001");

        when(chatProjectMapper.selectOne(any())).thenReturn(project);
        when(chatSessionMapper.selectList(any())).thenReturn(List.of(ownSession, otherSession));

        chatProjectService.deleteProject("admin", "proj_admin_001");

        ArgumentCaptor<LambdaUpdateWrapper<ChatSession>> update = ArgumentCaptor.forClass(LambdaUpdateWrapper.class);
        assertThat(otherSession.getProjectId()).isEqualTo("proj_admin_001");
        verify(chatSessionMapper).update(isNull(), update.capture());
        assertThat(update.getValue().getSqlSet()).contains("project_id");
        assertThat(update.getValue().getSqlSegment()).contains("username", "session_id", "project_id");
        assertThat(update.getValue().getParamNameValuePairs()).containsValue(null).containsValue("admin").containsValue("sess_admin_001").doesNotContainValue("other");
        verify(chatProjectMapper).deleteById(10L);
    }

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void createdProjectStoresImmutableTenantUserId() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        new TenantPrincipal(42L, "alice", "N/A", List.of()), null, List.of()));
        ChatProjectRequest request = new ChatProjectRequest();
        request.setName("Tenant project");
        ArgumentCaptor<ChatProject> captor = ArgumentCaptor.forClass(ChatProject.class);

        chatProjectService.createProject("alice", request);

        verify(chatProjectMapper).insert(captor.capture());
        assertThat(captor.getValue().getUserId()).isEqualTo(42L);
    }

    @Test
    void projectListFiltersByImmutableTenantUserId() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        new TenantPrincipal(42L, "alice", "N/A", List.of()), null, List.of()));
        ArgumentCaptor<LambdaQueryWrapper<ChatProject>> captor = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        when(chatProjectMapper.selectList(captor.capture())).thenReturn(List.of());

        chatProjectService.listUserProjects("alice");

        assertThat(captor.getValue().getSqlSegment()).contains("user_id").doesNotContain("username");
    }

    @Test
    void movingSessionFiltersByImmutableTenantUserId() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        new TenantPrincipal(42L, "alice", "N/A", List.of()), null, List.of()));
        ChatSession session = new ChatSession();
        session.setSessionId("sess_alice_001");
        session.setUserId(42L);
        session.setUsername("alice");
        ArgumentCaptor<LambdaQueryWrapper<ChatSession>> captor = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        when(chatSessionMapper.selectOne(captor.capture())).thenReturn(session);

        chatProjectService.moveSessionToProject("alice", session.getSessionId(), null);

        assertThat(captor.getValue().getSqlSegment()).contains("user_id").doesNotContain("username");
        ArgumentCaptor<LambdaUpdateWrapper<ChatSession>> update = ArgumentCaptor.forClass(LambdaUpdateWrapper.class);
        verify(chatSessionMapper).update(isNull(), update.capture());
        assertThat(update.getValue().getSqlSet()).contains("project_id");
        assertThat(update.getValue().getSqlSegment()).contains("user_id", "session_id").doesNotContain("username");
        assertThat(update.getValue().getParamNameValuePairs()).containsValue(null).containsValue(42L);
    }

    @Test
    void missingOrForeignProjectCannotBeAssignedAfterTheForeignKeyIsRemoved() {
        ChatSession session = new ChatSession();session.setSessionId("owned");session.setUsername("alice");
        when(chatSessionMapper.selectOne(any())).thenReturn(session);
        ArgumentCaptor<LambdaQueryWrapper<ChatProject>> query = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        when(chatProjectMapper.selectOne(query.capture())).thenReturn(null);
        assertThatThrownBy(() -> chatProjectService.moveSessionToProject("alice", "owned", "other-project"))
                .isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);
        assertThat(query.getValue().getSqlSegment()).contains("username", "project_id", "FOR UPDATE");
        assertThat(query.getValue().getParamNameValuePairs()).containsValue("alice").containsValue("other-project");
        verify(chatSessionMapper, never()).update(any(), any());
    }

    @Test
    void missingOrForeignSessionCannotBeMovedOrDetached() {
        when(chatSessionMapper.selectOne(any())).thenReturn(null);
        assertThatThrownBy(() -> chatProjectService.removeSessionFromProject("alice", "foreign-session"))
                .isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);
        verify(chatSessionMapper, never()).update(any(), any());
        verify(chatProjectMapper, never()).selectOne(any());
    }
}
