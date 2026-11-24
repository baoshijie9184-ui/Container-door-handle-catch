package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

class DetectionTaskCompletedResultsTest {
    @Test
    void inspectorCompletedResultsBindAccountToBothRowsAndFolderDeduplication() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), DetectionTask.class);
        var fixture = new DetectionTaskServiceFixture();
        fixture.setUp();
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken("inspector-owned", "N/A",
                        List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"))));
        try {
            when(fixture.detectionTaskMapper.selectPage(any(), any())).thenAnswer(call -> {
                IPage<DetectionTask> page = call.getArgument(0);
                LambdaQueryWrapper<DetectionTask> wrapper = call.getArgument(1);
                assertThat(page.getCurrent()).isEqualTo(2);
                assertThat(page.getSize()).isEqualTo(5);
                assertThat(wrapper.getSqlSegment())
                        .contains("detection_task.task_type <> 'SINGLE'", "f.status IN ('COMPLETED','PARTIAL_FAILED')",
                                "a.source_batch_id=detection_task.task_id", "detection_task.created_by =", "f.created_by =",
                                "collector LIKE", "region LIKE")
                        .doesNotContain(":scopeUsername", "inspector-owned");
                assertThat(wrapper.getParamNameValuePairs().values())
                        .contains("inspector-owned", "COMPLETED", "PARTIAL_FAILED", "%batch%", "%collector%", "%region%");
                page.setTotal(7);
                return page;
            });
            var result = fixture.service.listTasks(2, 5, "batch", null, "collector", null, "region", false, true);
            assertThat(result).containsEntry("total", 7L);
        } finally {
            fixture.tearDown();
        }
    }
}
