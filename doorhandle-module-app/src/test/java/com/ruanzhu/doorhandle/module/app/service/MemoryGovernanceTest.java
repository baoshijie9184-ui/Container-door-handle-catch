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
    private MemoryDtos.Review reviewResult(int revision,MemoryDtos.ReviewDecision... decisions){return new MemoryDtos.Review("review","mine","READY",revision,null,true,"COMPLETE",List.of(),List.of(decisions),null,null,20,true,"fixture",10L,null,null,null,"UNKNOWN");}
    private MemoryDtos.ResolveReview resolve(String key,String choice){return new MemoryDtos.ResolveReview(key,1,"candidate",choice,true);}
    @Test void semanticReviewRespectsReadPreferenceAndRejectsUnconfirmedDecisions(){
        settings.change(owner,new MemoryDtos.ChangePreference(0,false,true));
        assertThatThrownBy(()->service.startReview(owner,"mine",new MemoryDtos.StartReview("read","a".repeat(64),0))).hasMessageContaining("403");
        assertThatThrownBy(()->service.resolveReview(owner,"review",new MemoryDtos.ResolveReview("no",1,"candidate","KEEP_SOURCE",false))).hasMessageContaining("400");
        verifyNoInteractions(bridge);assertThat(settings.audit(owner)).hasSize(1);
    }
    @Test void reviewDecisionIsAuditedAndSuccessfulReplayDoesNotWriteAgain(){
        var proof=new MemoryDtos.ReviewDecision("decision","candidate","KEEP_SOURCE",1,"2026-10-18T14:00:00+08:00");var completed=reviewResult(2,proof);
        when(bridge.getReview(owner,"review")).thenReturn(reviewResult(1));when(bridge.resolveReview(owner,"review",resolve("decision","KEEP_SOURCE"))).thenReturn(completed);
        assertThat(service.resolveReview(owner,"review",resolve("decision","KEEP_SOURCE"))).isSameAs(completed);
        when(bridge.getReview(owner,"review")).thenReturn(completed);
        service.resolveReview(owner,"review",resolve("decision","KEEP_SOURCE"));verify(bridge,times(1)).resolveReview(any(),any(),any());
        assertThat(settings.audit(owner)).singleElement().satisfies(row->{assertThat(row.action()).isEqualTo("REVIEW_DECISION");assertThat(row.outcome()).isEqualTo("SUCCEEDED");});
        assertThatThrownBy(()->service.resolveReview(owner,"review",resolve("decision","KEEP_BOTH"))).hasMessageContaining("409");
    }
    @Test void readingACommittedReviewReconcilesLostResponseWithoutRepeatingTheDecision(){
        when(bridge.getReview(owner,"review")).thenReturn(reviewResult(1));when(bridge.resolveReview(any(),any(),any())).thenThrow(new IllegalStateException("PRIVATE_UPSTREAM"));
        assertThatThrownBy(()->service.resolveReview(owner,"review",resolve("uncertain","KEEP_SOURCE"))).hasMessageContaining("503").hasMessageNotContaining("PRIVATE_UPSTREAM");
        assertThatThrownBy(()->service.resolveReview(owner,"review",resolve("uncertain","KEEP_SOURCE"))).hasMessageContaining("409");
        var result=reviewResult(2,new MemoryDtos.ReviewDecision("uncertain","candidate","KEEP_SOURCE",1,null));when(bridge.getReview(owner,"review")).thenReturn(result);
        assertThat(service.getReview(owner,"review")).isSameAs(result);
        service.resolveReview(owner,"review",resolve("uncertain","KEEP_SOURCE"));verify(bridge,times(1)).resolveReview(any(),any(),any());
        assertThat(settings.audit(owner)).singleElement().satisfies(row->assertThat(row.outcome()).isEqualTo("SUCCEEDED"));
        assertThat(settings.audit(other)).isEmpty();
    }
    @Test void decisionProofAndAuditFailuresNeverProduceSuccess(){
        when(bridge.getReview(owner,"review")).thenReturn(reviewResult(1));when(bridge.resolveReview(any(),any(),any())).thenReturn(reviewResult(2,new MemoryDtos.ReviewDecision("wrong","candidate","KEEP_SOURCE",1,null)));
        assertThatThrownBy(()->service.resolveReview(owner,"review",resolve("bad-proof","KEEP_SOURCE"))).hasMessageContaining("503");
        assertThat(settings.audit(owner)).singleElement().satisfies(row->assertThat(row.outcome()).isEqualTo("UNKNOWN"));
        jdbc.execute("DROP TABLE agent_memory_audit");clearInvocations(bridge);
        assertThatThrownBy(()->service.resolveReview(owner,"review",resolve("no-audit","KEEP_SOURCE"))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        verify(bridge,never()).resolveReview(any(),any(),any());
    }
    private MemoryDtos.ChangeLifecycle lifecycle(String key,boolean confirmed){return new MemoryDtos.ChangeLifecycle(key,"a".repeat(64),0,"EXCLUDED",null,false,confirmed);}
    @Test void lifecycleRequiresConfirmationAndAuditsBeforeDispatch(){
        assertThatThrownBy(()->service.changeLifecycle(owner,"mine",lifecycle("no-confirm",false))).hasMessageContaining("400");
        verifyNoInteractions(bridge);assertThat(settings.audit(owner)).isEmpty();
        var saved=new MemoryDtos.Lifecycle("mine",1,"EXCLUDED",null,false,"NONE",null);
        when(bridge.changeLifecycle(owner,"mine",lifecycle("confirmed",true))).thenReturn(saved);
        assertThat(service.changeLifecycle(owner,"mine",lifecycle("confirmed",true))).isSameAs(saved);
        assertThat(settings.audit(owner)).singleElement().satisfies(a->{assertThat(a.action()).isEqualTo("LIFECYCLE");assertThat(a.outcome()).isEqualTo("SUCCEEDED");});
        when(bridge.getOwned(owner,"mine")).thenReturn(new MemoryDtos.Item("mine","text",null,null,null,"a".repeat(64),saved));
        assertThat(service.changeLifecycle(owner,"mine",lifecycle("confirmed",true))).isSameAs(saved);
        verify(bridge,times(1)).changeLifecycle(any(),any(),any());
        assertThatThrownBy(()->service.changeLifecycle(owner,"mine",new MemoryDtos.ChangeLifecycle("confirmed","a".repeat(64),0,"ACTIVE",null,false,true))).hasMessageContaining("409");
    }
    @Test void lifecycleAuditAndUnknownFailuresCannotRepeatRemoteMutation(){
        when(bridge.changeLifecycle(any(),any(),any())).thenThrow(new IllegalStateException("PRIVATE_ERROR"));
        assertThatThrownBy(()->service.changeLifecycle(owner,"mine",lifecycle("unknown",true))).hasMessageContaining("503").hasMessageNotContaining("PRIVATE_ERROR");
        assertThatThrownBy(()->service.changeLifecycle(owner,"mine",lifecycle("unknown",true))).hasMessageContaining("409");
        verify(bridge,times(1)).changeLifecycle(any(),any(),any());
        jdbc.execute("DROP TABLE agent_memory_audit");clearInvocations(bridge);
        assertThatThrownBy(()->service.changeLifecycle(owner,"mine",lifecycle("audit-failed",true))).isInstanceOf(org.springframework.dao.DataAccessException.class);verifyNoInteractions(bridge);
    }
    @Test void lifecycleRejectsMissingExpiryInvalidTimeAndInvalidStateBeforeAuditing(){
        for(var request:List.of(new MemoryDtos.ChangeLifecycle("invalid","a".repeat(64),0,"ACTIVE",null,true,true),
            new MemoryDtos.ChangeLifecycle("invalid","a".repeat(64),0,"ACTIVE","2020-01-01T00:00:00+08:00",true,true),
            new MemoryDtos.ChangeLifecycle("invalid","a".repeat(64),0,"ACTIVE","2030-01-01T00:00:00",false,true),
            new MemoryDtos.ChangeLifecycle("invalid","a".repeat(64),0,"DELETE_ALL",null,false,true)))
            assertThatThrownBy(()->service.changeLifecycle(owner,"mine",request)).hasMessageContaining("400");
        verifyNoInteractions(bridge);assertThat(settings.audit(owner)).isEmpty();
        service.lifecycleHistory(other);service.verifyCleanup(other,"mine");verify(bridge).lifecycleHistory(other);verify(bridge).verifyCleanup(other,"mine");
    }
    @Test void realHttpReceiptReconcilesTheDatabaseWithoutRepeatingExtraction()throws Exception{
        var json=new com.fasterxml.jackson.databind.ObjectMapper();var key=new java.util.concurrent.atomic.AtomicReference<String>();var adds=new java.util.concurrent.atomic.AtomicInteger();var completed=new java.util.concurrent.atomic.AtomicBoolean();
        var server=com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/memories",exchange->{var body=json.readTree(exchange.getRequestBody());assertThat(body.path("user_id").asText()).isEqualTo(owner.mem0UserId());assertThat(exchange.getRequestHeaders().getFirst("X-Doorhandle-Memory-Token")).isEqualTo("fixture");
            boolean add=exchange.getRequestURI().getPath().endsWith("/add");if(add){adds.incrementAndGet();key.set(body.path("request_id").asText());}
            var receipt=Map.of("requestId",key.get(),"status",completed.get()?"SUCCEEDED":"RUNNING","results",completed.get()?List.of(Map.of("id","stored","event","ADD")):List.of(),"updatedAt","2026-10-18T12:00:00+08:00");
            byte[] response=json.writeValueAsBytes(Map.of("code",add?202:200,"data",add?Map.of("operation",receipt):receipt));exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(add?202:200,response.length);exchange.getResponseBody().write(response);exchange.close();});server.start();
        try{
            var client=new Mem0Client(new com.ruanzhu.doorhandle.module.system.security.SensitiveDataSanitizer(),settings);org.springframework.test.util.ReflectionTestUtils.setField(client,"enabled",true);org.springframework.test.util.ReflectionTestUtils.setField(client,"bridgeToken","fixture");org.springframework.test.util.ReflectionTestUtils.setField(client,"serviceUrl","http://127.0.0.1:"+server.getAddress().getPort());
            var metadata=Map.<String,Object>of("turn_id",10,"source","fixture");client.addMemory(owner,"session","PRIVATE_INPUT",metadata);assertThat(settings.automaticOutcome(owner,key.get())).isEqualTo("DISPATCHED");
            client.addMemory(owner,"session","PRIVATE_INPUT",metadata);assertThat(adds).hasValue(1);
            var actual=new PersonalMemoryService(client,settings);assertThat(actual.verifyExtraction(owner,key.get()).affectedMemories()).isNull();assertThat(settings.automaticOutcome(owner,key.get())).isEqualTo("DISPATCHED");completed.set(true);assertThat(actual.verifyExtraction(owner,key.get()).affectedMemories()).isEqualTo(1);assertThat(settings.automaticOutcome(owner,key.get())).isEqualTo("SUCCEEDED");
            client.addMemory(owner,"session","PRIVATE_INPUT",metadata);assertThat(adds).hasValue(1);
            assertThat(jdbc.queryForList("SELECT * FROM agent_memory_audit").toString()).doesNotContain("PRIVATE_INPUT");
        }finally{server.stop(0);}
    }
    @Test void automaticWritesReserveOnceAndOnlyOwnedReceiptsCanResolveUnknownOutcomes(){
        String key="b".repeat(64),digest="c".repeat(64);
        assertThat(settings.reserveAutomatic(owner,key,digest)).isFalse();
        assertThatThrownBy(()->settings.reserveAutomatic(owner,key,digest)).hasMessageContaining("409");
        settings.deletionOutcome(owner,key,"UNKNOWN");
        assertThatThrownBy(()->settings.reserveAutomatic(owner,key,digest)).hasMessageContaining("409");
        assertThatThrownBy(()->service.verifyExtraction(other,key)).hasMessageContaining("404");verifyNoInteractions(bridge);
        when(bridge.extractionReceipt(owner,key)).thenReturn(new MemoryDtos.Extraction(key,"SUCCEEDED",2,"2026-10-18T12:00:00+08:00"));
        assertThat(service.verifyExtraction(owner,key).affectedMemories()).isEqualTo(2);
        assertThat(settings.automaticOutcome(owner,key)).isEqualTo("SUCCEEDED");
        assertThat(settings.reserveAutomatic(owner,key,digest)).isTrue();
        assertThatThrownBy(()->settings.reserveAutomatic(owner,key,"d".repeat(64))).hasMessageContaining("409");
        assertThat(settings.audit(owner)).singleElement().satisfies(row->{assertThat(row.action()).isEqualTo("AUTOSAVE");assertThat(row.requestId()).isEqualTo(key);});
    }
    @Test void aRunningReceiptDoesNotEraseUnknownOutcomeAndNotStartedIsARejection(){
        String key="b".repeat(64);settings.reserveAutomatic(owner,key,"c".repeat(64));settings.deletionOutcome(owner,key,"UNKNOWN");
        settings.reconcileAutomatic(owner,key,"RUNNING");assertThat(settings.automaticOutcome(owner,key)).isEqualTo("UNKNOWN");
        settings.reconcileAutomatic(owner,key,"NOT_STARTED");assertThat(settings.automaticOutcome(owner,key)).isEqualTo("REJECTED");
        assertThatThrownBy(()->settings.reconcileAutomatic(other,key,"SUCCEEDED")).hasMessageContaining("404");
    }
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
