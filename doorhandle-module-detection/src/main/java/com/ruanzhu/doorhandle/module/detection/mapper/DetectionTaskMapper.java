package com.ruanzhu.doorhandle.module.detection.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface DetectionTaskMapper extends BaseMapper<DetectionTask> {

    @Update("""
            UPDATE detection_task
            SET original_image_keys_json = #{task.originalImageKeysJson},
                model_id = #{task.modelId},
                model_version = #{task.modelVersion},
                threshold = #{task.threshold},
                total_images = #{task.totalImages},
                status = 'UPLOADED',
                stage = 'UPLOADED',
                flow_status = 'PENDING_DETECTION',
                dispatch_id = #{task.dispatchId},
                last_finished_event_id = NULL,
                error_message = NULL,
                updated_at = #{task.updatedAt}
            WHERE task_id = #{task.taskId}
              AND status IN ('UPLOADING', 'FAILED')
            """)
    int claimUploaded(@Param("task") DetectionTask task);
}
