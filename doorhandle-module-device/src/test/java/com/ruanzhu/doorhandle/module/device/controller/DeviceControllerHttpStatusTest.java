package com.ruanzhu.doorhandle.module.device.controller;

import com.ruanzhu.doorhandle.common.*;
import com.ruanzhu.doorhandle.module.device.service.DeviceService;
import com.ruanzhu.doorhandle.module.system.controller.ResultHttpStatusAdvice;
import com.ruanzhu.doorhandle.module.system.security.AuthorizationExceptionHandler;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.List;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class DeviceControllerHttpStatusTest {
    DeviceService service;
    MockMvc http(boolean enabled,RuntimeException failure){
        service=mock(DeviceService.class);when(service.createDevice(any())).thenThrow(failure);when(service.updateDevice(anyLong(),any())).thenThrow(failure);
        when(service.deleteDevice(anyLong())).thenThrow(failure);when(service.removeEmployeeFromDevice(anyLong())).thenThrow(failure);
        when(service.heartbeat(anyString(),any())).thenThrow(failure);
        var controller=new DeviceController(service);ReflectionTestUtils.setField(controller,"mutationProtectionEnabled",enabled);
        return enabled?MockMvcBuilders.standaloneSetup(controller).setControllerAdvice(new GlobalExceptionHandler(),new AuthorizationExceptionHandler(),new ResultHttpStatusAdvice()).build()
                :MockMvcBuilders.standaloneSetup(controller).setControllerAdvice(new GlobalExceptionHandler(),new AuthorizationExceptionHandler()).build();
    }
    List<MockHttpServletRequestBuilder> writes(){return List.of(post("/api/devices").contentType(MediaType.APPLICATION_JSON).content("{}"),
            put("/api/devices/1").contentType(MediaType.APPLICATION_JSON).content("{}"),delete("/api/devices/1"),delete("/api/devices/1/employee"),
            post("/api/devices/device-one/heartbeat").contentType(MediaType.APPLICATION_JSON).content("{}"));}
    @ParameterizedTest @ValueSource(booleans={true,false})
    void actualDeviceWriteCatchBlocksPreserveConflictsWhenEnabled(boolean enabled)throws Exception{
        var http=http(enabled,new BusinessException(409,"device version changed"));
        for(var write:writes())http.perform(write).andExpect(status().is(enabled?409:200)).andExpect(jsonPath("$.code").value(enabled?409:500));
    }
    @ParameterizedTest @ValueSource(booleans={true,false})
    void unknownDeviceFailureIsNeverHttpSuccessWhenEnabled(boolean enabled)throws Exception{
        var http=http(enabled,new IllegalStateException("unknown result"));for(var write:writes())http.perform(write).andExpect(status().is(enabled?500:200)).andExpect(jsonPath("$.code").value(500));
    }
    @ParameterizedTest @ValueSource(booleans={true,false})
    void permissionExceptionsReachTheExistingAuthorizationHandler(boolean enabled)throws Exception{
        var http=http(enabled,new org.springframework.security.access.AccessDeniedException("permission revoked"));
        http.perform(post("/api/devices").contentType(MediaType.APPLICATION_JSON).content("{}")).andExpect(status().is(enabled?403:200));
    }
}
