package com.ruanzhu.doorhandle.module.detection.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnit;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import java.util.List;

@Mapper
public interface DetectionWorkUnitMapper extends BaseMapper<DetectionWorkUnit> {
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
    @Select("SELECT * FROM detection_work_unit WHERE status IN ('WAITING','ASSIGNED','PROCESSING','SUBMITTED') ORDER BY created_at ASC")
    List<DetectionWorkUnit> findActive();
    @Select("SELECT * FROM detection_work_unit WHERE applicant_user_id = #{userId} OR assignee_user_id = #{userId} ORDER BY created_at DESC")
    List<DetectionWorkUnit> findMine(String userId);
}
