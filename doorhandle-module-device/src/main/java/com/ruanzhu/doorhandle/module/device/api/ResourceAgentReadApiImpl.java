package com.ruanzhu.doorhandle.module.device.api;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.ResourceAgentReadApi;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
public class ResourceAgentReadApiImpl implements ResourceAgentReadApi {
    private final DeviceMapper mapper;
    public ResourceAgentReadApiImpl(DeviceMapper mapper) { this.mapper = mapper; }

    @Override
    public List<DeviceView> devices(AgentActor actor, int page, int size) {
        actor.requireSupervisor();
        if (page < 1 || page > 10000 || size < 1 || size > 100) throw new IllegalArgumentException("分页参数超出范围");
        return mapper.selectList(new LambdaQueryWrapper<Device>().orderByAsc(Device::getId)
                        .last("LIMIT " + size + " OFFSET " + ((page - 1) * size)))
                .stream().map(d -> new DeviceView(d.getDeviceCode(), d.getStatus(), d.getOnlineStatus(),
                        d.getPlcStatus(), d.getCameraStatus(), d.getCaptureStatus())).toList();
    }
}
