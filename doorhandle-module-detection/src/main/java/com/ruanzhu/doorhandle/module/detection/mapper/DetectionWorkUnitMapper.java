package com.ruanzhu.doorhandle.module.detection.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnit;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import java.util.List;

@Mapper
public interface DetectionWorkUnitMapper extends BaseMapper<DetectionWorkUnit> {
    @org.apache.ibatis.annotations.Insert("""
        INSERT INTO detection_work_unit(work_unit_id,applicant_user_id,image_count,strategy,model_version,remark)
        VALUES(#{workUnitId},#{applicantUserId},#{imageCount},#{strategy},#{modelVersion},#{remark})
        ON DUPLICATE KEY UPDATE id=id
        """)
    void insertApplication(DetectionWorkUnit unit);

    @Select("SELECT * FROM detection_work_unit WHERE work_unit_id=#{id} FOR UPDATE")
    DetectionWorkUnit lock(String id);

    @Select("SELECT status, COUNT(*) AS total FROM detection_work_unit WHERE assignee_user_id = #{userId} GROUP BY status")
    List<java.util.Map<String, Object>> countAssignedStatuses(@org.apache.ibatis.annotations.Param("userId") String userId);

    @Select("SELECT status, COUNT(*) AS total FROM detection_work_unit GROUP BY status")
    List<java.util.Map<String, Object>> countDepartmentStatuses();
    @org.apache.ibatis.annotations.Update("""
        UPDATE detection_work_unit
        SET status=#{unit.status}, assignee_user_id=#{unit.assigneeUserId},
            assigned_at=#{unit.assignedAt}, submitted_at=#{unit.submittedAt},
            completed_count=#{unit.completedCount}, remark=#{unit.remark},
            updated_at=#{unit.updatedAt}, version=version+1
        WHERE work_unit_id=#{unit.workUnitId} AND version=#{expectedVersion} AND status=#{expectedStatus}
        """)
    int transition(@org.apache.ibatis.annotations.Param("unit") DetectionWorkUnit unit,
                   @org.apache.ibatis.annotations.Param("expectedVersion") Integer expectedVersion,
                   @org.apache.ibatis.annotations.Param("expectedStatus") String expectedStatus);

    @Update("""
        UPDATE detection_work_unit
        SET status=#{unit.status}, decision_request_id=#{unit.decisionRequestId},
            decision_actor_user_id=#{unit.decisionActorUserId}, decision_reason=#{unit.decisionReason},
            updated_at=#{unit.updatedAt}, version=version+1
        WHERE work_unit_id=#{unit.workUnitId} AND version=#{expectedVersion} AND status='WAITING'
          AND strategy<>'OSS_FOLDER' AND assignee_user_id IS NULL AND source_batch_id IS NULL AND batch_id IS NULL
          AND decision_request_id IS NULL
        """)
    int recordApplicationDecision(@Param("unit") DetectionWorkUnit unit, @Param("expectedVersion") int expectedVersion);

    @Select("SELECT * FROM detection_work_unit WHERE strategy <> 'OSS_FOLDER' AND status IN ('WAITING','ASSIGNED','PROCESSING','SUBMITTED') ORDER BY created_at ASC")
    List<DetectionWorkUnit> findActive();
    @Select("SELECT * FROM detection_work_unit WHERE strategy <> 'OSS_FOLDER' AND (applicant_user_id = #{userId} OR assignee_user_id = #{userId}) ORDER BY created_at DESC")
    List<DetectionWorkUnit> findMine(String userId);
}
