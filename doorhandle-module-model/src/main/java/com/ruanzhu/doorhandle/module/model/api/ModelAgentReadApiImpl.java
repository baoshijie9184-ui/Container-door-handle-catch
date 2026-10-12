package com.ruanzhu.doorhandle.module.model.api;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.ModelAgentReadApi;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
public class ModelAgentReadApiImpl implements ModelAgentReadApi {
    private final ModelInfoMapper mapper;
    public ModelAgentReadApiImpl(ModelInfoMapper mapper) { this.mapper = mapper; }

    @Override
    public List<ModelView> models(AgentActor actor, int page, int size) {
        actor.requireSupervisor();
        if (page < 1 || page > 10000 || size < 1 || size > 100) throw new IllegalArgumentException("分页参数超出范围");
        return mapper.selectList(new LambdaQueryWrapper<ModelInfo>().orderByAsc(ModelInfo::getModelId)
                        .last("LIMIT " + size + " OFFSET " + ((page - 1) * size)))
                .stream().map(m -> new ModelView(m.getModelId(), m.getModelName(), m.getVersion(),
                        m.getStatus(), m.getIsDefault())).toList();
    }
}
