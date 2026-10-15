package com.ruanzhu.doorhandle.module.app.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.app.entity.ChatSession;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface ChatSessionMapper extends BaseMapper<ChatSession> {
    /** 复用历史 JSON 栏位保存执行事件，不恢复旧图引擎；写入始终限定会话用户。 */
    @Update("""
            UPDATE chat_session
            SET state_json = #{traceJson},
                checkpoint_version = COALESCE(checkpoint_version, 0) + 1,
                checkpoint_node = NULL,
                checkpoint_exit_reason = NULL,
                checkpoint_updated_at = NOW(), updated_at = NOW()
            WHERE user_id = #{userId} AND session_id = #{sessionId}
            """)
    int saveExecutionTrace(@Param("userId") Long userId, @Param("sessionId") String sessionId,
                           @Param("traceJson") String traceJson);
}