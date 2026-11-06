package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.system.support.OperationsMySqlFixture;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@EnabledIfSystemProperty(named="doorhandle.operations.mysql.config",matches=".+")
class FileDeliveryAuditMySqlTest {
    OperationsMySqlFixture fixture;JdbcTemplate jdbc;BusinessUserDirectory users;FileDeliveryAuditService service;
    AgentActor actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);FileDelivery metadata;
    @BeforeEach void setup() throws Exception {
        fixture=new OperationsMySqlFixture(false);jdbc=fixture.target();users=mock(BusinessUserDirectory.class);
        when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        OperationsAuditApi api=new OperationsAuditService(jdbc,users);
        @SuppressWarnings("unchecked") ObjectProvider<OperationsAuditApi> provider=mock(ObjectProvider.class);
        when(provider.getObject()).thenReturn(api);when(provider.getIfAvailable()).thenReturn(api);
        service=new FileDeliveryAuditService(jdbc,new DataSourceTransactionManager(fixture.dataSource()),users,provider);service.schema();
        metadata=mock(FileDelivery.class);when(metadata.scope()).thenReturn("PRIVATE");when(metadata.domain()).thenReturn("DETECTION");
    }
    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}
    FileDeliveryAuditService.Ticket authorize(){return service.authorize(actor,metadata,"report-one","file-one",7L,"correlation-one",100L,false,200);}
    String state(String id){return jdbc.queryForObject("SELECT status FROM workflow_instance WHERE kind='FILE_DELIVERY' AND workflow_id=?",String.class,id);}
    @Test void completionUsesPreviouslyAuthorizedActorAndPreservesUnknownLowerBound() {
        var ticket=authorize();service.started(ticket);clearInvocations(users);
        when(users.current(1,"alice")).thenThrow(new SecurityException("account revoked"));
        service.finish(ticket,80,200,false,true);assertThat(state(ticket.deliveryId())).isEqualTo("UNKNOWN");
        assertThat(jdbc.queryForObject("SELECT finished_at FROM workflow_instance WHERE workflow_id=?",String.class,ticket.deliveryId())).isNull();
        service.finish(ticket,70,200,false,false);assertThat(state(ticket.deliveryId())).isEqualTo("SERVER_COMPLETED");
        assertThat(jdbc.queryForObject("SELECT CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.acceptedBytesLowerBound')) AS SIGNED) FROM workflow_instance WHERE workflow_id=?",Long.class,ticket.deliveryId())).isEqualTo(80L);
        verifyNoInteractions(users);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='OPERATIONS' AND request_id=?",Long.class,ticket.deliveryId())).isEqualTo(4L);
    }
    @Test void reconcileMarksUncertaintyWithoutInventingCompletionOrRepeatingAuthorization() {
        var ticket=authorize();jdbc.update("UPDATE workflow_instance SET updated_at=DATE_SUB(UTC_TIMESTAMP(6),INTERVAL 16 MINUTE) WHERE workflow_id=?",ticket.deliveryId());
        clearInvocations(users);service.reconcile();service.reconcile();verifyNoInteractions(users);
        assertThat(state(ticket.deliveryId())).isEqualTo("UNKNOWN");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE action='FILE_RESPONSE_UNCONFIRMED' AND request_id=?",Long.class,ticket.deliveryId())).isEqualTo(1L);
    }
    @Test void responseStateAndReceiptRollbackTogetherWhenAuditWriteFails() throws Exception {
        var ticket=authorize();service.started(ticket);
        fixture.install("CREATE TRIGGER fixture_reject_finish BEFORE INSERT ON audit_event FOR EACH ROW BEGIN IF NEW.action='FILE_RESPONSE_FINISHED' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture receipt failure'; END IF; END$$","$$");
        assertThatThrownBy(()->service.finish(ticket,100,200,false,false)).isInstanceOf(RuntimeException.class);
        assertThat(state(ticket.deliveryId())).isEqualTo("STREAMING");
        assertThat(jdbc.queryForObject("SELECT revision FROM workflow_instance WHERE workflow_id=?",Long.class,ticket.deliveryId())).isEqualTo(1L);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE action='FILE_RESPONSE_FINISHED'",Long.class)).isZero();
    }
    @Test void headAndRedirectRemainDifferentFromBodyCompletion() {
        var head=service.authorize(actor,metadata,"head",null,null,"head-request",0L,false,200,true);
        service.started(head);service.finish(head,0,200,false,false);assertThat(state(head.deliveryId())).isEqualTo("HEAD_COMPLETED");
        var redirect=service.authorize(actor,metadata,"redirect",null,null,"redirect-request",null,true,302);
        service.finish(redirect,100,200,false,false);assertThat(state(redirect.deliveryId())).isEqualTo("REDIRECT_AUTHORIZED");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE request_id=?",Long.class,redirect.deliveryId())).isEqualTo(1L);
    }
    @Test void concurrentFinalCallbacksCommitOnlyOneTerminalTransition() throws Exception {
        var ticket=authorize();service.started(ticket);var pool=Executors.newFixedThreadPool(2);var ready=new CountDownLatch(1);
        try {
            Callable<Void> finish=()->{ready.await();service.finish(ticket,100,200,false,false);return null;};
            var first=pool.submit(finish);var second=pool.submit(finish);ready.countDown();first.get(10,TimeUnit.SECONDS);second.get(10,TimeUnit.SECONDS);
        } finally {pool.shutdownNow();}
        assertThat(state(ticket.deliveryId())).isEqualTo("SERVER_COMPLETED");
        assertThat(jdbc.queryForObject("SELECT revision FROM workflow_instance WHERE workflow_id=?",Long.class,ticket.deliveryId())).isEqualTo(2L);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE action='FILE_RESPONSE_FINISHED' AND request_id=?",Long.class,ticket.deliveryId())).isEqualTo(1L);
    }
}
