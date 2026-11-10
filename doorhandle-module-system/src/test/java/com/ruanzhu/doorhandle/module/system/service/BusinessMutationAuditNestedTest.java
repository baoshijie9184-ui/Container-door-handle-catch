package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessMutationParticipant;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.aspectj.lang.ProceedingJoinPoint;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import java.util.List;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class BusinessMutationAuditNestedTest {
    static class Actions { @BusinessMutation(domain="DETECTION",action="KNOWN") public void known(){} @BusinessMutation(domain="DETECTION",action="UNKNOWN") public void unknown(){} }
    BusinessMutationAudit aspect;ProceedingJoinPoint call;BusinessMutationParticipant participant;OperationsAuditApi audit;
    @BeforeEach void setup(){
        var users=mock(BusinessUserDirectory.class);when(users.current(1,"actor")).thenReturn(new BusinessUserDirectory.Identity(1,"actor",false));
        audit=mock(OperationsAuditApi.class);aspect=new BusinessMutationAudit(audit,users,mock(PlatformTransactionManager.class));participant=mock(BusinessMutationParticipant.class);when(participant.supports("DETECTION","KNOWN")).thenReturn(true);aspect.collaboration(mock(JdbcTemplate.class),List.of(participant));
        ReflectionTestUtils.setField(aspect,"mutationProtectionEnabled",true);
        @SuppressWarnings("unchecked") var active=(ThreadLocal<String>)ReflectionTestUtils.getField(aspect,"activeRequest");active.set("outer-request");
        call=mock(ProceedingJoinPoint.class);when(call.getArgs()).thenReturn(new Object[0]);
        var principal=new TenantPrincipal(1L,"actor","",List.of());SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(principal,null,List.of()));
    }
    @AfterEach void close(){@SuppressWarnings("unchecked") var active=(ThreadLocal<String>)ReflectionTestUtils.getField(aspect,"activeRequest");active.remove();SecurityContextHolder.clearContext();}
    @Test void unregisteredNestedMutationCannotBypassStrategyValidation() throws Throwable {
        assertThatThrownBy(()->aspect.invoke(call,Actions.class.getMethod("unknown").getAnnotation(BusinessMutation.class))).isInstanceOf(IllegalStateException.class).hasMessageContaining("UNKNOWN");verify(call,never()).proceed();verifyNoInteractions(audit);
    }
    @Test void registeredNestedMutationExecutesUnderOuterAuditWithoutWritingSecondAudit() throws Throwable {
        when(call.proceed()).thenReturn("saved");assertThat(aspect.invoke(call,Actions.class.getMethod("known").getAnnotation(BusinessMutation.class))).isEqualTo("saved");verify(call).proceed();verifyNoInteractions(audit);
    }
}
