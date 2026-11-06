package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import com.ruanzhu.doorhandle.module.app.testsupport.CompactWorkflowFixture;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.transaction.support.TransactionTemplate;
import java.time.Duration;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

/** Execute only through the ECS test runner; no local application or database is needed to compile. */
class JdbcWorkflowFencingTest {
    public record Payload(String value) { }
    private JdbcTemplate jdbc; private TransactionTemplate tx;
    private final Payload body=new Payload("fixture");
    @BeforeEach void setup() throws Exception {
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");
        jdbc=new JdbcTemplate(source);tx=new TransactionTemplate(new DataSourceTransactionManager(source));CompactWorkflowFixture.install(jdbc);
    }
    private JdbcWorkflowStore store(boolean replaySafe) {
        return new JdbcWorkflowStore(jdbc,new ObjectMapper(),WorkflowProtocols.defaults().with(new WorkflowProtocol<>(
                WorkflowKind.DIGEST_RUN,1,Payload.class,Set.of("PENDING"),Set.of("COMPLETED"),
                Map.of("PENDING",Set.of("RUNNING"),"RUNNING",Set.of("RUNNING","FAILED","COMPLETED"),"FAILED",Set.of("PENDING")),
                value->{},replaySafe)));
    }
    private WorkflowRecord claim(JdbcWorkflowStore store) {
        return tx.execute(status->{
            String id=UUID.randomUUID().toString();
            var created=store.create(new WorkflowDraft(id,WorkflowKind.DIGEST_RUN,"FENCE_TEST",id,"a".repeat(64),1,1L,null,
                    "DIGEST","digest",null,null,null,"PENDING",null,1,body));
            return store.claim(created,"RUNNING",body,null,null,Duration.ofMinutes(5));
        });
    }
    @Test void expiredClaimRequiresDeclaredReplaySafetyAndRejectsPreviousWorkerAfterReclaim() {
        var store=store(true);var first=claim(store);
        jdbc.update("UPDATE workflow_instance SET lease_expires_at=? WHERE id=?",store.now().minusSeconds(1),first.id());
        var unsafe=store(false);
        assertThatThrownBy(()->tx.execute(s->unsafe.reclaim(first,"RUNNING",body,null,null,Duration.ofMinutes(5))))
                .isInstanceOf(WorkflowConflictException.class);
        var second=tx.execute(s->store.reclaim(first,"RUNNING",body,null,null,Duration.ofMinutes(5)));
        assertThat(second.fence()).isGreaterThan(first.fence());assertThat(second.claimToken()).isNotEqualTo(first.claimToken());
        assertThatThrownBy(()->tx.execute(s->store.finishClaim(first,"COMPLETED",body,null))).isInstanceOf(WorkflowConflictException.class);
        var done=tx.execute(s->store.finishClaim(second,"COMPLETED",body,null));
        assertThat(done.status()).isEqualTo("COMPLETED");assertThat(done.claimToken()).isNull();assertThat(done.finishedAt()).isNotNull();
    }
    @Test void retryReleaseRetainsFenceAndCannotBeAcknowledgedByAStaleWorker() {
        var store=store(true);var first=claim(store);
        var retry=tx.execute(s->store.releaseClaim(first,"FAILED",body,"RETRYABLE",store.now().plusMinutes(1)));
        assertThat(retry.claimToken()).isNull();assertThat(retry.finishedAt()).isNull();assertThat(retry.fence()).isEqualTo(first.fence());
        assertThatThrownBy(()->tx.execute(s->store.finishClaim(first,"COMPLETED",body,null))).isInstanceOf(WorkflowConflictException.class);
        var pending=tx.execute(s->store.transition(retry,"PENDING",body,null,null,null));
        var next=tx.execute(s->store.claim(pending,"RUNNING",body,null,null,Duration.ofMinutes(5)));
        assertThat(next.fence()).isGreaterThan(first.fence());
        assertThatThrownBy(()->tx.execute(s->store.releaseClaim(next,"COMPLETED",body,null,store.now().plusMinutes(1))))
                .isInstanceOf(IllegalArgumentException.class);
    }
    @Test void workflowMutationRejectsAutocommit() {
        var store=store(true);var first=claim(store);
        assertThatThrownBy(()->store.releaseClaim(first,"FAILED",body,null,null)).isInstanceOf(IllegalStateException.class);
    }
}
