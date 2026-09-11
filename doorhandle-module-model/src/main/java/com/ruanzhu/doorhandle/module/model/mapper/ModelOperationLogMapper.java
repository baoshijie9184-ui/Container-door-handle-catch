package com.ruanzhu.doorhandle.module.model.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.model.entity.ModelOperationLog;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ModelOperationLogMapper extends BaseMapper<ModelOperationLog> {

    @Select("""
            SELECT id, model_id, operation_type, operator, operation_time, remark
            FROM model_operation_log
            WHERE model_id = #{modelId}
            ORDER BY operation_time DESC, id DESC
            """)
    List<ModelOperationLog> selectByModelId(@Param("modelId") Integer modelId);
}
