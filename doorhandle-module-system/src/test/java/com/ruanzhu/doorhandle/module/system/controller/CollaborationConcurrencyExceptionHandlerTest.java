package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.common.GlobalExceptionHandler;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.dao.*;
import org.springframework.http.ResponseEntity;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.*;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** Source-level HTTP contracts; execute with the existing ECS test suite. */
class CollaborationConcurrencyExceptionHandlerTest {
    @RestController static class Conflicts {
        final AtomicInteger attempts=new AtomicInteger();
        @GetMapping("/lock") String locked(){attempts.incrementAndGet();throw new CannotAcquireLockException("private-table sql and connection details");}
        @GetMapping("/optimistic") String optimistic(){throw new OptimisticLockingFailureException("private row revision");}
        @GetMapping("/constraint") String constraint(){throw new DataIntegrityViolationException("private constraint");}
        @GetMapping("/resource-denied") String resourceDenied(){throw new SecurityException("private resource existence and field policy");}
        @GetMapping("/spring-denied") String springDenied(){throw new org.springframework.security.access.AccessDeniedException("private authorization rule");}
        @GetMapping("/context") String context(){throw new AccountSwitch();}
        @ExceptionHandler(AccountSwitch.class) ResponseEntity<?> contextChanged(){return ResponseEntity.status(409).body(Map.of("code","ACCOUNT_CONTEXT_CHANGED","message","账号已变化"));}
    }
    static class AccountSwitch extends RuntimeException { }
    @Test void lockFailureReturnsAConflictWithoutRetryingOrExposingDatabaseDetails() throws Exception {
        var controller=new Conflicts();var http=MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler(),new CollaborationConcurrencyExceptionHandler()).build();
        var response=http.perform(get("/lock")).andExpect(status().isConflict())
                .andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.code").value("CONCURRENT_WRITE"))
                .andExpect(jsonPath("$.message").value("并发修改未完成，请保留草稿并核对最新资料后重试")).andReturn();
        assertThat(controller.attempts).hasValue(1);assertThat(response.getResponse().getContentAsString()).doesNotContain("private-table","connection details");
    }
    @Test void optimisticConflictUsesTheSameCodeAndAccountContextKeepsItsOwnCode() throws Exception {
        var http=MockMvcBuilders.standaloneSetup(new Conflicts())
                .setControllerAdvice(new GlobalExceptionHandler(),new CollaborationConcurrencyExceptionHandler()).build();
        http.perform(get("/optimistic")).andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("CONCURRENT_WRITE"));
        http.perform(get("/context")).andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("ACCOUNT_CONTEXT_CHANGED"));
    }
    @Test void unrelatedPersistenceFailuresKeepTheirExistingErrorContract() throws Exception {
        var http=MockMvcBuilders.standaloneSetup(new Conflicts())
                .setControllerAdvice(new GlobalExceptionHandler(),new CollaborationConcurrencyExceptionHandler()).build();
        http.perform(get("/constraint")).andExpect(status().isOk()).andExpect(jsonPath("$.code").value(500));
    }
    @Test void resourceSecurityDenialIsARealForbiddenResponseWithoutResourceDetails() throws Exception {
        var http=MockMvcBuilders.standaloneSetup(new Conflicts())
                .setControllerAdvice(new GlobalExceptionHandler(),new CollaborationConcurrencyExceptionHandler()).build();
        var response=http.perform(get("/resource-denied")).andExpect(status().isForbidden())
                .andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.code").value(403))
                .andExpect(jsonPath("$.message").value("当前账号没有此操作权限")).andReturn();
        assertThat(response.getResponse().getContentAsString()).doesNotContain("private resource","field policy","SecurityException");
    }
    @Test void springAccessDenialKeepsTheGenericForbiddenContract() throws Exception {
        var http=MockMvcBuilders.standaloneSetup(new Conflicts())
                .setControllerAdvice(new GlobalExceptionHandler(),new CollaborationConcurrencyExceptionHandler()).build();
        var response=http.perform(get("/spring-denied")).andExpect(status().isForbidden()).andExpect(jsonPath("$.code").value(403)).andReturn();
        assertThat(response.getResponse().getContentAsString()).doesNotContain("private authorization","AccessDeniedException");
    }
    @Test void handlerIsOnlyRegisteredWhenMutationProtectionIsEnabled(){
        var context=new ApplicationContextRunner().withUserConfiguration(CollaborationConcurrencyExceptionHandler.class);
        context.run(result->assertThat(result).doesNotHaveBean(CollaborationConcurrencyExceptionHandler.class));
        context.withPropertyValues("collaboration.mutations.enabled=false").run(result->assertThat(result).doesNotHaveBean(CollaborationConcurrencyExceptionHandler.class));
        context.withPropertyValues("collaboration.mutations.enabled=true").run(result->assertThat(result).hasSingleBean(CollaborationConcurrencyExceptionHandler.class));
    }
}
