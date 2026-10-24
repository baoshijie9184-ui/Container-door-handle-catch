package com.ruanzhu.doorhandle.module.model.api;

import com.ruanzhu.doorhandle.contracts.agent.DetectionModelSelectionApi;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import org.springframework.stereotype.Service;
import java.util.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@Service
public class DetectionModelSelectionApiImpl implements DetectionModelSelectionApi {
    private final ModelInfoMapper models;
    public DetectionModelSelectionApiImpl(ModelInfoMapper models){this.models=models;}
    @Override @org.springframework.transaction.annotation.Transactional public void recordUse(Model expected){
        var locked=models.selectOne(new QueryWrapper<ModelInfo>().eq("model_id",expected.id()).last("FOR UPDATE"));
        if(locked==null||!"PUBLISHED".equals(locked.getStatus())||!describe(locked).equals(expected))throw new IllegalStateException("检测模型版本已变化，请重新确认");
        if(models.update(null,new com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper<ModelInfo>().eq("model_id",expected.id()).eq("status","PUBLISHED")
                .setSql("usage_count=COALESCE(usage_count,0)+1, last_used_at=CURRENT_TIMESTAMP(6)"))!=1)throw new IllegalStateException("检测模型已不可用");
    }
    @Override public Model select(Integer id){
        var query=new QueryWrapper<ModelInfo>().eq("status","PUBLISHED");
        if(id!=null){if(id<=0)throw new IllegalArgumentException("检测模型编号无效");query.eq("model_id",id);}
        query.orderByDesc("is_default").orderByAsc("model_id").last("LIMIT 1");
        var model=models.selectOne(query);
        if(model==null||model.getVersion()==null||model.getModelPath()==null)throw new IllegalArgumentException("没有可用的已发布检测模型");
        return describe(model);
    }
    private Model describe(ModelInfo model){
        if(model.getVersion()==null||model.getModelPath()==null)throw new IllegalStateException("检测模型资料不完整");
        try{
            // Metadata revision deliberately excludes mutable usage counters; no path is returned to the caller.
            String source=model.getModelId()+":"+model.getVersion().length()+":"+model.getVersion()+model.getModelPath().length()+":"+model.getModelPath()+":"+model.getStatus();
            String revision=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(source.getBytes(StandardCharsets.UTF_8)));
            return new Model(model.getModelId(),model.getModelName(),model.getVersion(),revision);
        }catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}
    }
}
