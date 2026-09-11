package com.ruanzhu.doorhandle.module.device.service.impl;

import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceCaptureAlert;
import com.ruanzhu.doorhandle.module.device.dto.device.DeviceAlertActionRequest;
import com.ruanzhu.doorhandle.module.device.dto.device.DeviceHeartbeatRequest;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DeviceServiceImplTest {

    @Mock
    private DeviceMapper deviceMapper;

    @Mock
    private DeviceCaptureAlertMapper deviceCaptureAlertMapper;

    @InjectMocks
    private DeviceServiceImpl deviceService;

    @Test
    void heartbeatMarksDeviceOnlineAndRefreshesLastHeartbeatAt() {
        Device device = new Device();
        device.setId(6L);
        device.setDeviceCode("CAM-01");
        device.setStatus("OFFLINE");

        when(deviceMapper.findByDeviceCode("CAM-01")).thenReturn(device);
        when(deviceMapper.updateById(device)).thenReturn(1);

        Device result = deviceService.heartbeat("CAM-01");

        assertEquals("ONLINE", result.getOnlineStatus());
        assertEquals("IDLE", result.getStatus());
        assertNotNull(result.getLastHeartbeatAt());

        ArgumentCaptor<Device> captor = ArgumentCaptor.forClass(Device.class);
        verify(deviceMapper).updateById(captor.capture());
        assertEquals(LocalDateTime.class, captor.getValue().getLastHeartbeatAt().getClass());
    }

    @Test
    void heartbeatStoresIndustrialCaptureRuntimeSnapshot() {
        Device device = new Device();
        device.setId(2L);
        device.setDeviceCode("CAM-02");
        device.setStatus("OFFLINE");

        DeviceHeartbeatRequest request = new DeviceHeartbeatRequest();
        request.setStationCode("LINE-A-ST01");
        request.setEdgeNodeId("EDGE-01");
        request.setPlcStatus("RUNNING");
        request.setCameraStatus("READY");
        request.setCaptureStatus("CAPTURING");
        request.setLastImageKey("detection/2026-06-11/CAM-02/img001.jpg");
        request.setLastCaptureAt("2026-06-11T08:30:00+08:00");
        request.setRuntimeMetadata(Map.of("fps", 18, "exposure", "12ms"));

        when(deviceMapper.findByDeviceCode("CAM-02")).thenReturn(device);
        when(deviceMapper.updateById(device)).thenReturn(1);

        Device result = deviceService.heartbeat("CAM-02", request);

        assertEquals("ONLINE", result.getOnlineStatus());
        assertEquals("IDLE", result.getStatus());
        assertEquals("LINE-A-ST01", result.getStationCode());
        assertEquals("EDGE-01", result.getEdgeNodeId());
        assertEquals("RUNNING", result.getPlcStatus());
        assertEquals("READY", result.getCameraStatus());
        assertEquals("CAPTURING", result.getCaptureStatus());
        assertEquals("detection/2026-06-11/CAM-02/img001.jpg", result.getLastImageKey());
        assertNotNull(result.getLastCaptureAt());
        assertTrue(result.getRuntimeMetadataJson().contains("\"fps\":18"));
    }

    @Test
    void heartbeatCreatesCaptureAlertWhenRuntimeReportsException() {
        Device device = new Device();
        device.setId(3L);
        device.setDeviceCode("CAM-03");
        device.setDeviceType("IMAGE_CAPTURE");
        device.setStatus("IN_USE");

        DeviceHeartbeatRequest request = new DeviceHeartbeatRequest();
        request.setStationCode("LINE-A-ST02");
        request.setEdgeNodeId("EDGE-02");
        request.setCaptureStatus("CAMERA_TIMEOUT");
        request.setCameraStatus("ERROR");
        request.setAlertLevel("MAJOR");
        request.setAlertMessage("相机连续 3 次采集超时");

        when(deviceMapper.findByDeviceCode("CAM-03")).thenReturn(device);
        when(deviceMapper.updateById(device)).thenReturn(1);
        when(deviceCaptureAlertMapper.insert(any(DeviceCaptureAlert.class))).thenReturn(1);

        deviceService.heartbeat("CAM-03", request);

        ArgumentCaptor<DeviceCaptureAlert> captor = ArgumentCaptor.forClass(DeviceCaptureAlert.class);
        verify(deviceCaptureAlertMapper).insert(captor.capture());
        DeviceCaptureAlert alert = captor.getValue();
        assertEquals("CAM-03", alert.getDeviceCode());
        assertEquals("LINE-A-ST02", alert.getStationCode());
        assertEquals("EDGE-02", alert.getEdgeNodeId());
        assertEquals("CAPTURE_EXCEPTION", alert.getAlertType());
        assertEquals("MAJOR", alert.getAlertLevel());
        assertEquals("OPEN", alert.getStatus());
        assertEquals("相机连续 3 次采集超时", alert.getAlertMessage());
    }

    @Test
    void alertLifecycleCanBeAcknowledgedAndResolved() {
        DeviceCaptureAlert alert = new DeviceCaptureAlert();
        alert.setId(12L);
        alert.setAlertId("ALERT-001");
        alert.setStatus("OPEN");

        DeviceAlertActionRequest ackRequest = new DeviceAlertActionRequest();
        ackRequest.setOperator("qa-leader");
        ackRequest.setRemark("已通知现场人员");

        when(deviceCaptureAlertMapper.selectById(12L)).thenReturn(alert);
        when(deviceCaptureAlertMapper.updateById(alert)).thenReturn(1);

        DeviceCaptureAlert acknowledged = deviceService.acknowledgeAlert(12L, ackRequest);

        assertEquals("ACKNOWLEDGED", acknowledged.getStatus());
        assertEquals("qa-leader", acknowledged.getAckOperator());
        assertNotNull(acknowledged.getAcknowledgedAt());

        DeviceAlertActionRequest resolveRequest = new DeviceAlertActionRequest();
        resolveRequest.setOperator("maintainer");
        resolveRequest.setRemark("重启相机恢复");

        DeviceCaptureAlert resolved = deviceService.resolveAlert(12L, resolveRequest);

        assertEquals("RESOLVED", resolved.getStatus());
        assertEquals("maintainer", resolved.getResolvedOperator());
        assertNotNull(resolved.getResolvedAt());
    }

    @Test
    void listCaptureAlertsReturnsPagedAlertRecords() {
        DeviceCaptureAlert alert = new DeviceCaptureAlert();
        alert.setId(1L);
        alert.setAlertId("ALERT-001");
        alert.setDeviceCode("CAM-01");
        alert.setAlertLevel("CRITICAL");
        alert.setStatus("OPEN");

        org.mockito.Mockito.doAnswer(invocation -> {
            com.baomidou.mybatisplus.extension.plugins.pagination.Page<DeviceCaptureAlert> page = invocation.getArgument(0);
            page.setRecords(List.of(alert));
            page.setTotal(1);
            return page;
        }).when(deviceCaptureAlertMapper).selectPage(any(), any());

        Map<String, Object> result = deviceService.listCaptureAlerts("OPEN", "CRITICAL", "CAM-01", 1, 20);

        assertEquals(1L, result.get("total"));
        @SuppressWarnings("unchecked")
        List<DeviceCaptureAlert> records = (List<DeviceCaptureAlert>) result.get("records");
        assertEquals("ALERT-001", records.get(0).getAlertId());
    }
}
