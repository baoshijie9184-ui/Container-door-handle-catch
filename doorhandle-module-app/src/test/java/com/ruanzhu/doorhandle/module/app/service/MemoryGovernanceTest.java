package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.web.server.ResponseStatusException;
import java.nio.file.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class MemoryGovernanceTest {
    private final TenantContext owner=new TenantContext(42L,"alice"),other=new TenantContext(43L,"bob");
    private JdbcTemplate jdbc;private MemoryPreferenceService settings;private Mem0Client bridge;private PersonalMemoryService service;
    @BeforeEach void setup()throws Exception{
        var data=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");jdbc=new JdbcTemplate(data);
        String ddl=Files.readString(Path.of("src/main/resources/db/migration-V26-personal-memory-governance.sql")).replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin","");for(String statement:ddl.split(";"))if(!statement.isBlank())jdbc.execute(statement);
        settings=new MemoryPreferenceService(jdbc,new DataSourceTransactionManager(data));bridge=mock(Mem0Client.class);service=new PersonalMemoryService(bridge,settings);
    }
    private MemoryDtos.Delete request(String key){return new MemoryDtos.Delete(key,"a".repeat(64),true);}
    @Test void defaultsPreserveExistingPolicyAndOwnerRevisionGuardsConcurrentChanges(){
        assertThat(settings.get(owner)).isEqualTo(new MemoryDtos.Preference(true,true,0,null));
        var saved=settings.change(owner,new MemoryDtos.ChangePreference(0,false,false));assertThat(saved.revision()).isEqualTo(1);
        assertThat(saved.readEnabled()).isFalse();assertThat(settings.get(other).readEnabled()).isTrue();
        assertThatThrownBy(()->settings.change(owner,new MemoryDtos.ChangePreference(0,true,true))).isInstanceOf(ResponseStatusException.class).hasMessageContaining("409");
        assertThat(settings.audit(owner)).hasSize(1);assertThat(settings.audit(other)).isEmpty();
    }
    @Test void deletesOnceAndSuccessfulRequestReplayDoesNotRepeatSideEffect(){
        assertThat(service.delete(owner,"mine",request("request-one")).deleted()).isTrue();
        assertThat(service.delete(owner,"mine",request("request-one")).replayed()).isTrue();verify(bridge,times(1)).deleteOwned(owner,"mine","a".repeat(64));
        assertThat(settings.audit(owner)).singleElement().satisfies(row->assertThat(row.outcome()).isEqualTo("SUCCEEDED"));
        assertThatThrownBy(()->service.delete(owner,"another",request("request-one"))).hasMessageContaining("409");
    }
    @Test void missingConfirmationNeverReservesOrDispatches(){
        assertThatThrownBy(()->service.delete(owner,"mine",new MemoryDtos.Delete("unconfirmed","a".repeat(64),false))).hasMessageContaining("400");verifyNoInteractions(bridge);assertThat(settings.audit(owner)).isEmpty();
    }
    @Test void foreignAndStaleRecordsAreRejectedWithoutFalseSuccess(){
        doThrow(new ResponseStatusException(org.springframework.http.HttpStatus.NOT_FOUND,"不可用")).when(bridge).deleteOwned(any(),any(),any());
        assertThatThrownBy(()->service.delete(owner,"foreign",request("foreign-one"))).hasMessageContaining("404");assertThat(settings.audit(owner)).singleElement().satisfies(row->assertThat(row.outcome()).isEqualTo("REJECTED"));
    }
    @Test void auditFailureBeforeDispatchBlocksRemoteDeletion(){
        jdbc.execute("DROP TABLE agent_memory_audit");assertThatThrownBy(()->service.delete(owner,"mine",request("audit-down"))).isInstanceOf(org.springframework.dao.DataAccessException.class);verifyNoInteractions(bridge);
    }
    @Test void transportFailureIsUnknownAndIsNotAutomaticallyRetried(){
        doThrow(new IllegalStateException("SECRET_BODY")).when(bridge).deleteOwned(any(),any(),any());
        assertThatThrownBy(()->service.delete(owner,"mine",request("timeout"))).hasMessageContaining("503").hasMessageNotContaining("SECRET_BODY");
        assertThat(settings.audit(owner)).singleElement().satisfies(row->assertThat(row.outcome()).isEqualTo("UNKNOWN"));
        assertThatThrownBy(()->service.delete(owner,"mine",request("timeout"))).hasMessageContaining("409");verify(bridge,times(1)).deleteOwned(any(),any(),any());
    }
    @Test void pendingDispatchCannotBeClaimedTwiceAndAuditCompletionFailureIsNotSuccess(){
        assertThat(settings.reserveDelete(owner,"mine",request("claimed"))).isFalse();assertThatThrownBy(()->settings.reserveDelete(owner,"mine",request("claimed"))).hasMessageContaining("409");
        doAnswer(inv->{jdbc.execute("DROP TABLE agent_memory_audit");return null;}).when(bridge).deleteOwned(any(),any(),any());
        assertThatThrownBy(()->service.delete(owner,"mine",request("after-delete"))).isInstanceOf(org.springframework.dao.DataAccessException.class);
    }
    private MemoryDtos.Update edit(String key,String text){return new MemoryDtos.Update(key,"a".repeat(64),text,true);}
    @Test void editIsAuditedDeduplicatedAndBoundToTargetContentAndAction(){
        assertThat(service.update(owner,"mine",edit("edit-once","  本人按月汇总  ")).updated()).isTrue();
        assertThat(service.update(owner,"mine",edit("edit-once","本人按月汇总")).replayed()).isTrue();
        verify(bridge,times(1)).updateOwned(owner,"mine","a".repeat(64),"本人按月汇总");
        assertThatThrownBy(()->service.update(owner,"mine",edit("edit-once","改成另一份内容"))).hasMessageContaining("409");
        assertThatThrownBy(()->service.delete(owner,"mine",request("edit-once"))).hasMessageContaining("409");
        service.delete(owner,"mine",request("delete-first"));
        assertThatThrownBy(()->service.update(owner,"mine",edit("delete-first","本人按月汇总"))).hasMessageContaining("409");
        assertThat(settings.audit(owner)).anySatisfy(row->{assertThat(row.action()).isEqualTo("UPDATE");assertThat(row.outcome()).isEqualTo("SUCCEEDED");});
        assertThat(settings.audit(other)).isEmpty();
        assertThat(jdbc.queryForList("SELECT * FROM agent_memory_audit").toString()).doesNotContain("本人按月汇总","改成另一份内容");
    }
    @Test void unconfirmedBlankAndOversizedEditsCannotReachAuditOrRemoteStore(){
        for(var request:List.of(new MemoryDtos.Update("edit","a".repeat(64),"正文",false),edit("edit","  \n  "),edit("edit","x".repeat(4001))))
            assertThatThrownBy(()->service.update(owner,"mine",request)).hasMessageContaining("400");
        verifyNoInteractions(bridge);assertThat(settings.audit(owner)).isEmpty();
    }
    @Test void editAuditFailureBlocksRemoteWriteAndCompletionFailureIsNotSuccess(){
        doAnswer(inv->{jdbc.execute("DROP TABLE agent_memory_audit");return null;}).when(bridge).updateOwned(any(),any(),any(),any());
        assertThatThrownBy(()->service.update(owner,"mine",edit("completion-failed","新的偏好"))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        clearInvocations(bridge);
        assertThatThrownBy(()->service.update(owner,"mine",edit("audit-down","新的偏好"))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        verifyNoInteractions(bridge);
    }
    @Test void editUnknownOutcomeCannotBeRetriedAndExpectedRejectionsAreAudited(){
        doThrow(new IllegalStateException("SECRET_BODY")).when(bridge).updateOwned(any(),any(),any(),any());
        assertThatThrownBy(()->service.update(owner,"mine",edit("unknown","新的偏好"))).hasMessageContaining("503").hasMessageNotContaining("SECRET_BODY");
        assertThatThrownBy(()->service.update(owner,"mine",edit("unknown","新的偏好"))).hasMessageContaining("409");
        verify(bridge,times(1)).updateOwned(any(),any(),any(),any());
        assertThat(settings.audit(owner)).singleElement().satisfies(row->assertThat(row.outcome()).isEqualTo("UNKNOWN"));
        doThrow(new ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,"版本变化")).when(bridge).updateOwned(any(),any(),any(),any());
        assertThatThrownBy(()->service.update(owner,"mine",edit("stale","新正文"))).hasMessageContaining("409");
        assertThat(settings.audit(owner)).anySatisfy(row->assertThat(row.outcome()).isEqualTo("REJECTED"));
    }
    @Test void pagesAndSingleReadsAlwaysCarryOwnerAndValidateBoundaries(){
        var page=new MemoryDtos.Page(List.of(),true,150);when(bridge.listOwned(owner,50,100)).thenReturn(page);
        assertThat(service.list(owner,50,100)).isSameAs(page);service.get(owner,"mine");verify(bridge).getOwned(owner,"mine");
        for(int offset:new int[]{-1,Integer.MAX_VALUE})assertThatThrownBy(()->service.list(owner,50,offset)).hasMessageContaining("400");
        assertThatThrownBy(()->service.list(owner,101,0)).hasMessageContaining("400");
    }
}
