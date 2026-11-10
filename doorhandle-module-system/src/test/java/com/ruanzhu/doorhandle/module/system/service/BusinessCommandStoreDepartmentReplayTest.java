package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.organization.OrganizationDirectoryApi.DepartmentIdentity;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** ECS source codec regressions; command identity/digest validation remains in the owning aspect. */
class BusinessCommandStoreDepartmentReplayTest {
    private record OtherReply(Long id,String name,Long revision) { }
    private final JdbcTemplate jdbc=mock(JdbcTemplate.class);
    private final BusinessCommandStore commands=new BusinessCommandStore(jdbc);
    private BusinessCommandStore.Claim stored(String result){
        return new BusinessCommandStore.Claim("codec-only",true,"{\"result\":"+result+
                ",\"receipt\":{\"resourceVersion\":\"9\",\"auditId\":\"81\",\"eventId\":\"original-event\"}}");
    }
    @AfterEach void clear(){RequestContextHolder.resetRequestAttributes();}
    @Test void oldDepartmentReplyKeepsUnknownRevisionAndItsOriginalReceiptWithoutAnyRead(){
        var response=new MockHttpServletResponse();
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(new MockHttpServletRequest(),response));
        var replay=(DepartmentIdentity)commands.replay(stored("{\"id\":21,\"name\":\"Original Department\"}"),DepartmentIdentity.class);
        assertThat(replay).isEqualTo(new DepartmentIdentity(21L,"Original Department"));assertThat(replay.version()).isNull();
        assertThat(response.getHeader("X-Resource-Version")).isEqualTo("9");
        assertThat(response.getHeader("X-Audit-ID")).isEqualTo("81");assertThat(response.getHeader("X-Change-Event-ID")).isEqualTo("original-event");
        verifyNoInteractions(jdbc);
    }
    @Test void departmentCompatibilityNeverAcceptsUnknownFieldsOrWeakensOtherRequiredCreators(){
        for(String result:new String[]{"{\"id\":21,\"name\":\"Original\",\"unexpected\":true}",
                "{\"id\":21,\"name\":\"Original\",\"version\":1,\"unexpected\":true}"})
            assertThatThrownBy(()->commands.replay(stored(result),DepartmentIdentity.class)).isInstanceOf(IllegalStateException.class).hasMessage("命令回执解码失败");
        assertThatThrownBy(()->commands.replay(stored("{\"id\":21,\"name\":\"Other\"}"),OtherReply.class))
                .isInstanceOf(IllegalStateException.class).hasMessage("命令回执解码失败");
        verifyNoInteractions(jdbc);
    }
    @Test void newDepartmentReplyRetainsItsOwnExactPersistedRevision(){
        var replay=(DepartmentIdentity)commands.replay(stored("{\"id\":21,\"name\":\"Original\",\"version\":9223372036854775807}"),DepartmentIdentity.class);
        assertThat(replay.version()).isEqualTo(Long.MAX_VALUE);verifyNoInteractions(jdbc);
    }
}
