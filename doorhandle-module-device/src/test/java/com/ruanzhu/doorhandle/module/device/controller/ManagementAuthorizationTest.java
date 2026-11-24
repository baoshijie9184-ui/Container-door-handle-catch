package com.ruanzhu.doorhandle.module.device.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceUsageRecord;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import com.ruanzhu.doorhandle.module.device.service.*;
import org.junit.jupiter.api.*;
import org.springframework.context.annotation.*;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.web.bind.annotation.GetMapping;
import java.lang.reflect.InvocationTargetException;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ManagementAuthorizationTest {
    private AnnotationConfigApplicationContext context;

    @Configuration
    @EnableMethodSecurity
    @Import({DeviceController.class, DeviceUsageRecordController.class, EmployeeController.class})
    static class Config {
        @Bean DeviceService devices() { return mock(DeviceService.class); }
        @Bean EmployeeService employees() { return mock(EmployeeService.class); }
        @Bean DeviceUsageRecordService records() { return mock(DeviceUsageRecordService.class); }
        @Bean DeviceMapper mapper() { return mock(DeviceMapper.class); }
    }

    @BeforeEach void start() { context = new AnnotationConfigApplicationContext(Config.class); }
    @AfterEach void stop() { SecurityContextHolder.clearContext(); context.close(); }

    private void login(String role) {
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(
                "test-user", "unused", List.of(new SimpleGrantedAuthority(role))));
    }

    @Test void inspectorCannotInvokeAnyProtectedManagementWrite() {
        login("ROLE_INSPECTOR");
        int checked = 0;
        for (Class<?> type : List.of(DeviceController.class, DeviceUsageRecordController.class, EmployeeController.class)) {
            Object controller = context.getBean(type);
            for (var method : type.getDeclaredMethods()) {
                if (!method.isAnnotationPresent(PreAuthorize.class) || method.isAnnotationPresent(GetMapping.class)) continue;
                var failure = assertThrows(InvocationTargetException.class,
                        () -> method.invoke(controller, new Object[method.getParameterCount()]), method.getName());
                assertInstanceOf(AccessDeniedException.class, failure.getCause(), method.getName());
                checked++;
            }
        }
        assertEquals(13, checked);
        verifyNoInteractions(context.getBean(DeviceService.class), context.getBean(EmployeeService.class),
                context.getBean(DeviceUsageRecordService.class), context.getBean(DeviceMapper.class));
    }

    @Test void supervisorCanReachManagementServices() {
        login("ROLE_SUPERVISOR");
        context.getBean(DeviceController.class).deleteDevice(1L);
        context.getBean(EmployeeController.class).delete(2L);
        context.getBean(DeviceUsageRecordController.class).deleteDeviceUsageRecord(3L);
        verify(context.getBean(DeviceService.class)).deleteDevice(1L);
        verify(context.getBean(EmployeeService.class)).delete(2L);
        verify(context.getBean(DeviceUsageRecordService.class)).deleteDeviceUsageRecord(3L);
    }

    @Test void inspectorRetainsReadAccess() {
        login("ROLE_INSPECTOR");
        context.getBean(DeviceController.class).getDeviceById(1L);
        context.getBean(EmployeeController.class).getById(2L);
        verify(context.getBean(DeviceService.class)).getDeviceById(1L);
        verify(context.getBean(EmployeeService.class)).getById(2L);
    }

    @Test void captureAlertsRequireSupervisor() {
        var controller = context.getBean(DeviceController.class);
        var devices = context.getBean(DeviceService.class);
        login("ROLE_INSPECTOR");
        assertThrows(AccessDeniedException.class, () -> controller.listCaptureAlerts("OPEN", null, null, 1, 20));
        verifyNoInteractions(devices);

        login("ROLE_SUPERVISOR");
        when(devices.listCaptureAlerts("OPEN", null, null, 1, 20)).thenReturn(Map.of("total", 1));
        assertEquals(1, controller.listCaptureAlerts("OPEN", null, null, 1, 20).getData().get("total"));
    }

    @Test void contactDetailsAreRestrictedWithoutMutatingDirectoryOrHistoryRecords() {
        var employee = new Employee();
        employee.setId(2L);
        employee.setEmployeeNumber("DET-0002");
        employee.setContact("private-contact");
        var device = new Device();
        device.setEmployee(employee);
        var usage = new DeviceUsageRecord();
        usage.setEmployeeNumber(employee.getEmployeeNumber());
        usage.setContact(employee.getContact());
        var people = context.getBean(EmployeeController.class);
        var devices = context.getBean(DeviceController.class);
        var records = context.getBean(DeviceUsageRecordController.class);
        var employeeService = context.getBean(EmployeeService.class);
        when(employeeService.getById(2L)).thenReturn(employee);
        when(employeeService.findByPage(1,10,null,null,null,null,null,null))
                .thenReturn(new Page<Employee>(1,10,1).setRecords(List.of(employee)));
        when(context.getBean(DeviceService.class).getDeviceById(1L)).thenReturn(device);
        when(context.getBean(DeviceUsageRecordService.class).getDeviceUsageRecordsByDeviceId(1L)).thenReturn(List.of(usage));

        login("ROLE_INSPECTOR");
        assertThrows(AccessDeniedException.class, () -> people.findByPage(1,10,null,null,"private-contact",null,null,null));
        assertNull(people.findByPage(1,10,null,null,null,null,null,null).getData().getRecords().get(0).getContact());
        assertEquals("DET-0002", people.getById(2L).getData().getEmployeeNumber());
        assertNull(people.getById(2L).getData().getContact());
        assertNull(devices.getDeviceById(1L).getData().getEmployee().getContact());
        assertNull(devices.getDeviceEmployee(1L).getData().getContact());
        assertNull(usageRecord(records).getContact());

        login("ROLE_SUPERVISOR");
        assertEquals("private-contact", people.getById(2L).getData().getContact());
        assertEquals("private-contact", devices.getDeviceById(1L).getData().getEmployee().getContact());
        assertEquals("private-contact", usageRecord(records).getContact());
    }

    @Test void employeeDeviceReadsAndHeartbeatExcludeCaptureInternalsFromEveryResponse() {
        var employee = new Employee();
        employee.setId(2L);
        employee.setName("采集员");
        employee.setEmployeeNumber("DET-0002");
        employee.setEmployeeType("COLLECTOR");
        employee.setContact("private-contact");
        var assigned = registeredDevice(1L);
        assigned.setEmployeeId(employee.getId());
        assigned.setEmployee(employee);
        var unassigned = registeredDevice(3L);

        var devices = context.getBean(DeviceController.class);
        var people = context.getBean(EmployeeController.class);
        var deviceService = context.getBean(DeviceService.class);
        when(deviceService.getDeviceById(1L)).thenReturn(assigned);
        when(deviceService.getDevicesByPage(null, null, null, null, null, 1, 10))
                .thenReturn(Map.of("records", List.of(assigned), "total", 1L, "page", 1L, "size", 10L));
        when(deviceService.getUnassignedDevices()).thenReturn(List.of(unassigned));
        when(deviceService.heartbeat(assigned.getDeviceCode(), null)).thenReturn(assigned);
        when(context.getBean(EmployeeService.class).getDevicesByEmployeeId(2L)).thenReturn(List.of(assigned));

        login("ROLE_INSPECTOR");
        var mapper = new ObjectMapper().findAndRegisterModules().setSerializationInclusion(JsonInclude.Include.NON_NULL);
        for (var row : readAssignedDeviceResponses(devices, people)) {
            assertDeviceDirectoryFields(mapper, row, assigned);
            assertEquals(2L, row.getEmployee().getId());
            assertEquals("采集员", row.getEmployee().getName());
            assertEquals("DET-0002", row.getEmployee().getEmployeeNumber());
            assertEquals("COLLECTOR", row.getEmployee().getEmployeeType());
            assertFalse(mapper.valueToTree(row).path("employee").has("contact"));
        }
        var unassignedResponse = devices.getUnassignedDevices().getData().get(0);
        assertDeviceDirectoryFields(mapper, unassignedResponse, unassigned);
        assertNull(unassignedResponse.getEmployee());

        login("ROLE_SUPERVISOR");
        for (var row : readAssignedDeviceResponses(devices, people)) {
            assertSame(assigned, row);
            assertEquals("private-contact", row.getEmployee().getContact());
            assertEquals("edge-node", row.getEdgeNodeId());
            assertEquals("capture/original.jpg", row.getLastImageKey());
            assertEquals("{\"internal\":true}", row.getRuntimeMetadataJson());
        }
        assertSame(unassigned, devices.getUnassignedDevices().getData().get(0));
    }

    private static Device registeredDevice(long id) {
        var device = new Device();
        device.setId(id);
        device.setVersion(5);
        device.setDeviceCode("CAPTURE-" + id);
        device.setDeviceType("IMAGE_CAPTURE");
        device.setModelName("camera-model");
        device.setSerialNumber("serial-" + id);
        device.setStatus("IN_USE");
        device.setOnlineStatus("ONLINE");
        device.setLastHeartbeatAt(LocalDateTime.of(2026, 1, 2, 3, 4));
        device.setLastMaintenanceDate(LocalDateTime.of(2026, 1, 1, 8, 0));
        device.setCreatedTime(LocalDateTime.of(2025, 12, 1, 8, 0));
        device.setUpdatedTime(device.getLastHeartbeatAt());
        device.setStationCode("internal-station");
        device.setEdgeNodeId("edge-node");
        device.setLastImageKey("capture/original.jpg");
        device.setRuntimeMetadataJson("{\"internal\":true}");
        device.setPlcStatus("RUNNING");
        device.setCameraStatus("READY");
        device.setCaptureStatus("CAPTURING");
        device.setLastCaptureAt(device.getLastHeartbeatAt());
        return device;
    }

    private List<Device> readAssignedDeviceResponses(DeviceController devices, EmployeeController people) {
        var page = devices.getAllDevices(null, null, null, null, null, 1, 10).getData();
        assertEquals(1L, page.get("total"));
        var listed = (List<?>) page.get("records");
        return List.of((Device) listed.get(0), devices.getDeviceById(1L).getData(),
                people.getDevicesByEmployeeId(2L).getData().get(0), devices.heartbeat("CAPTURE-1", null).getData());
    }

    private static void assertDeviceDirectoryFields(ObjectMapper mapper, Device row, Device original) {
        assertEquals(original.getId(), row.getId());
        assertEquals(original.getVersion(), row.getVersion());
        assertEquals(original.getDeviceCode(), row.getDeviceCode());
        assertEquals(original.getDeviceType(), row.getDeviceType());
        assertEquals(original.getModelName(), row.getModelName());
        assertEquals(original.getSerialNumber(), row.getSerialNumber());
        assertEquals(original.getOnlineStatus(), row.getOnlineStatus());
        assertEquals(original.getStatus(), row.getStatus());
        assertEquals(original.getLastMaintenanceDate(), row.getLastMaintenanceDate());
        assertEquals(original.getLastHeartbeatAt(), row.getLastHeartbeatAt());
        assertEquals(original.getCreatedTime(), row.getCreatedTime());
        assertEquals(original.getUpdatedTime(), row.getUpdatedTime());
        var json = mapper.valueToTree(row);
        for (var field : List.of("stationCode", "edgeNodeId", "lastImageKey", "runtimeMetadataJson",
                "plcStatus", "cameraStatus", "captureStatus", "lastCaptureAt")) {
            assertFalse(json.has(field), field);
        }
    }

    private DeviceUsageRecord usageRecord(DeviceUsageRecordController controller) {
        return (DeviceUsageRecord) ((List<?>) controller.getDeviceUsageRecordsByDeviceId(1L).getData()).get(0);
    }
}
