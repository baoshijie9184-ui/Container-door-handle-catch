package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentConversationApi;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatConfirmActionRequest;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatMessageResponse;
import com.ruanzhu.doorhandle.module.app.entity.ChatPendingAction;
import com.ruanzhu.doorhandle.module.app.service.ChatSessionService;
import com.ruanzhu.doorhandle.module.app.service.Mem0Client;
import com.ruanzhu.doorhandle.module.app.service.RagKnowledgeService;
import com.ruanzhu.doorhandle.module.app.testsupport.LegacyChatActionMySqlFixture;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Native MySQL coverage; never falls back to H2 or a local/business database. */
@EnabledIfSystemProperty(named="legacy.chat.mysql.config",matches=".+")
class LegacyChatActionStoreMySqlTest {
    private static final String SESSION="legacy-session-alice",OTHER="legacy-session-bob";
    private static final String RAW="  not JSON: <原始动作𠀀>\r\n'\\\ttrailing bytes  ";
    private final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    private LegacyChatActionMySqlFixture fixture;
    private JdbcTemplate jdbc;
    private LegacyChatActionStore store;
    private TransactionTemplate tx;

    @BeforeEach void setup() throws Exception {
        fixture=new LegacyChatActionMySqlFixture();jdbc=fixture.jdbc();
        var manager=new DataSourceTransactionManager(fixture.dataSource());tx=new TransactionTemplate(manager);
        // Application-wide NON_NULL must not erase mandatory nullable fields in the stored protocol.
        store=new LegacyChatActionStore(jdbc,json.copy().setSerializationInclusion(JsonInclude.Include.NON_NULL),manager);
        jdbc.update("INSERT INTO users(id,username,password,role) VALUES(1,'alice','fixture','INSPECTOR'),(2,'bob','fixture','INSPECTOR')");
        jdbc.update("INSERT INTO chat_session(session_id,username,user_id) VALUES(?,'alice',1),(?,'bob',2)",SESSION,OTHER);
    }
    @AfterEach void cleanup(){SecurityContextHolder.clearContext();if(fixture!=null)fixture.close();}

    private ChatPendingAction pending(String action,String session) {
        var value=new ChatPendingAction();value.setActionId(action);value.setSessionId(session);
        value.setActionType("OLD_OPERATION");value.setActionPayloadJson(RAW);return value;
    }
    private long count(String table){return jdbc.queryForObject("SELECT COUNT(*) FROM "+table,Long.class);}
    private long revision(String action){return jdbc.queryForObject("SELECT revision FROM workflow_instance WHERE chat_action_id=?",Long.class,action);}
    private String digest(String text) throws Exception {return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));}
    private void importNullClockAction(String action) throws Exception {
        var payload=new LegacyChatActionStore.PendingV1("OLD_OPERATION",RAW,"original error  ","98",SESSION,null,null,"+08:00");
        jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,
                  resource_type,resource_id,chat_action_session_id,status,revision,payload_version,payload_json,
                  created_at,updated_at,confirmation_recorded_at,finished_at,legacy_source,legacy_key)
                VALUES(?,'LEGACY_CHAT_ACTION','LEGACY_CHAT_ACTION',?,?,1,'CHAT_ACTION',?,?,'pending',0,1,?,
                  NULL,NULL,NULL,NULL,'chat_pending_action','98')
                """,UUID.randomUUID().toString(),action,digest(json.writeValueAsString(List.of(payload.actionType(),payload.actionPayload()))),
                action,SESSION,json.writeValueAsString(payload));
    }

    @Test void rawLongtextAndUnknownHistoricalTimesSurviveReadAndCancellation() throws Exception {
        importNullClockAction("Legacy_Action");var read=store.get(1,SESSION,"legacy_action");
        assertThat(read.getActionId()).isEqualTo("Legacy_Action");assertThat(read.getActionPayloadJson()).isEqualTo(RAW);
        assertThat(read.getCreatedAt()).isNull();assertThat(read.getConfirmedAt()).isNull();assertThat(read.getErrorMessage()).isEqualTo("original error  ");
        assertThat(store.transition(1,SESSION,"LEGACY_ACTION","PENDING","CANCELLED",null)).isTrue();
        var changed=store.get(1,SESSION,"legacy_action");assertThat(changed.getActionPayloadJson()).isEqualTo(RAW);
        assertThat(changed.getCreatedAt()).isNull();assertThat(changed.getConfirmedAt()).isNull();assertThat(changed.getStatus()).isEqualTo("CANCELLED");
        var payload=json.readValue(jdbc.queryForObject("SELECT payload_json FROM workflow_instance",String.class),LegacyChatActionStore.PendingV1.class);
        assertThat(payload.legacyId()).isEqualTo("98");assertThat(payload.legacySessionId()).isEqualTo(SESSION);
        assertThat(payload.legacyCreatedAt()).isNull();assertThat(payload.legacyConfirmedAt()).isNull();assertThat(payload.sourceUtcOffset()).isEqualTo("+08:00");
        var audit=json.readValue(jdbc.queryForObject("SELECT payload_json FROM audit_event",String.class),LegacyChatActionStore.TransitionV1.class);
        assertThat(audit.previousStatus()).isEqualTo("pending");assertThat(audit.previousErrorMessage()).isEqualTo("original error  ");
        assertThat(jdbc.queryForObject("SELECT finished_at FROM workflow_instance",LocalDateTime.class)).isNotNull();
    }

    private String importUnresolvedClockAction(String action)throws Exception{
        var times=new java.util.LinkedHashMap<String,Object>();times.put("created_at","2026-05-28 17:38:15");times.put("confirmed_at",null);
        String evidence=json.writeValueAsString(java.util.Map.of("protocol","doorhandle-legacy-clock-v1","status","UNRESOLVED",
                "sourceTable","chat_pending_action","sourceKey",java.util.Map.of("id",98),"sourceSnapshotSha256","a".repeat(64),
                "sourceRowSha256","b".repeat(64),"sourceWallTimes",times));
        var payload=new LegacyChatActionStore.PendingV1("OLD_OPERATION",RAW,"original error  ","98",SESSION,"2026-05-28 17:38:15.000000",null,null);
        jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,
                  resource_type,resource_id,chat_action_session_id,status,revision,payload_version,payload_json,
                  created_at,updated_at,confirmation_recorded_at,finished_at,legacy_source,legacy_key,legacy_clock_json)
                VALUES(?,'LEGACY_CHAT_ACTION','LEGACY_CHAT_ACTION',?,?,1,'CHAT_ACTION',?,?,'pending',0,1,?,
                  NULL,NULL,NULL,NULL,'chat_pending_action','98',?)
                """,UUID.randomUUID().toString(),action,digest(json.writeValueAsString(List.of(payload.actionType(),payload.actionPayload()))),
                action,SESSION,json.writeValueAsString(payload),evidence);
        return evidence;
    }
    @Test void unresolvedClockRetainsOriginalStatusRawPayloadAndNullTimesButBlocksApplication()throws Exception{
        String evidence=importUnresolvedClockAction("unknown-clock-action");
        var read=store.get(1,SESSION,"unknown-clock-action");
        assertThat(read.getCreatedAt()).isNull();assertThat(read.getConfirmedAt()).isNull();assertThat(read.getStatus()).isEqualTo("pending");
        assertThat(read.getActionPayloadJson()).isEqualTo(RAW);assertThat(read.getClockStatus()).isEqualTo("UNRESOLVED");
        assertThat(read.getSourceWallTimes()).containsEntry("created_at","2026-05-28 17:38:15").containsEntry("confirmed_at",null);
        assertThatThrownBy(()->store.transition(1,SESSION,"unknown-clock-action","PENDING","EXECUTING",null)).hasMessageContaining("历史时区未确认");
        assertThatThrownBy(()->store.mark(1,SESSION,"unknown-clock-action","CANCELLED")).hasMessageContaining("历史时区未确认");
        assertThatThrownBy(()->store.get(2,SESSION,"unknown-clock-action")).isInstanceOf(SecurityException.class);
        assertThat(jdbc.queryForObject("SELECT legacy_clock_json FROM workflow_instance",String.class)).isEqualTo(evidence);
        assertThat(jdbc.queryForObject("SELECT status FROM workflow_instance",String.class)).isEqualTo("pending");assertThat(count("audit_event")).isZero();
        var current=store.insert(1,pending("new-current-action",SESSION));assertThat(current.getCreatedAt()).isNotNull();assertThat(current.getClockStatus()).isEqualTo("UTC");
        assertThat(store.transition(1,SESSION,"new-current-action","PENDING","CANCELLED",null)).isTrue();
    }
    @Test void unresolvedClockCannotBorrowAnOffsetOrAnotherPrimaryKey()throws Exception{
        importUnresolvedClockAction("unknown-clock-action");
        assertThatThrownBy(()->{jdbc.update("UPDATE workflow_instance SET payload_json=JSON_SET(payload_json,'$.sourceUtcOffset','+08:00')");store.get(1,SESSION,"unknown-clock-action");})
                .isInstanceOfAny(IllegalStateException.class,DataAccessException.class);
        assertThatThrownBy(()->{jdbc.update("UPDATE workflow_instance SET payload_json=JSON_SET(payload_json,'$.sourceUtcOffset',CAST('null' AS JSON)),legacy_key='99'");store.get(1,SESSION,"unknown-clock-action");})
                .isInstanceOfAny(IllegalStateException.class,DataAccessException.class);
    }

    @Test void currentSessionOwnerControlsExistingActionsAfterTransfer() {
        store.insert(1,pending("ownership",SESSION));
        assertThatThrownBy(()->store.get(2,SESSION,"ownership")).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->store.insert(2,pending("wrong-owner",SESSION))).isInstanceOf(SecurityException.class);
        jdbc.update("UPDATE chat_session SET user_id=2,username='bob' WHERE session_id=?",SESSION);
        assertThatThrownBy(()->store.get(1,SESSION,"ownership")).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->store.transition(1,SESSION,"ownership","PENDING","CANCELLED",null)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->store.deleteSession(1,SESSION)).isInstanceOf(SecurityException.class);
        assertThat(store.get(2,SESSION,"ownership").getActionPayloadJson()).isEqualTo(RAW);
        assertThat(store.transition(2,SESSION,"ownership","PENDING","CANCELLED",null)).isTrue();
        assertThat(jdbc.queryForObject("SELECT owner_user_id FROM workflow_instance",Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForList("SELECT actor_user_id FROM audit_event ORDER BY id",Long.class)).containsExactly(1L,2L);
    }

    @Test void sessionRenameAndDeletionCascadeOnlyLiveActionRowsAndKeepAuditEvidence() {
        store.insert(1,pending("rename-action",SESSION));store.insert(2,pending("other-action",OTHER));
        jdbc.update("UPDATE chat_session SET session_id='renamed-session' WHERE session_id=?",SESSION);
        jdbc.update("UPDATE users SET username='alice-renamed' WHERE id=1");
        assertThat(jdbc.queryForObject("SELECT username FROM chat_session WHERE session_id='renamed-session'",String.class)).isEqualTo("alice-renamed");
        assertThat(store.get(1,"renamed-session","rename-action").getSessionId()).isEqualTo("renamed-session");
        assertThatThrownBy(()->store.get(1,SESSION,"rename-action")).isInstanceOf(SecurityException.class);
        assertThat(jdbc.queryForObject("SELECT session_id FROM audit_event WHERE resource_id='rename-action'",String.class)).isEqualTo(SESSION);
        assertThat(store.transition(1,"renamed-session","rename-action","PENDING","CANCELLED",null)).isTrue();
        jdbc.update("DELETE FROM chat_session WHERE session_id='renamed-session'");
        assertThat(count("workflow_instance")).isEqualTo(1);assertThat(store.get(2,OTHER,"other-action").getStatus()).isEqualTo("PENDING");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE resource_id='rename-action'",Long.class)).isEqualTo(2);
        assertThatThrownBy(()->store.get(1,"renamed-session","rename-action")).isInstanceOf(SecurityException.class);
    }

    @Test void actionIdentityRetainsGlobalUnicodeCaseAndAccentInsensitiveUniqueness() {
        store.insert(1,pending("Résumé_Action",SESSION));
        assertThat(store.get(1,SESSION,"resume_action").getActionId()).isEqualTo("Résumé_Action");
        assertThatThrownBy(()->store.insert(2,pending("RESUME_ACTION",OTHER))).isInstanceOf(DataAccessException.class);
        assertThat(count("workflow_instance")).isEqualTo(1);assertThat(count("audit_event")).isEqualTo(1);
    }

    @Test void twoConcurrentCancellationsProduceOneTransitionAndOneAudit() throws Exception {
        store.insert(1,pending("race",SESSION));var start=new CountDownLatch(1);var executor=Executors.newFixedThreadPool(2);
        try {
            var first=executor.submit(()->{if(!start.await(5,TimeUnit.SECONDS))throw new IllegalStateException("fixture barrier timeout");return store.transition(1,SESSION,"race","PENDING","CANCELLED",null);});
            var second=executor.submit(()->{if(!start.await(5,TimeUnit.SECONDS))throw new IllegalStateException("fixture barrier timeout");return store.transition(1,SESSION,"race","PENDING","CANCELLED",null);});
            start.countDown();assertThat(List.of(first.get(20,TimeUnit.SECONDS),second.get(20,TimeUnit.SECONDS))).containsExactlyInAnyOrder(true,false);
            assertThat(revision("race")).isEqualTo(1);assertThat(count("audit_event")).isEqualTo(2);
            assertThat(store.get(1,SESSION,"race").getStatus()).isEqualTo("CANCELLED");
        } finally {executor.shutdownNow();if(!executor.awaitTermination(20,TimeUnit.SECONDS))throw new IllegalStateException("Fixture cancellation threads did not stop");}
    }

    @Test void auditFailureRollsBackBothNewActionAndExistingStateChange() {
        store.insert(1,pending("kept",SESSION));String before=jdbc.queryForObject("SELECT payload_json FROM workflow_instance",String.class);
        jdbc.execute("CREATE TRIGGER fixture_refuse_legacy_audit BEFORE INSERT ON audit_event FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture audit unavailable'");
        assertThatThrownBy(()->store.insert(1,pending("rolled-back",SESSION))).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->store.transition(1,SESSION,"kept","PENDING","CANCELLED","new error")).isInstanceOf(DataAccessException.class);
        assertThat(count("workflow_instance")).isEqualTo(1);assertThat(count("audit_event")).isEqualTo(1);assertThat(revision("kept")).isZero();
        assertThat(store.get(1,SESSION,"kept").getStatus()).isEqualTo("PENDING");
        assertThat(jdbc.queryForObject("SELECT payload_json FROM workflow_instance",String.class)).isEqualTo(before);
    }

    @ParameterizedTest @ValueSource(strings={"missing-session","wrong-kind","trailing-kind"})
    void insertAndUpdateGuardsRejectInvalidOrdinarySessionReferences(String change) throws Exception {
        String kind=change.equals("wrong-kind")?"DIGEST_RUN":change.equals("trailing-kind")?"LEGACY_CHAT_ACTION ":"LEGACY_CHAT_ACTION";
        String ref=change.equals("missing-session")?null:SESSION;
        String body=json.writeValueAsString(new LegacyChatActionStore.PendingV1("OLD_OPERATION",RAW,null,null,null,null,null,null));
        assertThatThrownBy(()->jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,
                  resource_type,resource_id,chat_action_session_id,status,payload_version,payload_json)
                VALUES(?,?,'LEGACY_CHAT_ACTION','guard','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',1,
                  'CHAT_ACTION','guard',?,'PENDING',1,?)
                """,UUID.randomUUID().toString(),kind,ref,body)).isInstanceOf(DataAccessException.class)
                .hasStackTraceContaining("Legacy chat action session does not match its workflow kind");
        assertThat(count("workflow_instance")).isZero();
        store.insert(1,pending("guard-update",SESSION));
        assertThatThrownBy(()->jdbc.update("UPDATE workflow_instance SET kind=?,chat_action_session_id=? WHERE request_id='guard-update'",kind,ref))
                .isInstanceOf(DataAccessException.class).hasStackTraceContaining("Legacy chat action session does not match its workflow kind");
        assertThat(store.get(1,SESSION,"guard-update").getStatus()).isEqualTo("PENDING");
    }

    @Test void realForeignKeyRejectsMissingSessionEvenWhenWorkflowShapeIsValid() {
        store.insert(1,pending("fk",SESSION));
        assertThatThrownBy(()->jdbc.update("UPDATE workflow_instance SET chat_action_session_id='absent-session' WHERE request_id='fk'"))
                .isInstanceOf(DataAccessException.class).hasStackTraceContaining("fk_workflow_legacy_chat_session");
        assertThat(store.get(1,SESSION,"fk").getSessionId()).isEqualTo(SESSION);
    }

    @Test void malformedHistoricalProtocolCannotBeSilentlyReadWithMissingNullableFields() {
        store.insert(1,pending("missing-payload-field",SESSION));
        jdbc.update("UPDATE workflow_instance SET payload_json=JSON_REMOVE(payload_json,'$.errorMessage') WHERE request_id='missing-payload-field'");
        assertThatThrownBy(()->store.get(1,SESSION,"missing-payload-field")).isInstanceOf(IllegalStateException.class);
    }

    @Test void publicLegacyConfirmationStaysGoneAndCancellationIsAtomicWithItsMessage() {
        store.insert(1,pending("public-boundary",SESSION));
        var sessions=mock(ChatSessionService.class);var tenant=new TenantContext(1L,"alice");
        doAnswer(invocation->{String session=invocation.getArgument(1);Long owner=jdbc.queryForObject("SELECT user_id FROM chat_session WHERE session_id=?",Long.class,session);
            if(owner==null||owner!=1)throw new SecurityException("not current owner");return null;}).when(sessions).verifySessionOwner(eq("alice"),anyString());
        when(sessions.getPendingAction(eq(tenant),anyString(),anyString())).thenAnswer(invocation->store.get(1,invocation.getArgument(1),invocation.getArgument(2)));
        when(sessions.transitionPendingAction(eq(tenant),anyString(),anyString(),anyString(),anyString(),nullable(String.class)))
                .thenAnswer(invocation->store.transition(1,invocation.getArgument(1),invocation.getArgument(2),invocation.getArgument(3),invocation.getArgument(4),invocation.getArgument(5)));
        when(sessions.appendAssistantMessage(eq(tenant),anyString(),anyString(),anyString(),anyString(),nullable(String.class))).thenAnswer(invocation->{
            String session=invocation.getArgument(1),body=invocation.getArgument(2);
            jdbc.update("INSERT INTO chat_message(session_id,role,message_type,content) VALUES(?,'assistant','TEXT',?)",session,body);
            var response=new ChatMessageResponse();response.setContent(body);response.setRole("assistant");return response;});
        @SuppressWarnings("unchecked") ObjectProvider<AgentConversationApi> agents=mock(ObjectProvider.class);
        var service=new AgentScopeChatServiceImpl(sessions,agents,mock(RagKnowledgeService.class),mock(Mem0Client.class),Runnable::run,new ChatAssistantProperties(),json);
        var authorities=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L,"alice","fixture",authorities),null,authorities));
        var request=new ChatConfirmActionRequest();request.setSessionId(SESSION);request.setActionId("public-boundary");request.setConfirmed(true);
        assertThatThrownBy(()->tx.execute(status->service.confirmAction("alice",request))).isInstanceOfSatisfying(BusinessException.class,error->assertThat(error.getCode()).isEqualTo(410));
        assertThat(store.get(1,SESSION,"public-boundary").getStatus()).isEqualTo("PENDING");assertThat(count("chat_message")).isZero();
        request.setConfirmed(false);
        jdbc.execute("CREATE TRIGGER fixture_refuse_cancel_message BEFORE INSERT ON chat_message FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture message unavailable'");
        assertThatThrownBy(()->tx.execute(status->service.confirmAction("alice",request))).isInstanceOf(DataAccessException.class);
        assertThat(store.get(1,SESSION,"public-boundary").getStatus()).isEqualTo("PENDING");assertThat(revision("public-boundary")).isZero();assertThat(count("audit_event")).isEqualTo(1);
        jdbc.execute("DROP TRIGGER fixture_refuse_cancel_message");
        assertThat(tx.execute(status->service.confirmAction("alice",request)).getContent()).isEqualTo("已取消旧版待确认动作");
        assertThatThrownBy(()->tx.execute(status->service.confirmAction("alice",request))).isInstanceOfSatisfying(BusinessException.class,error->assertThat(error.getCode()).isEqualTo(409));
        assertThat(count("chat_message")).isEqualTo(1);assertThat(count("audit_event")).isEqualTo(2);verifyNoInteractions(agents);
    }
}
