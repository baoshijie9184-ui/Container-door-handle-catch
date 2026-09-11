package com.ruanzhu.doorhandle.module.device.controller;

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
import java.lang.reflect.InvocationTargetException;
import java.util.List;
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
                if (!method.isAnnotationPresent(PreAuthorize.class)) continue;
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
}
