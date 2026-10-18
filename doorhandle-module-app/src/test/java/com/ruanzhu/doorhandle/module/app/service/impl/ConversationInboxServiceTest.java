package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.app.service.*;
import com.ruanzhu.doorhandle.module.system.security.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.security.core.context.SecurityContextHolder;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.awaitility.Awaitility.await;
import static org.mockito.Mockito.*;

@Timeout(15)
class ConversationInboxServiceTest {
    final AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),bob=new AgentActor(2,"bob",AgentActor.Role.SUPERVISOR);
    JdbcTemplate jdbc;ChatSessionService sessions;ChatConversationService chat;BusinessUserDirectory users;AgentConversationControlApi control;
    ConversationInboxService inbox;final List<ConversationInboxService> services=new ArrayList<>();
    javax.sql.DataSource source(){return new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");}
    @BeforeEach void setup()throws Exception{
        jdbc=new JdbcTemplate(source());
        String ddl=Files.readString(Path.of("../sql/mysql/migration-V36-conversation-inbox.sql")).replaceAll("(?m)^--.*$", "").replaceAll(" COLLATE utf8mb4_bin","").replaceAll(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","")
                .replaceAll("(?m)^(\\s*)UNIQUE KEY (\\w+)\\s*(\\([^\\n]+\\))", "$1CONSTRAINT $2 UNIQUE $3").replaceAll("(?m)^\\s*KEY .*\\n","").replaceAll(",\\s*\\)",")").replace(" COLLATE=utf8mb4_bin","");
        for(String sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
        sessions=mock(ChatSessionService.class);chat=mock(ChatConversationService.class);users=mock(BusinessUserDirectory.class);control=mock(AgentConversationControlApi.class);
        doCallRealMethod().when(chat).handleQueuedMessage(anyString(),any(),anyString(),anyString());
        when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));when(users.current(2,"bob")).thenReturn(new BusinessUserDirectory.Identity(2,"bob",true));
        when(sessions.resolveTenantForSystemCallback(anyString())).thenAnswer(inv->new TenantContext("bob".equals(inv.getArgument(0))?2L:1L,"bob".equals(inv.getArgument(0))?"bob":"alice"));
        when(control.inspect(any(),anyString())).thenAnswer(inv->new AgentConversationControlApi.View(inv.getArgument(1),null,"IDLE",0,false,""));when(control.maxRunSeconds()).thenReturn(1800);inbox=create();
    }
    ConversationInboxService create(){var provider=mock(ObjectProvider.class);when(provider.getIfAvailable()).thenReturn(control);when(provider.getObject()).thenReturn(control);var service=new ConversationInboxService(jdbc,new DataSourceTransactionManager(jdbc.getDataSource()),sessions,chat,users,provider);service.schema();services.add(service);return service;}
    @AfterEach void close(){services.forEach(ConversationInboxService::close);SecurityContextHolder.clearContext();if(jdbc!=null&&jdbc.getDataSource() instanceof com.zaxxer.hikari.HikariDataSource pool)pool.close();}
    ConversationInboxService.Item enqueue(String text){return inbox.enqueue(alice,"s1",UUID.randomUUID().toString(),"NEXT_TURN",text);}
    String status(String id){return jdbc.queryForObject("SELECT status FROM agent_conversation_input WHERE input_id=?",String.class,id);}
    Duration executionWait(){return Duration.ofSeconds(3);}
    void completed(String id){await().atMost(executionWait()).until(()->"COMPLETED".equals(status(id)));}
    void active(){when(control.inspect(any(),anyString())).thenReturn(new AgentConversationControlApi.View("s1","run-1","RUNNING",0,true,""));}
    @Test void promotingAPendingMessageKeepsItsIdentityDeadlineAndOriginalSubmissionReceipt(){
        var queued=enqueue("PROMOTE_ME");var deadline=jdbc.queryForMap("SELECT expires_at FROM agent_conversation_input").get("expires_at");active();
        var promoted=inbox.steer(alice,"s1",queued.id(),0,"run-1");
        assertThat(promoted).satisfies(item->{assertThat(item.id()).isEqualTo(queued.id());assertThat(item.mode()).isEqualTo("NEXT_STEP");assertThat(item.targetRunId()).isEqualTo("run-1");assertThat(item.revision()).isEqualTo(1);});
        assertThat(jdbc.queryForMap("SELECT expires_at FROM agent_conversation_input").get("expires_at")).isEqualTo(deadline);
        assertThat(inbox.enqueue(alice,"s1",queued.id(),"NEXT_TURN","PROMOTE_ME").id()).isEqualTo(queued.id());
        inbox.dispatch();verifyNoInteractions(chat);
        assertThat(inbox.take(alice,"s1","run-1")).containsExactly(new AgentSteeringInboxApi.Input(queued.id(),"PROMOTE_ME"));assertThat(inbox.take(alice,"s1","run-1")).isEmpty();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input",Integer.class)).isEqualTo(1);
        assertThat(jdbc.queryForList("SELECT * FROM agent_conversation_input_audit WHERE action='PROMOTED_NEXT_STEP'")).hasSize(1).allSatisfy(row->assertThat(row.toString()).doesNotContain("PROMOTE_ME"));
    }
    @Test void promotionRejectsStaleEditsWithdrawalsAndDifferentRuns(){
        active();var queued=enqueue("before");inbox.change(alice,"s1",queued.id(),0,"after");
        assertThatThrownBy(()->inbox.steer(alice,"s1",queued.id(),0,"run-1")).hasMessageContaining("409");
        assertThatThrownBy(()->inbox.steer(alice,"s1",queued.id(),1,"run-2")).hasMessageContaining("409");
        inbox.change(alice,"s1",queued.id(),1,null);assertThatThrownBy(()->inbox.steer(alice,"s1",queued.id(),2,"run-1")).hasMessageContaining("409");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input_audit WHERE action='PROMOTED_NEXT_STEP'",Integer.class)).isZero();
    }
    @Test void promotionRequiresAnActiveRunAnOwnedSessionAndUnexpiredInput(){
        var queued=enqueue("pending");assertThatThrownBy(()->inbox.steer(alice,"s1",queued.id(),0,"run-1")).hasMessageContaining("409");active();
        assertThatThrownBy(()->inbox.steer(bob,"bob",queued.id(),0,"run-1")).hasMessageContaining("404");
        assertThatThrownBy(()->inbox.steer(alice,"other-session",queued.id(),0,"run-1")).hasMessageContaining("404");
        jdbc.update("UPDATE agent_conversation_input SET expires_at=?",LocalDateTime.now().minusDays(1));assertThatThrownBy(()->inbox.steer(alice,"s1",queued.id(),0,"run-1")).hasMessageContaining("409");
        assertThat(inbox.list(alice,"s1").get(0).mode()).isEqualTo("NEXT_TURN");
    }
    @Test void promotionUsesTheSameSteeringQuotaAndLengthLimit(){
        active();var longInput=enqueue("x".repeat(4001));assertThatThrownBy(()->inbox.steer(alice,"s1",longInput.id(),0,"run-1")).hasMessageContaining("400");
        for(int i=0;i<6;i++)inbox.enqueue(alice,"s1",UUID.randomUUID().toString(),"NEXT_STEP","focus-"+i);
        var queued=enqueue("pending");assertThatThrownBy(()->inbox.steer(alice,"s1",queued.id(),0,"run-1")).hasMessageContaining("429");assertThat(inbox.list(alice,"s1").get(0).mode()).isEqualTo("NEXT_TURN");
    }
    @Test void promotionRollsBackWhenItsAuditCannotBeStored(){
        active();var queued=enqueue("PRIVATE");jdbc.execute("ALTER TABLE agent_conversation_input_audit ADD CONSTRAINT deny_promotion CHECK(action<>'PROMOTED_NEXT_STEP')");
        assertThatThrownBy(()->inbox.steer(alice,"s1",queued.id(),0,"run-1")).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(inbox.list(alice,"s1").get(0)).satisfies(item->{assertThat(item.mode()).isEqualTo("NEXT_TURN");assertThat(item.revision()).isZero();assertThat(item.targetRunId()).isNull();});
    }
    @Test void explicitInputIsDurableIdempotentAndAuditContainsNoBody(){
        var item=enqueue("PRIVATE_INPUT");var again=inbox.enqueue(alice,"s1",item.id(),"NEXT_TURN","PRIVATE_INPUT");assertThat(again.id()).isEqualTo(item.id());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input",Integer.class)).isEqualTo(1);assertThat(jdbc.queryForMap("SELECT * FROM agent_conversation_input_audit").toString()).doesNotContain("PRIVATE_INPUT");
        assertThatThrownBy(()->inbox.enqueue(alice,"s1",item.id(),"NEXT_STEP","PRIVATE_INPUT")).hasMessageContaining("409");
    }
    @Test void editsAndWithdrawalRequireTheCurrentVersionAndPreserveOnlyHashesAfterWithdrawal(){
        var queued=enqueue("first");var edited=inbox.change(alice,"s1",queued.id(),0,"edited");assertThat(edited.revision()).isEqualTo(1);
        assertThatThrownBy(()->inbox.change(alice,"s1",queued.id(),0,null)).hasMessageContaining("409");
        assertThat(inbox.change(alice,"s1",queued.id(),1,null)).satisfies(item->{assertThat(item.status()).isEqualTo("CANCELLED");assertThat(item.content()).isEmpty();});
        inbox.dispatch();verifyNoInteractions(chat);
    }
    @Test void stableAccountIdProtectsMessagesEvenWhenNoThreadSecurityContextExists(){
        var queued=enqueue("PRIVATE_INPUT");assertThatThrownBy(()->inbox.list(bob,"s1")).hasMessageContaining("404");assertThatThrownBy(()->inbox.change(bob,"bob",queued.id(),0,null)).hasMessageContaining("404");assertThat(status(queued.id())).isEqualTo("QUEUED");
    }
    @Test void steeringIsDeliveredOnceAndAddedToConversationHistoryWithStableTenant(){
        active();var queued=inbox.enqueue(alice,"s1",UUID.randomUUID().toString(),"NEXT_STEP","FOCUS");
        assertThat(inbox.take(alice,"s1","other-run")).isEmpty();assertThat(inbox.take(alice,"s1","run-1")).containsExactly(new AgentSteeringInboxApi.Input(queued.id(),"FOCUS"));assertThat(inbox.take(alice,"s1","run-1")).isEmpty();
        verify(sessions).appendUserMessage(new TenantContext(1L,"alice"),"s1","FOCUS");assertThat(status(queued.id())).isEqualTo("APPLIED");assertThat(inbox.list(alice,"s1").get(0).content()).isEmpty();
    }
    @Test void aSteerThatMissedTheFinalBoundaryBecomesANormalNextTurn(){
        active();var queued=inbox.enqueue(alice,"s1",UUID.randomUUID().toString(),"NEXT_STEP","LATE_STEERING");
        when(control.inspect(any(),anyString())).thenReturn(new AgentConversationControlApi.View("s1",null,"IDLE",0,false,""));inbox.dispatch();completed(queued.id());
        assertThat(jdbc.queryForObject("SELECT mode FROM agent_conversation_input",String.class)).isEqualTo("NEXT_TURN");verify(chat).handleUserMessage(eq("alice"),argThat(request->"LATE_STEERING".equals(request.getContent())));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input_audit WHERE action='FALLBACK_NEXT_TURN'",Integer.class)).isEqualTo(1);
    }
    @Test void concurrentDispatchersCannotRunTwoInputsOfTheSameSession()throws Exception{
        var entered=new CountDownLatch(1);var release=new CountDownLatch(1);when(chat.handleUserMessage(anyString(),any())).thenAnswer(inv->{entered.countDown();release.await(5,TimeUnit.SECONDS);return null;});
        var first=enqueue("one");var second=enqueue("two");var other=create();try{inbox.dispatch();assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();other.dispatch();assertThat(status(second.id())).isEqualTo("QUEUED");verify(chat,times(1)).handleUserMessage(anyString(),any());release.countDown();completed(first.id());other.dispatch();completed(second.id());}finally{release.countDown();}
    }
    @Test void queuedMessagesSurviveRestartButStartedMessagesAreNotReplayed(){
        var queued=enqueue("after-restart");inbox.close();var restarted=create();restarted.dispatch();completed(queued.id());
        var started=restarted.enqueue(alice,"s1",UUID.randomUUID().toString(),"NEXT_TURN","do-not-replay");jdbc.update("UPDATE agent_conversation_input SET status='STARTED',active_slot=1,content='' WHERE input_id=?",started.id());
        restarted.dispatch();verify(chat,times(1)).handleUserMessage(anyString(),any());assertThat(status(started.id())).isEqualTo("STARTED");
    }
    @Test void backgroundExecutionUsesFreshRoleAndNeverStoresCredentials(){
        var queued=enqueue("query");when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",true));
        when(chat.handleUserMessage(anyString(),any())).thenAnswer(inv->{var principal=(TenantPrincipal)SecurityContextHolder.getContext().getAuthentication().getPrincipal();assertThat(principal.userId()).isEqualTo(1L);assertThat(principal.getPassword()).isEmpty();assertThat(principal.authorities()).extracting("authority").containsExactly("ROLE_SUPERVISOR");return null;});
        inbox.dispatch();completed(queued.id());assertThat(jdbc.queryForMap("SELECT * FROM agent_conversation_input").toString()).doesNotContain("ROLE_SUPERVISOR","password");
    }
    @Test void failedAdmissionAuditRollsBackTheInput(){
        jdbc.execute("ALTER TABLE agent_conversation_input_audit ADD CONSTRAINT deny_admission CHECK(action<>'ENQUEUED')");assertThatThrownBy(()->enqueue("PRIVATE")).isInstanceOf(org.springframework.dao.DataAccessException.class);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input",Integer.class)).isZero();
    }
    @Test void deliveryAuditFailureRollsBackBothQueuedStateAndConversationAppend(){
        active();var queued=inbox.enqueue(alice,"s1",UUID.randomUUID().toString(),"NEXT_STEP","PRIVATE");jdbc.execute("CREATE TABLE fixture_chat(body VARCHAR(8000))");
        when(sessions.appendUserMessage(any(TenantContext.class),anyString(),anyString())).thenAnswer(inv->{jdbc.update("INSERT INTO fixture_chat(body) VALUES(?)",inv.<String>getArgument(2));return null;});
        jdbc.execute("ALTER TABLE agent_conversation_input_audit ADD CONSTRAINT deny_delivery CHECK(action<>'APPLIED_AT_BOUNDARY')");
        assertThatThrownBy(()->inbox.take(alice,"s1","run-1")).isInstanceOf(org.springframework.dao.DataAccessException.class);assertThat(status(queued.id())).isEqualTo("QUEUED");assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM fixture_chat",Integer.class)).isZero();
    }
    @Test void expirationClearsPendingBodyAndPreventsExecution(){var queued=enqueue("EXPIRED_PRIVATE");jdbc.update("UPDATE agent_conversation_input SET expires_at=?",LocalDateTime.now().minusDays(1));inbox.dispatch();assertThat(status(queued.id())).isEqualTo("EXPIRED");assertThat(inbox.list(alice,"s1").get(0).content()).isEmpty();verifyNoInteractions(chat);}
    @Test void accountRevocationAndExecutionFailureNeverAutomaticallyRetry(){var queued=enqueue("first");when(users.current(1,"alice")).thenThrow(new SecurityException());inbox.dispatch();assertThat(status(queued.id())).isEqualTo("FAILED");verifyNoInteractions(chat);}
    @Test void failedExecutionIsTerminal(){var queued=enqueue("query");when(chat.handleUserMessage(anyString(),any())).thenThrow(new IllegalStateException("PRIVATE_ERROR"));inbox.dispatch();await().atMost(Duration.ofSeconds(3)).until(()->"FAILED".equals(status(queued.id())));inbox.dispatch();verify(chat,times(1)).handleUserMessage(anyString(),any());assertThat(jdbc.queryForList("SELECT * FROM agent_conversation_input_audit").toString()).doesNotContain("PRIVATE_ERROR");}
    @Test void pausedSessionsKeepQueuedMessagesWaiting(){var queued=enqueue("wait");when(control.inspect(any(),anyString())).thenReturn(new AgentConversationControlApi.View("s1","run-1","PAUSED",2,true,""));inbox.dispatch();assertThat(status(queued.id())).isEqualTo("QUEUED");verifyNoInteractions(chat);}
    @Test void missingMigrationFailsBeforeEnablingDispatch(){jdbc.execute("DROP TABLE agent_conversation_input_audit");assertThatThrownBy(inbox::schema).hasMessageContaining("migration-V36-conversation-inbox.sql");}
    @Test void actualSchedulerDispatchesPersistedInputAfterApplicationReadiness(){var queued=enqueue("ready");inbox.startDispatcher();completed(queued.id());verify(chat,times(1)).handleUserMessage(anyString(),any());}
    @Test void lastQuotaSlotIsSerializedAcrossConcurrentRequests()throws Exception{
        for(int i=0;i<15;i++)enqueue("pending-"+i);var workers=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try{Callable<Integer> attempt=()->{start.await();try{enqueue("last");return 1;}catch(org.springframework.web.server.ResponseStatusException error){assertThat(error.getStatusCode().value()).isEqualTo(429);return 0;}};var first=workers.submit(attempt);var second=workers.submit(attempt);start.countDown();assertThat(first.get(4,TimeUnit.SECONDS)+second.get(4,TimeUnit.SECONDS)).isEqualTo(1);}finally{workers.shutdownNow();}
    }
    @Test void twoBusyAccountsCannotHideTheNextReadyAccountBehindThirtyTwoInputs(){
        var charlie=new AgentActor(3,"charlie",AgentActor.Role.INSPECTOR);
        when(users.current(3,"charlie")).thenReturn(new BusinessUserDirectory.Identity(3,"charlie",false));
        when(sessions.resolveTenantForSystemCallback("charlie")).thenReturn(new TenantContext(3L,"charlie"));
        when(control.inspect(any(),anyString())).thenAnswer(inv->{AgentActor actor=inv.getArgument(0);String session=inv.getArgument(1);return new AgentConversationControlApi.View(session,actor.userId()==3?null:"busy-run",actor.userId()==3?"IDLE":"RUNNING",0,false,"");});
        for(int i=0;i<16;i++)enqueue("alice-wait-"+i);
        for(int i=0;i<16;i++)inbox.enqueue(bob,"bob",UUID.randomUUID().toString(),"NEXT_TURN","bob-wait-"+i);
        var ready=inbox.enqueue(charlie,"charlie",UUID.randomUUID().toString(),"NEXT_TURN","ready-charlie");
        inbox.dispatch();completed(ready.id());
        verify(chat,times(1)).handleUserMessage(eq("charlie"),argThat(request->"ready-charlie".equals(request.getContent())));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input WHERE status='QUEUED'",Integer.class)).isEqualTo(32);
    }
    @Test void readyAccountsAlternateWhileTheirOwnMessagesStayInOrder(){
        var delivered=new CopyOnWriteArrayList<String>();
        when(chat.handleUserMessage(anyString(),any())).thenAnswer(inv->{delivered.add(inv.getArgument(0)+":"+((com.ruanzhu.doorhandle.module.app.dto.chat.ChatSendMessageRequest)inv.getArgument(1)).getContent());return null;});
        var a1=enqueue("first");var a2=enqueue("second");var a3=enqueue("third");
        var b1=inbox.enqueue(bob,"bob",UUID.randomUUID().toString(),"NEXT_TURN","first");
        var b2=inbox.enqueue(bob,"bob",UUID.randomUUID().toString(),"NEXT_TURN","second");
        inbox.dispatch();completed(a1.id());inbox.dispatch();completed(b1.id());
        inbox.dispatch();completed(a2.id());inbox.dispatch();completed(b2.id());inbox.dispatch();completed(a3.id());
        assertThat(delivered).containsExactly("alice:first","bob:first","alice:second","bob:second","alice:third");
    }
    @Test void moreThanThirtyTwoBusyOwnersAreVisitedInBoundedPages(){
        when(control.inspect(any(),anyString())).thenAnswer(inv->{AgentActor actor=inv.getArgument(0);String session=inv.getArgument(1);return new AgentConversationControlApi.View(session,actor.userId()==34?null:"busy-run",actor.userId()==34?"IDLE":"RUNNING",0,false,"");});
        ConversationInboxService.Item ready=null;
        for(long user=1;user<=34;user++){
            String name="owner-"+user,session="session-"+user;
            var actor=new AgentActor(user,name,AgentActor.Role.INSPECTOR);
            when(users.current(user,name)).thenReturn(new BusinessUserDirectory.Identity(user,name,false));
            when(sessions.resolveTenantForSystemCallback(session)).thenReturn(new TenantContext(user,name));
            ready=inbox.enqueue(actor,session,UUID.randomUUID().toString(),"NEXT_TURN","page-test");
        }
        inbox.dispatch();verifyNoInteractions(chat);inbox.dispatch();completed(ready.id());
        verify(chat,times(1)).handleUserMessage(eq("owner-34"),any());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input WHERE status='QUEUED'",Integer.class)).isEqualTo(33);
    }
    @Test void newlyArrivingAccountsCannotKeepTheRoundFromReturningToExistingAccounts(){
        var first=enqueue("first");var second=enqueue("second");
        var b=inbox.enqueue(bob,"bob",UUID.randomUUID().toString(),"NEXT_TURN","bob");
        inbox.dispatch();completed(first.id());
        when(users.current(3,"charlie")).thenReturn(new BusinessUserDirectory.Identity(3,"charlie",false));
        when(sessions.resolveTenantForSystemCallback("charlie")).thenReturn(new TenantContext(3L,"charlie"));
        var later=inbox.enqueue(new AgentActor(3,"charlie",AgentActor.Role.INSPECTOR),"charlie",UUID.randomUUID().toString(),"NEXT_TURN","later");
        inbox.dispatch();completed(b.id());inbox.dispatch();completed(second.id());
        assertThat(status(later.id())).isEqualTo("QUEUED");
        inbox.dispatch();completed(later.id());
    }
    @Test void gracefulShutdownLetsAnAdmittedShortExecutionFinishBeforeClosingPersistence()throws Exception{
        var entered=new CountDownLatch(1);var release=new CountDownLatch(1);
        var interrupted=new java.util.concurrent.atomic.AtomicBoolean();
        when(chat.handleUserMessage(anyString(),any())).thenAnswer(inv->{entered.countDown();try{release.await(3,TimeUnit.SECONDS);}catch(InterruptedException error){interrupted.set(true);throw new IllegalStateException(error);}return null;});
        var input=enqueue("finish-before-shutdown");inbox.dispatch();assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();
        var closer=Executors.newSingleThreadExecutor();
        try{
            var closing=closer.submit(inbox::close);
            await().during(Duration.ofMillis(150)).atMost(Duration.ofSeconds(1)).until(()->!closing.isDone());
            release.countDown();closing.get(3,TimeUnit.SECONDS);
            assertThat(status(input.id())).isEqualTo("COMPLETED");assertThat(interrupted).isFalse();
        }finally{release.countDown();closer.shutdownNow();}
    }
}
