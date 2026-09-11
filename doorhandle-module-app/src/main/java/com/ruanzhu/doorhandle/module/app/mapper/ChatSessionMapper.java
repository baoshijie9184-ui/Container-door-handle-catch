package com.ruanzhu.doorhandle.module.app.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.app.entity.ChatSession;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface ChatSessionMapper extends BaseMapper<ChatSession> {

    @Update("UPDATE chat_session SET state_json = #{stateJson}, updated_at = NOW() WHERE session_id = #{sessionId}")
    int updateStateJson(@Param("sessionId") String sessionId, @Param("stateJson") String stateJson);

    @Update("""
            UPDATE chat_session
            SET state_json = #{stateJson},
                checkpoint_version = COALESCE(checkpoint_version, 0) + 1,
                checkpoint_node = #{checkpointNode},
                checkpoint_exit_reason = #{checkpointExitReason},
                checkpoint_updated_at = NOW(),
                updated_at = NOW()
            WHERE session_id = #{sessionId}
            """)
    int updateCheckpoint(@Param("sessionId") String sessionId,
                         @Param("stateJson") String stateJson,
                         @Param("checkpointNode") String checkpointNode,
                         @Param("checkpointExitReason") String checkpointExitReason);

    @Update("""
            UPDATE chat_session
            SET state_json = #{stateJson},
                checkpoint_version = COALESCE(checkpoint_version, 0) + 1,
                checkpoint_node = #{checkpointNode},
                checkpoint_exit_reason = #{checkpointExitReason},
                checkpoint_updated_at = NOW(),
                updated_at = NOW()
            WHERE user_id = #{userId} AND session_id = #{sessionId}
            """)
    int updateCheckpointForTenant(@Param("userId") Long userId,
                                  @Param("sessionId") String sessionId,
                                  @Param("stateJson") String stateJson,
                                  @Param("checkpointNode") String checkpointNode,
                                  @Param("checkpointExitReason") String checkpointExitReason);

    @Update("""
            UPDATE chat_session
            SET state_json = NULL,
                checkpoint_version = COALESCE(checkpoint_version, 0) + 1,
                checkpoint_node = NULL,
                checkpoint_exit_reason = NULL,
                checkpoint_updated_at = NOW(),
                updated_at = NOW()
            WHERE session_id = #{sessionId}
            """)
    int clearCheckpoint(@Param("sessionId") String sessionId);

    @Update("""
            UPDATE chat_session
            SET state_json = NULL,
                checkpoint_version = COALESCE(checkpoint_version, 0) + 1,
                checkpoint_node = NULL,
                checkpoint_exit_reason = NULL,
                checkpoint_updated_at = NOW(),
                updated_at = NOW()
            WHERE user_id = #{userId} AND session_id = #{sessionId}
            """)
    int clearCheckpointForTenant(@Param("userId") Long userId, @Param("sessionId") String sessionId);

    @Select("SELECT state_json FROM chat_session WHERE session_id = #{sessionId}")
    String selectStateJson(@Param("sessionId") String sessionId);

    @Select("SELECT state_json FROM chat_session WHERE user_id = #{userId} AND session_id = #{sessionId}")
    String selectStateJsonForTenant(@Param("userId") Long userId, @Param("sessionId") String sessionId);

    @Select("""
            SELECT id, session_id, username, title, status, pinned, project_id, created_at, updated_at,
                   state_json, checkpoint_version, checkpoint_node, checkpoint_exit_reason, checkpoint_updated_at
            FROM chat_session
            WHERE session_id = #{sessionId}
            LIMIT 1
            """)
    ChatSession selectCheckpointSnapshot(@Param("sessionId") String sessionId);
}
