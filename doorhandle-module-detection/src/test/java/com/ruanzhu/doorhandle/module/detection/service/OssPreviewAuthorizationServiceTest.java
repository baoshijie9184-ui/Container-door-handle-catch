package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.ArgumentCaptor;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.apache.ibatis.builder.MapperBuilderAssistant;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class OssPreviewAuthorizationServiceTest {

    @BeforeAll
    static void initializeMybatisMetadata() {
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""),
                DetectionTask.class);
    }

    @Mock
    private DetectionTaskMapper mapper;

    @Test
    void ownerCanPreviewExactlyReferencedKey() {
        DetectionTask task = task("alice", "[\"detection/task-1/original/a.jpg\"]");
        when(mapper.selectList(any())).thenReturn(List.of(task));
        var service = service();

        service.authorize("detection/task-1/original/a.jpg", auth("alice"));
    }

    @Test
    void ownerCanPreviewSharedKeyWhenFirstCandidateIsForeign() {
        String key = "detection/shared/original/a.jpg";
        ArgumentCaptor<LambdaQueryWrapper<DetectionTask>> queryCaptor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        when(mapper.selectList(queryCaptor.capture())).thenReturn(List.of(
                task("bob", "[\"detection/shared/original/a.jpg\"]"),
                task("alice", "[\"detection/shared/original/a.jpg\"]")
        ));

        service().authorize(key, auth("alice"));

        assertThat(queryCaptor.getValue().getSqlSegment())
                .contains("created_by", "assignee", "result_json_oss_key", "original_image_keys_json", "preview_image_keys_json");
    }

    @Test
    void foreignUserCannotPreviewReferencedKey() {
        when(mapper.selectList(any())).thenReturn(List.of(
                task("alice", "[\"detection/task-1/original/a.jpg\"]")));

        assertDenied("detection/task-1/original/a.jpg", auth("bob"));
    }

    @Test
    void assigneeCanPreviewExactReferencedKey() {
        var task = task("alice", "[\"detection/task-1/original/a.jpg\"]");
        task.setAssignee("bob");
        when(mapper.selectList(any())).thenReturn(List.of(task));
        service().authorize("detection/task-1/original/a.jpg", auth("bob"));
    }

    @Test
    void rejectsUnreferencedKeyEvenUnderDetectionPrefix() {
        when(mapper.selectList(any())).thenReturn(List.of(task("alice", "[]")));

        assertDenied("detection/guessed/private.jpg", auth("alice"));
    }

    @Test
    void rejectsKeyOutsideDetectionPrefix() {
        assertDenied("models/private.onnx", auth("alice"));
    }

    private void assertDenied(String key, UsernamePasswordAuthenticationToken auth) {
        assertThatThrownBy(() -> service().authorize(key, auth))
                .isInstanceOf(BusinessException.class)
                .hasMessage("无权访问该资源");
    }

    private OssPreviewAuthorizationService service() {
        return new OssPreviewAuthorizationService(
                mapper, new ObjectMapper(), new DetectionTaskAccessPolicy());
    }

    private DetectionTask task(String owner, String originalKeys) {
        DetectionTask task = new DetectionTask();
        task.setCreatedBy(owner);
        task.setOriginalImageKeysJson(originalKeys);
        task.setPreviewImageKeysJson("[]");
        return task;
    }

    private UsernamePasswordAuthenticationToken auth(String username) {
        return new UsernamePasswordAuthenticationToken(username, "n/a",
                List.of(new SimpleGrantedAuthority("ROLE_OPERATOR")));
    }
}
