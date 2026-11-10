package com.ruanzhu.doorhandle.module.model.controller;

import com.ruanzhu.doorhandle.common.*;
import com.ruanzhu.doorhandle.module.model.service.*;
import com.ruanzhu.doorhandle.module.system.controller.ResultHttpStatusAdvice;
import com.ruanzhu.doorhandle.module.system.security.AuthorizationExceptionHandler;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class ModelControllerHttpStatusTest {
    MockMvc http(boolean enabled,RuntimeException failure){
        var service=mock(ModelService.class);when(service.uploadModel(any(),anyString(),anyString(),any())).thenThrow(failure);
        when(service.updateModel(any())).thenThrow(failure);when(service.publishModel(anyInt())).thenThrow(failure);when(service.setDefaultModel(anyInt())).thenThrow(failure);
        when(service.disableModel(anyInt())).thenThrow(failure);when(service.archiveModel(anyInt())).thenThrow(failure);when(service.validateModel(anyInt())).thenThrow(failure);doThrow(failure).when(service).deleteModel(anyInt());
        @SuppressWarnings("unchecked") var provider=(org.springframework.beans.factory.ObjectProvider<ModelFileJournal>)mock(org.springframework.beans.factory.ObjectProvider.class);
        var controller=new ModelController(service,provider);ReflectionTestUtils.setField(controller,"mutationProtectionEnabled",enabled);
        return enabled?MockMvcBuilders.standaloneSetup(controller).setControllerAdvice(new GlobalExceptionHandler(),new AuthorizationExceptionHandler(),new ResultHttpStatusAdvice()).build()
                :MockMvcBuilders.standaloneSetup(controller).setControllerAdvice(new GlobalExceptionHandler(),new AuthorizationExceptionHandler()).build();
    }
    List<MockHttpServletRequestBuilder> writes(){
        var writes=new ArrayList<MockHttpServletRequestBuilder>();writes.add(put("/api/models").contentType(MediaType.APPLICATION_JSON).content("{\"modelId\":1,\"modelName\":\"fixture\",\"version\":\"v1\"}"));
        for(String action:List.of("publish","set-default","disable","archive","validate"))writes.add(post("/api/models/1/"+action));
        writes.add(delete("/api/models/1"));writes.add(multipart("/api/models/upload").file(new MockMultipartFile("file","model.onnx","application/octet-stream",new byte[]{1})).param("modelName","fixture").param("version","v1").param("updateDescription","description"));return writes;
    }
    @ParameterizedTest @ValueSource(booleans={true,false})
    void actualModelWriteCatchBlocksPreserveConflictsWhenEnabled(boolean enabled)throws Exception{
        var http=http(enabled,new BusinessException(409,"model version changed"));for(var write:writes())http.perform(write).andExpect(status().is(enabled?409:200)).andExpect(jsonPath("$.code").value(enabled?409:500));
    }
    @ParameterizedTest @ValueSource(booleans={true,false})
    void unknownModelFailureIsNeverHttpSuccessWhenEnabled(boolean enabled)throws Exception{
        var http=http(enabled,new IllegalStateException("unknown result"));for(var write:writes())http.perform(write).andExpect(status().is(enabled?500:200)).andExpect(jsonPath("$.code").value(500));
    }
    @ParameterizedTest @ValueSource(booleans={true,false})
    void permissionExceptionsReachTheExistingAuthorizationHandler(boolean enabled)throws Exception{
        var http=http(enabled,new org.springframework.security.access.AccessDeniedException("permission revoked"));http.perform(post("/api/models/1/publish")).andExpect(status().is(enabled?403:200));
    }
}
