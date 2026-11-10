package com.ruanzhu.doorhandle.module.system.service;

import org.junit.jupiter.api.*;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.*;
import static org.assertj.core.api.Assertions.*;

/** Exact mutation metadata contracts; execute through the existing ECS suite. */
class AuditMetadataTest {
    record Claim(String expectedVersion) { }
    record Model(Long rowVersion,String version) { }
    record Conflicting(Long expectedVersion,Long revision) { }
    @AfterEach void clear(){RequestContextHolder.resetRequestAttributes();}
    @Test void explicitRevisionStringWorksAndModelBusinessVersionIsNeverUsed(){
        assertThat(AuditMetadata.expectedVersion(new Object[]{new Claim("7")})).isEqualTo(7);
        assertThat(AuditMetadata.expectedVersion(new Object[]{new Model(8L,"2026.11")})).isEqualTo(8);
        assertThat(AuditMetadata.expectedVersion(new Object[]{new Model(null,"123")})).isNull();
    }
    @Test void maximumSignedLongWorksInBothHeaderForms(){
        var request=new MockHttpServletRequest();request.addHeader("X-Expected-Version","9223372036854775807");request.addHeader("If-Match","\"9223372036854775807\"");
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        assertThat(AuditMetadata.expectedVersion(new Object[0])).isEqualTo(Long.MAX_VALUE);
    }
    @Test void conflictingFieldsAndHeaderCannotSilentlyChooseOneRevision(){
        assertThatThrownBy(()->AuditMetadata.expectedVersion(new Object[]{new Conflicting(1L,2L)})).isInstanceOf(IllegalArgumentException.class);
        var request=new MockHttpServletRequest();request.addHeader("X-Expected-Version","3");RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        assertThatThrownBy(()->AuditMetadata.expectedVersion(new Object[]{new Claim("2")})).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void nonCanonicalOrOutOfRangeVersionsAreRejected(){
        for(String value:new String[]{"01","1.0","-1","9223372036854775808"})
            assertThatThrownBy(()->AuditMetadata.expectedVersion(new Object[]{new Claim(value)})).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void registeredAccountVersionReadsOnlyItsExactMetadataProperty(){
        var view=new AccountAccessService.View(21,"supervisor",true,"SUPERVISOR",Long.MAX_VALUE);
        assertThat(AuditMetadata.version("result.accountVersion",new Object[0],view)).isEqualTo(Long.MAX_VALUE);
        assertThatThrownBy(()->AuditMetadata.select("result.username",new Object[0],view))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("禁止读取");
        assertThatThrownBy(()->AuditMetadata.select("result.password",new Object[0],view))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("禁止读取");
    }
}
