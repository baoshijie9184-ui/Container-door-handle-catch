package com.ruanzhu.doorhandle.module.detection.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface DetectionTaskMapper extends BaseMapper<DetectionTask> {

    /** Explicit NULLs: updateById otherwise preserves the previous disposition and its operator. */
    @Update("UPDATE detection_task SET disposition_status=NULL,disposition_action=NULL,disposition_remark=NULL,disposition_operator=NULL,disposed_at=NULL WHERE task_id=#{taskId} AND flow_status IN ('RECHECK_REQUIRED','PENDING_REVIEW')")
    int clearDispositionForRework(@Param("taskId") String taskId);

    /** updateById ignores nulls by default, so resetting a retry must explicitly clear old results. */
    @Update("""
            UPDATE detection_task SET status='UPLOADED',stage='UPLOADED',flow_status='PENDING_DETECTION',
            processed_images=0,successful_images=0,failed_images=0,
            result_oss_prefix=NULL,result_json_oss_key=NULL,preview_image_keys_json=NULL,statistics_json=NULL,
            defect_evidence_json=NULL,defect_count=0,primary_defect_type=NULL,max_defect_severity=NULL,error_message=NULL,
            review_status='PENDING',review_conclusion=NULL,severity_level=NULL,confirmed_defect_count=0,false_positive_count=0,
            review_remark=NULL,reviewer=NULL,reviewed_at=NULL,
            disposition_status='PENDING',disposition_action=NULL,disposition_remark=NULL,disposition_operator=NULL,disposed_at=NULL,
            recheck_required=FALSE,started_at=NULL,finished_at=NULL,last_finished_event_id=NULL,
            dispatch_id=#{task.dispatchId},updated_at=#{task.updatedAt}
            WHERE task_id=#{task.taskId}
            """)
    int resetForRetry(@Param("task") DetectionTask task);

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
