package com.ruanzhu.doorhandle.module.device.api;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.ResourceAgentReadApi;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import com.ruanzhu.doorhandle.module.device.entity.DeviceCaptureAlert;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper;
import java.time.LocalDateTime;
import java.util.Objects;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
public class ResourceAgentReadApiImpl implements ResourceAgentReadApi {
    private final DeviceMapper mapper;
    private final DeviceCaptureAlertMapper alerts;
    public ResourceAgentReadApiImpl(DeviceMapper mapper, DeviceCaptureAlertMapper alerts) {
        this.mapper = mapper; this.alerts = alerts;
    }

    @Override
    public List<DeviceView> devices(AgentActor actor, int page, int size) {
        actor.requireSupervisor();
        if (page < 1 || page > 10000 || size < 1 || size > 100) throw new IllegalArgumentException("分页参数超出范围");
        return mapper.selectList(new LambdaQueryWrapper<Device>().orderByAsc(Device::getId)
                        .last("LIMIT " + size + " OFFSET " + ((page - 1) * size)))
                .stream().map(this::view).toList();
    }

    @Override
    public DeviceView device(AgentActor actor, long deviceId) {
        actor.requireSupervisor();
        if (deviceId < 1) throw new IllegalArgumentException("设备 ID 不合法");
        Device device = mapper.selectById(deviceId);
        if (device == null) throw new BusinessException(404, "设备不存在");
        return view(device);
    }

    private DeviceView view(Device d) {
        return new DeviceView(d.getId().toString(), d.getDeviceCode(), d.getStatus(), d.getOnlineStatus(),
                d.getPlcStatus(), d.getCameraStatus(), d.getCaptureStatus());
    }

    @Override
    public AlertPage alerts(AgentActor actor, AlertQuery query) {
        actor.requireSupervisor();
        Objects.requireNonNull(query, "缺少查询参数");
        var wrapper = alertSummaryColumns();
        if (!query.status().equals("ALL")) wrapper.eq(DeviceCaptureAlert::getStatus, query.status());
        if (!query.level().equals("ALL")) wrapper.eq(DeviceCaptureAlert::getAlertLevel, query.level());
        if (query.deviceId() != null) wrapper.eq(DeviceCaptureAlert::getDeviceId, Long.parseLong(query.deviceId()));
        if (query.beforeId() != null) wrapper.lt(DeviceCaptureAlert::getId, Long.parseLong(query.beforeId()));
        var rows = alerts.selectList(wrapper.orderByDesc(DeviceCaptureAlert::getId).last("LIMIT " + (query.size() + 1)));
        boolean more = rows.size() > query.size();
        var items = rows.stream().limit(query.size()).map(this::alertView).toList();
        return new AlertPage(items, more ? items.get(items.size() - 1).alertId() : null, more, LocalDateTime.now());
    }

    @Override
    public AlertView alert(AgentActor actor, long alertId) {
        actor.requireSupervisor();
        if (alertId < 1) throw new IllegalArgumentException("告警 ID 不合法");
        var alert = alerts.selectOne(alertSummaryColumns().eq(DeviceCaptureAlert::getId, alertId));
        if (alert == null) throw new BusinessException(404, "告警不存在");
        return alertView(alert);
    }

    private LambdaQueryWrapper<DeviceCaptureAlert> alertSummaryColumns() {
        return new LambdaQueryWrapper<DeviceCaptureAlert>().select(DeviceCaptureAlert::getId, DeviceCaptureAlert::getAlertId,
                DeviceCaptureAlert::getDeviceId, DeviceCaptureAlert::getDeviceCode, DeviceCaptureAlert::getAlertType,
                DeviceCaptureAlert::getAlertLevel, DeviceCaptureAlert::getStatus, DeviceCaptureAlert::getCreatedAt, DeviceCaptureAlert::getUpdatedAt);
    }

    private AlertView alertView(DeviceCaptureAlert alert) {
        return new AlertView(alert.getId().toString(), alert.getAlertId(), Objects.toString(alert.getDeviceId(), null),
                alert.getDeviceCode(), alert.getAlertType(), alert.getAlertLevel(), alert.getStatus(), alert.getCreatedAt(), alert.getUpdatedAt());
    }
}
