package com.ruanzhu.doorhandle.module.app.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.app.entity.ChatPendingAction;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface ChatPendingActionMapper extends BaseMapper<ChatPendingAction> {

    @Update("""
            UPDATE chat_pending_action
            SET status = #{targetStatus},
                confirmed_at = CASE WHEN #{targetStatus} = 'EXECUTING' THEN CURRENT_TIMESTAMP ELSE confirmed_at END,
                error_message = #{errorMessage}
            WHERE session_id = #{sessionId}
              AND action_id = #{actionId}
              AND status = #{expectedStatus}
            """)
    int transitionStatus(@Param("sessionId") String sessionId,
                         @Param("actionId") String actionId,
                         @Param("expectedStatus") String expectedStatus,
                         @Param("targetStatus") String targetStatus,
                         @Param("errorMessage") String errorMessage);
}
