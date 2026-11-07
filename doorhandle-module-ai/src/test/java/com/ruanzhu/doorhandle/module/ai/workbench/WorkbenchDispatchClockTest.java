package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.time.LegacyClockEvidence;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.WorkbenchSessionApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Supplier;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Pure admission-boundary regressions, executed only by the ECS source verification reactor. */
class WorkbenchDispatchClockTest {
    private final AgentActor actor=new AgentActor(1,"fixture-user",AgentActor.Role.INSPECTOR);
    private final WorkbenchStore store=mock(WorkbenchStore.class);
    private final WorkbenchSessionApi app=mock(WorkbenchSessionApi.class);
    private final BusinessUserDirectory users=mock(BusinessUserDirectory.class);
    private final AtomicBoolean locked=new AtomicBoolean();
    private AgentWorkbenchService service;

    @BeforeEach void create(){
        @SuppressWarnings("unchecked") ObjectProvider<WorkbenchSessionApi> provider=mock(ObjectProvider.class);
        when(provider.getObject()).thenReturn(app);
        when(users.current(actor.userId(),actor.username())).thenReturn(new BusinessUserDirectory.Identity(1,actor.username(),false));
        doAnswer(call->{
            assertThat(locked.compareAndSet(false,true)).isTrue();
            try{return call.<Supplier<?>>getArgument(1).get();}finally{locked.set(false);}
        }).when(store).locked(eq(1L),any());
        service=new AgentWorkbenchService(store,new WorkbenchProperties(),users,provider,mock(RoleAgentFactory.class),mock(AgentJournal.class));
    }
    @AfterEach void close(){service.close();}

    private WorkbenchStore.Row row(String kind,String status,long revision,LegacyClockEvidence clock){
        return new WorkbenchStore.Row("fixture-item",1,"fixture-session",kind,status,revision,
            Map.of("username",actor.username(),"role",actor.role().name(),"continuation","continue revision "+revision),
            null,17,"fixture-workflow",null,0,null,null,clock);
    }
    private LegacyClockEvidence unresolved()throws Exception{
        // These are explicit protocol-fixture attestations, never a migration or native row-hash proof.
        String body=new ObjectMapper().writeValueAsString(Map.of("protocol",LegacyClockEvidence.PROTOCOL,"status","UNRESOLVED",
            "sourceTable","agent_workbench_item","sourceKey",Map.of("id",17),"sourceSnapshotSha256","a".repeat(64),
            "sourceRowSha256","b".repeat(64),"sourceWallTimes",Map.of("updated_at","2025-01-02 03:04:05")));
        return LegacyClockEvidence.parse(body,"agent_workbench_item",Map.of("id",17));
    }
    @Test void preservedUnknownCandidatesNeverReachAuthorizationOrAdmission()throws Exception{
        var clock=unresolved();
        when(store.dispatch(0)).thenReturn(List.of(row("EXECUTION","READY",2,clock),row("CHILD","QUEUED",3,clock)));
        service.dispatch();
        verifyNoInteractions(app,users);verify(store,never()).require(anyLong(),anyString(),anyString());
    }
    @Test void unknownLatestRowCannotReuseAKnownScanCandidate()throws Exception{
        when(store.dispatch(0)).thenReturn(List.of(row("EXECUTION","READY",2,null)));
        when(store.require(1,"fixture-session","fixture-item")).thenReturn(row("EXECUTION","READY",2,unresolved()));
        service.dispatch();
        verify(app,never()).continueSession(any(),anyString(),anyString(),anyString());
        verify(store,never()).locked(anyLong(),any());
    }
    @Test void finalLockedReadRejectsUnknownExecutionAndChildBeforeAnySideEffect()throws Exception{
        for(String kind:List.of("EXECUTION","CHILD")){
            clearInvocations(store,app);String status=kind.equals("EXECUTION")?"READY":"QUEUED";
            var known=row(kind,status,2,null);
            when(store.dispatch(anyLong())).thenReturn(List.of(known));
            when(store.require(1,"fixture-session","fixture-item")).thenReturn(known,row(kind,status,2,unresolved()));
            service.dispatch();
            verify(store).locked(eq(1L),any());verify(store,times(2)).require(1,"fixture-session","fixture-item");
            verify(app,never()).continueSession(any(),anyString(),anyString(),anyString());
            verify(store,never()).update(any(),anyString(),anyMap(),anyString());
        }
    }
    @Test void aCancelledExecutionCannotBeAdmittedFromAStaleReadyScan(){
        var ready=row("EXECUTION","READY",2,null);
        when(store.dispatch(0)).thenReturn(List.of(ready));
        when(store.require(1,"fixture-session","fixture-item")).thenReturn(ready,row("EXECUTION","CANCELLED",3,null));
        service.dispatch();
        verify(store).locked(eq(1L),any());verify(app,never()).continueSession(any(),anyString(),anyString(),anyString());
    }
    @Test void anAlreadyQueuedContinuationCannotBypassAnUnknownMainExecution()throws Exception{
        String main=WorkbenchStore.stable(1,"fixture-session","MAIN_EXECUTION");
        String continuation=WorkbenchStore.stable(1,"fixture-session","continue:fixture-item:2");
        for(String status:List.of("READY","RUNNING","COMPLETED","CANCELLED","WAITING_PLAN","NEEDS_REVIEW")){
            when(store.find(1,"fixture-session",main)).thenReturn(row("EXECUTION",status,2,unresolved()));
            assertThat(service.canDispatchInput(actor,"fixture-session",continuation)).isFalse();
        }
        when(store.find(1,"fixture-session",main)).thenReturn(row("EXECUTION","READY",2,null));
        assertThat(service.canDispatchInput(actor,"fixture-session",continuation)).isTrue();
        assertThat(service.canDispatchInput(actor,"fixture-session","unrelated-input")).isFalse();
        when(store.find(1,"fixture-session",main)).thenReturn(row("EXECUTION","COMPLETED",2,null));
        assertThat(service.canDispatchInput(actor,"fixture-session","new-input")).isTrue();
    }
    @Test void confirmedReadyUsesFinalRevisionAndAdmitsOnlyInsideTheExistingLock(){
        var scanned=row("EXECUTION","READY",2,null);var current=row("EXECUTION","READY",4,null);
        when(store.dispatch(0)).thenReturn(List.of(scanned));
        when(store.require(1,"fixture-session","fixture-item")).thenReturn(scanned,current);
        String request=WorkbenchStore.stable(1,"fixture-session","continue:fixture-item:4");
        doAnswer(call->{assertThat(locked).isTrue();return null;}).when(app).continueSession(actor,"fixture-session",request,"continue revision 4");
        service.dispatch();
        verify(app).continueSession(actor,"fixture-session",request,"continue revision 4");
        verify(store).locked(eq(1L),any());assertThat(locked).isFalse();
        verify(store,never()).update(any(),anyString(),anyMap(),anyString());
    }
}
