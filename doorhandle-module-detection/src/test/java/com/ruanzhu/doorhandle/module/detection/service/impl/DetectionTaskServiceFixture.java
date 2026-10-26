package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.infra.config.properties.OssProperties;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskDispatchService;
import com.ruanzhu.doorhandle.module.detection.service.DetectionNotificationPort;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import org.mockito.Mockito;
import org.mockito.MockitoSession;
import org.mockito.quality.Strictness;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

final class DetectionTaskServiceFixture {

    private final MockitoSession mockitoSession;
    final DetectionTaskMapper detectionTaskMapper;
    final ModelInfoMapper modelInfoMapper;
    final ModelService modelService;
    final OssStorageService ossStorageService;
    final DetectionTaskDispatchService detectionTaskDispatchService;
    final DetectionNotificationPort detectionNotificationPort;

    DetectionTaskServiceImpl service;

    DetectionTaskServiceFixture() {
        mockitoSession = Mockito.mockitoSession()
                .strictness(Strictness.STRICT_STUBS)
                .startMocking();
        detectionTaskMapper = Mockito.mock(DetectionTaskMapper.class);
        modelInfoMapper = Mockito.mock(ModelInfoMapper.class);
        modelService = Mockito.mock(ModelService.class);
        ossStorageService = Mockito.mock(OssStorageService.class);
        detectionTaskDispatchService = Mockito.mock(DetectionTaskDispatchService.class);
        detectionNotificationPort = Mockito.mock(DetectionNotificationPort.class);
    }

    void setUp() {
        SecurityContextHolder.clearContext();
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken("admin", "N/A",
                        List.of(new SimpleGrantedAuthority("ROLE_ADMIN")))
        );

        OssProperties ossProperties = new OssProperties();
        ossProperties.setUploadUrlExpireMinutes(15);
        ossProperties.setPreviewUrlExpireMinutes(30);
        ossProperties.setBasePrefix("detection");

        service = new DetectionTaskServiceImpl(
                detectionTaskMapper,
                modelInfoMapper,
                modelService,
                ossStorageService,
                ossProperties,
                detectionTaskDispatchService,
                detectionNotificationPort,
                new ObjectMapper(),
                new DetectionTaskAccessPolicy()
        );
        ReflectionTestUtils.setField(service, "maxImagesPerBatch", 200);
        ReflectionTestUtils.setField(service, "maxImageBytes", 10L * 1024L * 1024L);
        var assignmentUsers = Mockito.mock(com.ruanzhu.doorhandle.contracts.agent.AgentUserDirectory.class);
        var actors = Mockito.mock(com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.class);
        Mockito.lenient().when(actors.authenticated()).thenReturn(
                new com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity(1,"admin",true));
        Mockito.lenient().when(assignmentUsers.inspector("qa-user")).thenReturn(
                new com.ruanzhu.doorhandle.contracts.agent.AgentUserDirectory.Inspector(2,"qa-user","a".repeat(64)));
        service.setAssignmentDirectory(assignmentUsers, actors);
    }

    void tearDown() {
        try {
            mockitoSession.finishMocking();
        } finally {
            SecurityContextHolder.clearContext();
        }
    }
}
