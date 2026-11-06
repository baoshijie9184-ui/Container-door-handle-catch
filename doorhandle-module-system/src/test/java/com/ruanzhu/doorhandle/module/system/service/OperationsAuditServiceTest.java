package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import com.ruanzhu.doorhandle.module.system.support.OperationsMySqlFixture;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@EnabledIfSystemProperty(named="doorhandle.operations.mysql.config",matches=".+")
class OperationsAuditServiceTest {
    JdbcTemplate jdbc;BusinessUserDirectory users;OperationsAuditService service;
    OperationsMySqlFixture fixture;TransactionTemplate tx;
    AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),bob=new AgentActor(2,"bob",AgentActor.Role.INSPECTOR),boss=new AgentActor(3,"boss",AgentActor.Role.SUPERVISOR);
    @BeforeEach void setup() throws Exception {fixture=new OperationsMySqlFixture(false);jdbc=fixture.target();tx=new TransactionTemplate(new DataSourceTransactionManager(fixture.dataSource()));tx.setIsolationLevel(org.springframework.transaction.TransactionDefinition.ISOLATION_REPEATABLE_READ);users=mock(BusinessUserDirectory.class);for(var a:List.of(alice,bob,boss))when(users.current(a.userId(),a.username())).thenReturn(new BusinessUserDirectory.Identity(a.userId(),a.username(),a.supervisor()));service=new OperationsAuditService(jdbc,users);}
    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}
    void append(OperationsAuditApi.Event event){tx.executeWithoutResult(status->service.append(event));}
    OperationsAuditApi.Event event(AgentActor actor,String scope,String id){return new OperationsAuditApi.Event(actor,scope,"DETECTION","UPDATE",id,"request-1","APPLIED",1L);}
    @Test void supervisorCannotReadOtherAccountsPrivateAuditAndEmployeeOnlySeesOwn(){append(event(alice,"PRIVATE","a"));append(event(bob,"ENTERPRISE","b"));append(event(boss,"ENTERPRISE","c"));assertThat(service.list(alice,Long.MAX_VALUE,50,null)).hasSize(1);assertThat(service.list(boss,Long.MAX_VALUE,50,null)).hasSize(2).noneMatch(row->row.get("resource_id").equals("a"));}
    @Test void exactReceiptIsIdempotentButChangingScopeUnderSameIdentityIsRejected(){var event=event(alice,"ENTERPRISE","a");append(event);append(event);assertThat(service.list(alice,Long.MAX_VALUE,50,null)).hasSize(1);assertThatThrownBy(()->append(event(alice,"PRIVATE","a"))).hasMessageContaining("冲突");}
    @Test void originalSixPartIdentityAndMaximumLengthsArePreserved(){String domain="d".repeat(48),resource="r".repeat(160),request="q".repeat(128),result="x".repeat(40);var first=new OperationsAuditApi.Event(alice,"ENTERPRISE",domain,"WRITE",resource,request,result,-7L);append(first);append(first);append(new OperationsAuditApi.Event(alice,"ENTERPRISE",domain,"WRITE",resource,request,"OTHER",-7L));append(new OperationsAuditApi.Event(alice,"ENTERPRISE",domain,"WRITE","other",request,result,-7L));assertThat(service.list(alice,Long.MAX_VALUE,100,domain)).hasSize(3);assertThatThrownBy(()->append(new OperationsAuditApi.Event(alice,"ENTERPRISE",domain,"WRITE",resource,request,result,null))).hasMessageContaining("冲突");}
    @Test void duplicateReceiptUsesCurrentReadAfterAnOlderRepeatableReadSnapshot() throws Exception {
        var ready=new java.util.concurrent.CountDownLatch(1);var committed=new java.util.concurrent.CountDownLatch(1);
        var pool=java.util.concurrent.Executors.newSingleThreadExecutor();var receipt=event(alice,"PRIVATE","racing");
        try {
            var future=pool.submit(()->tx.executeWithoutResult(status->{
                service.list(alice,Long.MAX_VALUE,10,null);ready.countDown();
                try {if(!committed.await(10,java.util.concurrent.TimeUnit.SECONDS))throw new IllegalStateException("winner timeout");}
                catch(InterruptedException error){Thread.currentThread().interrupt();throw new IllegalStateException(error);}
                service.append(receipt);
            }));
            assertThat(ready.await(10,java.util.concurrent.TimeUnit.SECONDS)).isTrue();append(receipt);committed.countDown();
            future.get(10,java.util.concurrent.TimeUnit.SECONDS);
        } finally {committed.countDown();pool.shutdownNow();}
        assertThat(service.list(alice,Long.MAX_VALUE,10,null)).hasSize(1);
    }
    @Test void simultaneousDuplicateInsertReadersDoNotUpgradeSharedLocks() throws Exception {
        var receipt=event(alice,"PRIVATE","same-receipt");append(receipt);
        var duplicateBarrier=new java.util.concurrent.CyclicBarrier(2);
        var gated=new JdbcTemplate(fixture.dataSource()) {
            @Override public int update(String sql,Object... arguments) {
                try {return super.update(sql,arguments);}
                catch(org.springframework.dao.DuplicateKeyException duplicate) {
                    if(sql.contains("INSERT INTO audit_event")) {
                        try {duplicateBarrier.await(10,java.util.concurrent.TimeUnit.SECONDS);}
                        catch(InterruptedException error){Thread.currentThread().interrupt();throw new IllegalStateException(error);}
                        catch(java.util.concurrent.BrokenBarrierException|java.util.concurrent.TimeoutException error){throw new IllegalStateException(error);}
                    }
                    throw duplicate;
                }
            }
        };
        var competing=new OperationsAuditService(gated,users);var pool=java.util.concurrent.Executors.newFixedThreadPool(2);
        try {
            Runnable replay=()->tx.executeWithoutResult(status->competing.append(receipt));
            var first=pool.submit(replay);var second=pool.submit(replay);
            first.get(15,java.util.concurrent.TimeUnit.SECONDS);second.get(15,java.util.concurrent.TimeUnit.SECONDS);
        } finally {pool.shutdownNow();}
        assertThat(service.list(alice,Long.MAX_VALUE,10,null)).hasSize(1);
    }
    @Test void revokedIdentityAndFreeTextMetadataAreRejected(){when(users.current(alice.userId(),alice.username())).thenThrow(new SecurityException());assertThatThrownBy(()->service.append(event(alice,"PRIVATE","a"))).isInstanceOf(SecurityException.class);assertThatThrownBy(()->service.append(new OperationsAuditApi.Event(bob,"ENTERPRISE","DETECTION","WRITE","private prompt with spaces","r","DONE",null))).isInstanceOf(IllegalArgumentException.class);}
}
