package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.contracts.files.LocalDetectionFilesApi.Kind;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessPrincipal;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;
import java.nio.file.Path;
import java.util.List;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class LocalDetectionFileAuthorizationServiceTest {
    @TempDir Path directory;
    DetectionTaskMapper mapper=mock(DetectionTaskMapper.class);
    BusinessUserDirectory users=mock(BusinessUserDirectory.class);
    DetectionTaskAccessPolicy policy=new DetectionTaskAccessPolicy();
    LocalDetectionFileAuthorizationService service=new LocalDetectionFileAuthorizationService(mapper,policy,users);
    record Principal(Long userId,String username) implements BusinessPrincipal,java.security.Principal {
        @Override public String getName(){return username;}
    }
    @BeforeEach void setup() throws java.io.IOException {
        for(String folder:List.of("images","annotated","results"))java.nio.file.Files.createDirectories(directory.resolve(folder));
        policy.setUsers(users);
        var actor=new BusinessUserDirectory.Identity(7L,"alice",false);
        when(users.authenticated()).thenReturn(actor);
        when(users.current(7L,"alice")).thenReturn(actor);
        ReflectionTestUtils.setField(service,"images",directory.resolve("images").toString());
        ReflectionTestUtils.setField(service,"annotated",directory.resolve("annotated").toString());
        ReflectionTestUtils.setField(service,"results",directory.resolve("results").toString());
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(new Principal(7L,"alice"),"n/a",List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"))));
    }
    @AfterEach void clear() { SecurityContextHolder.clearContext(); }
    @Test void ownedAndAssignedTaskFilesAreAuthorizedButUnrelatedFoldersAreNot() {
        var task=new DetectionTask();task.setCreatedBy("bob");task.setAssignee("alice");
        task.setTaskId("local-file-task-a");
        task.setSourceOssPrefix(directory.resolve("images/task-a").toString());
        task.setResultOssPrefix(directory.resolve("results/task-a/result.json").toString());
        when(mapper.selectList(any())).thenReturn(List.of(task));
        service.authorize(Kind.IMAGE,directory.resolve("images/task-a/image.jpg"));
        service.authorize(Kind.ANNOTATED,directory.resolve("annotated/task-a/image.jpg"));
        service.authorize(Kind.RESULT,directory.resolve("results/task-a/result.json"));
        assertThatThrownBy(()->service.authorize(Kind.IMAGE,directory.resolve("images/task-ab/image.jpg")))
                .isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
        task.setAssignee("charlie");
        assertThatThrownBy(()->service.authorize(Kind.IMAGE,directory.resolve("images/task-a/image.jpg")))
                .isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
    }
    @Test void ossPrefixOrEntireBaseDirectoryDoesNotGrantLocalFileAccess() {
        var task=new DetectionTask();task.setCreatedBy("alice");task.setSourceOssPrefix("detection/oss/task-a");
        when(mapper.selectList(any())).thenReturn(List.of(task));
        assertThatThrownBy(()->service.authorize(Kind.IMAGE,directory.resolve("images/task-a/a.jpg")))
                .isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
        task.setSourceOssPrefix(directory.resolve("images").toString());
        assertThatThrownBy(()->service.authorize(Kind.IMAGE,directory.resolve("images/task-a/a.jpg")))
                .isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
    }
}
