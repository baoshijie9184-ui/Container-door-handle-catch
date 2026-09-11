package com.ruanzhu.doorhandle.module.model.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Delete;
import java.util.List;

/**
 * 模型信息Mapper接口
 */
@Mapper
public interface ModelInfoMapper extends BaseMapper<ModelInfo> {
    ModelInfo selectByModelNameAndVersion(@Param("modelName") String modelName, @Param("version") String version);

    List<ModelInfo> selectAll();

    @Select("SELECT COALESCE(MAX(model_id), 0) + 1 FROM model_management")
    Integer selectNextModelId();

    int updateModelRecord(ModelInfo modelInfo);
    
    /**
     * 根据模型ID查询模型信息
     * @param modelId 模型ID
     * @return 模型信息
     */
    @Select("""
            SELECT model_id, model_name, version, model_path, upload_time, update_description,
                   status, is_default, creator, published_at, last_used_at, usage_count,
                   validation_status, validation_message, mlops_status, evaluation_dataset,
                   precision_score, recall_score, map_score, f1_score, avg_inference_ms,
                   compatibility_note, deployment_strategy, canary_percent, ab_group,
                   rollback_from_model_id
            FROM model_management
            WHERE model_id = #{modelId}
            """)
    ModelInfo selectByModelId(@Param("modelId") Integer modelId);
    
    /**
     * 根据模型ID删除模型信息
     * @param modelId 模型ID
     * @return 删除记录数
     */
    @Delete("DELETE FROM model_management WHERE model_id = #{modelId}")
    int deleteByModelId(@Param("modelId") Integer modelId);
} 
