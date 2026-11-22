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
    String ACTIVE_WORK_UNITS = """
        u.status IN ('WAITING','ASSIGNED','PROCESSING','SUBMITTED')
        AND (u.strategy='OSS_FOLDER' OR NOT EXISTS (
            SELECT 1 FROM detection_work_unit f WHERE f.work_unit_id=u.batch_id AND f.strategy='OSS_FOLDER'
        ))
        """;
    String APPROVED_WITHOUT_IMAGES = """
        u.strategy<>'OSS_FOLDER' AND u.status='ASSIGNED' AND u.source_batch_id IS NULL AND u.batch_id IS NULL
        AND u.assignee_user_id IS NOT NULL AND BINARY u.assignee_user_id=BINARY u.applicant_user_id
        AND NOT EXISTS (SELECT 1 FROM detection_input i WHERE i.work_unit_id=u.work_unit_id)
        """;

    @org.apache.ibatis.annotations.Insert("""
        INSERT INTO detection_work_unit(work_unit_id,applicant_user_id,image_count,strategy,model_version,remark)
        VALUES(#{workUnitId},#{applicantUserId},#{imageCount},#{strategy},#{modelVersion},#{remark})
        ON DUPLICATE KEY UPDATE id=id
        """)
    void insertApplication(DetectionWorkUnit unit);

    @Select("SELECT * FROM detection_work_unit WHERE work_unit_id=#{id} FOR UPDATE")
    DetectionWorkUnit lock(String id);

    @Select("""
        SELECT u.status, COUNT(*) AS total FROM detection_work_unit u WHERE
        ((u.strategy='OSS_FOLDER' AND u.assignee_user_id=CAST(#{userId} AS CHAR))
         OR (u.strategy<>'OSS_FOLDER' AND BINARY u.assignee_user_id=BINARY #{username})) AND
        """ + ACTIVE_WORK_UNITS + " AND NOT (" + APPROVED_WITHOUT_IMAGES + ") GROUP BY u.status")
    List<java.util.Map<String, Object>> countAssignedStatuses(@Param("username") String username, @Param("userId") long userId);

    @Select("SELECT CASE WHEN " + APPROVED_WITHOUT_IMAGES + " THEN 'WAITING' ELSE u.status END AS status, "
        + "COUNT(*) AS total FROM detection_work_unit u WHERE " + ACTIVE_WORK_UNITS + " GROUP BY 1")
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
