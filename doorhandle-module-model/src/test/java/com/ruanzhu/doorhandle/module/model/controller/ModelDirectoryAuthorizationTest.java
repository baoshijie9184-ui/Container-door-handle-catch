package com.ruanzhu.doorhandle.module.model.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.entity.ModelOperationLog;
import com.ruanzhu.doorhandle.module.model.service.ModelInfoService;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;

import java.lang.reflect.InvocationTargetException;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ModelDirectoryAuthorizationTest {
    private AnnotationConfigApplicationContext context;

    @Configuration
    @EnableMethodSecurity
    @Import({ModelInfoController.class, ModelController.class})
    static class Config {
        @Bean ModelInfoService modelInfo() { return mock(ModelInfoService.class); }
        @Bean ModelService models() { return mock(ModelService.class); }
    }

    @BeforeEach void start() { context = new AnnotationConfigApplicationContext(Config.class); }

    @AfterEach void stop() {
        SecurityContextHolder.clearContext();
        context.close();
    }

    private void login(String role) {
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(
                "account", null, List.of(new SimpleGrantedAuthority(role))));
    }

    @Test void legacyMetadataWritesRequireSupervisorWithoutAuditInfrastructure() {
        login("ROLE_INSPECTOR");
        var controller = context.getBean(ModelInfoController.class);
        int checked = 0;
        for (var method : ModelInfoController.class.getDeclaredMethods()) {
            if (!method.isAnnotationPresent(PostMapping.class) && !method.isAnnotationPresent(PutMapping.class)
                    && !method.isAnnotationPresent(DeleteMapping.class)) continue;
            var error = assertThrows(InvocationTargetException.class,
                    () -> method.invoke(controller, new Object[method.getParameterCount()]), method.getName());
            assertInstanceOf(AccessDeniedException.class, error.getCause(), method.getName());
            checked++;
        }
        assertEquals(6, checked);
        var info = context.getBean(ModelInfoService.class);
        verifyNoInteractions(info, context.getBean(ModelService.class));

        login("ROLE_SUPERVISOR");
        var model = new ModelInfo();
        when(info.saveModelInfo(model)).thenReturn(true);
        controller.saveModelInfo(model);
        verify(info).saveModelInfo(model);
    }

    @Test void employeeModelDirectoryRetainsModelInformationWithoutCachedStoragePath() {
        var model = new ModelInfo();
        model.setModelId(7);
        model.setModelName("Detection model");
        model.setModelPath("/private/models/model.onnx");
        var info = context.getBean(ModelInfoService.class);
        when(info.getModelInfoByModelId(7)).thenReturn(model);
        when(info.getModelInfoPage(1,10,null,null,null,null))
                .thenReturn(new Page<ModelInfo>(1,10,1).setRecords(List.of(model)));
        when(context.getBean(ModelService.class).getAllModels()).thenReturn(List.of(model));
        var modern = context.getBean(ModelController.class);
        var legacy = context.getBean(ModelInfoController.class);

        login("ROLE_INSPECTOR");
        assertNull(modern.getAllModels().getData().get(0).getModelPath());
        assertNull(legacy.getModelInfoById(7).getData().getModelPath());
        var page = legacy.getModelInfoPage(1,10,null,null,null,null).getData();
        assertNull(page.getRecords().get(0).getModelPath());
        assertEquals("Detection model", page.getRecords().get(0).getModelName());
        assertEquals(1, page.getTotal());

        login("ROLE_SUPERVISOR");
        assertEquals("/private/models/model.onnx", modern.getAllModels().getData().get(0).getModelPath());
    }

    @Test void modelOperationLogsRequireSupervisor() {
        var controller = context.getBean(ModelController.class);
        var models = context.getBean(ModelService.class);
        login("ROLE_INSPECTOR");
        assertThrows(AccessDeniedException.class, () -> controller.getModelOperations(7));
        verifyNoInteractions(models);

        login("ROLE_SUPERVISOR");
        var operation = new ModelOperationLog();
        when(models.getOperationLogs(7)).thenReturn(List.of(operation));
        assertEquals(List.of(operation), controller.getModelOperations(7).getData());
    }
}
