package com.ruanzhu.doorhandle.module.app.service.agent.impl;

import com.ruanzhu.doorhandle.module.app.dto.chat.AgentExecutionResult;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.app.service.DeepSeekClient;
import com.ruanzhu.doorhandle.module.device.service.DeviceService;
import com.ruanzhu.doorhandle.module.device.service.EmployeeService;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class ResourceAgentServiceImplTest {

    @Test
    void fallbackDeviceAnswerIncludesSystemDataSource() {
        DeviceService deviceService = mock(DeviceService.class);
        EmployeeService employeeService = mock(EmployeeService.class);
        ModelService modelService = mock(ModelService.class);
        DeepSeekClient deepSeekClient = mock(DeepSeekClient.class);

        Device device = new Device();
        device.setDeviceCode("CAM-01");
        device.setStatus("ACTIVE");
        device.setOnlineStatus("ONLINE");
        device.setCaptureStatus("IDLE");

        when(deviceService.getAllDevices()).thenReturn(List.of(device));
        when(deepSeekClient.generateResourceResponse(anyString(), anyString()))
                .thenThrow(new RuntimeException("llm unavailable"));

        ResourceAgentServiceImpl service = new ResourceAgentServiceImpl(
                deviceService,
                employeeService,
                modelService,
                deepSeekClient
        );

        AgentExecutionResult result = service.answer("查看当前设备在线状态", "tester");

        assertThat(result.getContent()).contains("CAM-01", "来源：系统数据");
    }
}
