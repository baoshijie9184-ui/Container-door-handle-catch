package com.ruanzhu.doorhandle.module.device.service.impl;

import com.ruanzhu.doorhandle.contracts.security.BusinessPrincipal;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceCaptureAlert;
import com.ruanzhu.doorhandle.module.device.dto.device.DeviceAlertActionRequest;
import com.ruanzhu.doorhandle.module.device.dto.device.DeviceHeartbeatRequest;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DeviceServiceImplTest {

    @Mock
    private DeviceMapper deviceMapper;

    @Mock
    private DeviceCaptureAlertMapper deviceCaptureAlertMapper;

    @Mock
    private com.ruanzhu.doorhandle.module.device.service.DeviceUsageRecordService deviceUsageRecordService;

    @Mock
    private BusinessUserDirectory businessUsers;

    @InjectMocks
    private DeviceServiceImpl deviceService;

    @BeforeEach
    void startWithEmptySecurityContext() {
        SecurityContextHolder.clearContext();
    }

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    private record AlertPrincipal(Long userId, String username) implements BusinessPrincipal {}

    private void authenticate(Long userId, String username) {
        var context = SecurityContextHolder.createEmptyContext();
        context.setAuthentication(new UsernamePasswordAuthenticationToken(new AlertPrincipal(userId, username), null,
                List.of(new SimpleGrantedAuthority("ROLE_SUPERVISOR"))));
        SecurityContextHolder.setContext(context);
    }

    private void supervisorHeartbeat() {
        var actor = new BusinessUserDirectory.Identity(2L,"boss",true);
        when(businessUsers.authenticated()).thenReturn(actor);
        when(businessUsers.lockCurrent(actor.userId(),actor.username())).thenReturn(actor);
    }

    private void employeeHeartbeat() {
        var actor = new BusinessUserDirectory.Identity(3L,"worker",false);
        when(businessUsers.authenticated()).thenReturn(actor);
        when(businessUsers.lockDetectionEmployeeId(actor.userId(),actor.username())).thenReturn(17L);
    }

    @Test
    void heartbeatMarksDeviceOnlineAndRefreshesLastHeartbeatAt() {
        Device device = new Device();
        device.setId(6L);
        device.setDeviceCode("CAM-01");
        device.setStatus("OFFLINE");

        supervisorHeartbeat();
        when(deviceMapper.findByDeviceCodeForUpdate("CAM-01")).thenReturn(device);
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
        device.setEmployeeId(17L);
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

        employeeHeartbeat();
        when(deviceMapper.findByDeviceCodeForUpdate("CAM-02")).thenReturn(device);
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

        supervisorHeartbeat();
        when(deviceMapper.findByDeviceCodeForUpdate("CAM-03")).thenReturn(device);
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
    void employeeCannotReportHeartbeatForUnassignedOrForeignDevice() {
        employeeHeartbeat();
        var device = new Device();
        device.setId(4L);
        device.setEmployeeId(99L);
        when(deviceMapper.findByDeviceCodeForUpdate("CAM-04")).thenReturn(device);
        var unassigned = new Device();
        unassigned.setId(5L);
        when(deviceMapper.findByDeviceCodeForUpdate("CAM-05")).thenReturn(unassigned);

        assertThrows(AccessDeniedException.class, () -> deviceService.heartbeat("CAM-04"));
        assertThrows(AccessDeniedException.class, () -> deviceService.heartbeat("CAM-05"));
        assertThrows(AccessDeniedException.class, () -> deviceService.heartbeat("missing"));
        verify(deviceMapper, never()).updateById(any(Device.class));
        verifyNoInteractions(deviceCaptureAlertMapper);
    }

    @Test
    void heartbeatWithoutTrustedBusinessIdentityDoesNotLookupDevice() {
        when(businessUsers.authenticated()).thenThrow(new SecurityException("missing business principal"));

        assertThrows(AccessDeniedException.class, () -> deviceService.heartbeat("CAM-03"));
        verifyNoInteractions(deviceMapper, deviceCaptureAlertMapper);
    }

    @Test
    void alertLifecycleCanBeAcknowledgedAndResolved() {
        DeviceCaptureAlert alert = new DeviceCaptureAlert();
        alert.setId(12L);
        alert.setAlertId("ALERT-001");
        alert.setStatus("OPEN");

        DeviceAlertActionRequest ackRequest = new DeviceAlertActionRequest();
        ackRequest.setOperator("payload-impostor-ack");
        ackRequest.setRemark("已通知现场人员");

        when(deviceCaptureAlertMapper.selectById(12L)).thenReturn(alert);
        when(deviceCaptureAlertMapper.updateById(alert)).thenReturn(1);

        authenticate(101L, "qa-leader");
        DeviceCaptureAlert acknowledged = deviceService.acknowledgeAlert(12L, ackRequest);

        assertEquals("ACKNOWLEDGED", acknowledged.getStatus());
        assertEquals("qa-leader", acknowledged.getAckOperator());
        assertEquals("已通知现场人员", acknowledged.getAckRemark());
        assertNotNull(acknowledged.getAcknowledgedAt());
        assertNotNull(acknowledged.getUpdatedAt());
        LocalDateTime acknowledgedAt = acknowledged.getAcknowledgedAt();

        DeviceAlertActionRequest resolveRequest = new DeviceAlertActionRequest();
        resolveRequest.setOperator("payload-impostor-resolve");
        resolveRequest.setRemark("重启相机恢复");

        authenticate(102L, "maintainer");
        DeviceCaptureAlert resolved = deviceService.resolveAlert(12L, resolveRequest);

        assertEquals("RESOLVED", resolved.getStatus());
        assertEquals("maintainer", resolved.getResolvedOperator());
        assertEquals("重启相机恢复", resolved.getResolvedRemark());
        assertNotNull(resolved.getResolvedAt());
        assertNotNull(resolved.getUpdatedAt());
        assertEquals("qa-leader", resolved.getAckOperator());
        assertEquals(acknowledgedAt, resolved.getAcknowledgedAt());
        verify(deviceCaptureAlertMapper, times(2)).updateById(alert);
    }

    @Test
    void unauthenticatedBusinessPrincipalCannotAcknowledgeOrResolveAlerts() {
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(
                new AlertPrincipal(101L, "qa-leader"), null));
        DeviceAlertActionRequest request = new DeviceAlertActionRequest();
        request.setOperator("payload-impostor");

        assertThrows(SecurityException.class, () -> deviceService.acknowledgeAlert(12L, request));
        assertThrows(SecurityException.class, () -> deviceService.resolveAlert(12L, request));

        verifyNoInteractions(deviceCaptureAlertMapper, deviceMapper);
    }

    @Test
    void authenticatedPrincipalWithoutUserIdCannotAcknowledgeOrResolveAlerts() {
        authenticate(null, "qa-leader");
        DeviceAlertActionRequest request = new DeviceAlertActionRequest();
        request.setOperator("payload-impostor");

        assertThrows(SecurityException.class, () -> deviceService.acknowledgeAlert(12L, request));
        assertThrows(SecurityException.class, () -> deviceService.resolveAlert(12L, request));

        verifyNoInteractions(deviceCaptureAlertMapper, deviceMapper);
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
