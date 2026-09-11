package com.ruanzhu.doorhandle.module.detection.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionDuplicateTicket;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import java.util.List;

@Mapper
public interface DetectionDuplicateTicketMapper extends BaseMapper<DetectionDuplicateTicket> {
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
    @Select("SELECT * FROM detection_duplicate_ticket WHERE status IN ('OPEN','ASSIGNED','COMPARING','PENDING_APPROVAL') ORDER BY created_at ASC")
    List<DetectionDuplicateTicket> findPending();
}
