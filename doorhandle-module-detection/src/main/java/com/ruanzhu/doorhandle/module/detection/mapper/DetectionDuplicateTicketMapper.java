package com.ruanzhu.doorhandle.module.detection.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionDuplicateTicket;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import java.util.List;

@Mapper
public interface DetectionDuplicateTicketMapper extends BaseMapper<DetectionDuplicateTicket> {
    String COLUMNS="id,ticket_id,sha256,left_task_id,right_task_id,left_employee_id,right_employee_id,left_folder_name,right_folder_name,"
            +"left_images_json,right_images_json,assigned_to,comparison_result,resolution,status,approved_by,approved_at,version,created_at,updated_at";
    @Select("SELECT status, COUNT(*) AS total FROM detection_duplicate_ticket WHERE assigned_to = #{userId} GROUP BY status")
    List<java.util.Map<String, Object>> countAssignedStatuses(@org.apache.ibatis.annotations.Param("userId") String userId);

    @Select("SELECT status, COUNT(*) AS total FROM detection_duplicate_ticket GROUP BY status")
    List<java.util.Map<String, Object>> countDepartmentStatuses();
    @org.apache.ibatis.annotations.Update("""
        UPDATE detection_duplicate_ticket
        SET resolution = #{ticket.resolution}, comparison_result = #{ticket.comparisonResult},
            status = 'RESOLVED', approved_by = #{ticket.approvedBy},
            approved_at = #{ticket.approvedAt}, updated_at = #{ticket.updatedAt}, version = version + 1
        WHERE ticket_id = #{ticket.ticketId} AND version = #{expectedVersion}
          AND status IN ('OPEN','ASSIGNED','COMPARING','PENDING_APPROVAL')
        """)
    int resolveIfVersion(@org.apache.ibatis.annotations.Param("ticket") DetectionDuplicateTicket ticket,
                         @org.apache.ibatis.annotations.Param("expectedVersion") Integer expectedVersion);
    @Select("SELECT "+COLUMNS+" FROM detection_duplicate_ticket WHERE status IN ('OPEN','ASSIGNED','COMPARING','PENDING_APPROVAL') ORDER BY created_at ASC,id ASC")
    List<DetectionDuplicateTicket> findPending();
}
