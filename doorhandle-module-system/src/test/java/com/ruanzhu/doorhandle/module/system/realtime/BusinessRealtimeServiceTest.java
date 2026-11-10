package com.ruanzhu.doorhandle.module.system.realtime;

import com.ruanzhu.doorhandle.contracts.collaboration.BusinessResourceAccess;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessResourceChanged;
import com.ruanzhu.doorhandle.contracts.security.*;
import org.junit.jupiter.api.*;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.core.env.MapPropertySource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.embedded.EmbeddedDatabase;
import org.springframework.jdbc.datasource.embedded.EmbeddedDatabaseBuilder;
import org.springframework.jdbc.datasource.embedded.EmbeddedDatabaseType;
import org.springframework.security.authentication.CredentialsExpiredException;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.event.TransactionalEventListenerFactory;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
import static org.assertj.core.api.Assertions.*;

/** Source-stage ECS tests. Spring transaction events use actual JDBC commit/rollback on an isolated in-memory database. */
class BusinessRealtimeServiceTest {
    final RealtimeProperties properties=new RealtimeProperties();
    final Map<String,LoginSessionAccess.Session> live=new ConcurrentHashMap<>();
    final Map<Long,Set<String>> grants=new ConcurrentHashMap<>();
    final List<BlockingTransport> blocked=new CopyOnWriteArrayList<>();
    final AtomicInteger next=new AtomicInteger();
    BusinessRealtimeService service;
    AnnotationConfigApplicationContext context;
    EmbeddedDatabase database;
    TransactionTemplate transaction;
    @BeforeEach void setup(){
        LoginSessionAccess sessions=(id,name,digest)->{
            var current=live.get(digest);
            if(current==null||current.userId()!=id||!Objects.equals(current.username(),name)||!current.expiresAt().isAfter(Instant.now()))throw new CredentialsExpiredException("revoked");
            return current;
        };
        BusinessResourceAccess access=(actor,scope,domain,type,id)->grants.getOrDefault(actor.userId(),Set.of()).contains(id);
        service=new BusinessRealtimeService(sessions,List.of(access),properties);
        database=new EmbeddedDatabaseBuilder().generateUniqueName(true).setType(EmbeddedDatabaseType.H2).build();
        transaction=new TransactionTemplate(new DataSourceTransactionManager(database));
        context=new AnnotationConfigApplicationContext();
        context.getEnvironment().getPropertySources().addFirst(new MapPropertySource("realtime-test",Map.of("collaboration.realtime.enabled","true")));
        context.registerBean(TransactionalEventListenerFactory.class,TransactionalEventListenerFactory::new);
        context.registerBean(BusinessRealtimeService.class,()->service);context.refresh();
    }
    @AfterEach void cleanup()throws Exception{
        for(var channel:blocked)channel.release.countDown();
        if(context!=null)context.close();if(service!=null){service.stop();await(()->service.activeSlots()==0);}
        if(database!=null)database.shutdown();
    }
    LoginSessionAccess.Session session(long id){
        String digest=String.format("%064x",next.incrementAndGet());
        var value=new LoginSessionAccess.Session(id,"user-"+id,"SUPERVISOR",digest,"context-"+digest,Instant.now().plusSeconds(86400));
        live.put(digest,value);grants.putIfAbsent(id,Set.of("42","43"));return value;
    }
    BusinessRealtimeService.Connection connect(LoginSessionAccess.Session session,RecordingTransport channel)throws Exception{
        var connection=service.register(session,Instant.now().plusSeconds(30),channel);connection.begin();
        assertThat(channel.take("resync-required").body().get("reason")).isEqualTo("CONNECTED");return connection;
    }
    BusinessResourceChanged change(String eventId,String scope,long actor,String resource){
        return new BusinessResourceChanged(eventId,"audit-"+eventId,scope,"QUALITY","TASK",resource,"7","UPDATE","request-"+eventId,actor,Instant.now());
    }
    void committed(BusinessResourceChanged event){transaction.executeWithoutResult(status->context.publishEvent(event));}
    static void await(BooleanSupplier condition)throws Exception{
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
        while(!condition.getAsBoolean()&&System.nanoTime()<deadline)Thread.sleep(10);
        assertThat(condition.getAsBoolean()).isTrue();
    }
    record Sent(String name,String id,Map<String,Object> body){}
    static class RecordingTransport implements BusinessRealtimeService.Transport {
        final BlockingQueue<Sent> incoming=new LinkedBlockingQueue<>();
        final List<Sent> sent=new CopyOnWriteArrayList<>();
        final AtomicInteger completed=new AtomicInteger();
        public void send(String name,String id,Map<String,Object> body)throws Exception{
            var value=new Sent(name,id,Map.copyOf(body));sent.add(value);incoming.add(value);
        }
        public void complete(){completed.incrementAndGet();}
        Sent take(String name)throws Exception{
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
            while(System.nanoTime()<deadline){var value=incoming.poll(100,TimeUnit.MILLISECONDS);if(value!=null&&name.equals(value.name()))return value;}
            throw new AssertionError("Expected SSE event: "+name);
        }
        boolean resource(String eventId){return sent.stream().anyMatch(e->"resource-changed".equals(e.name())&&eventId.equals(e.id()));}
    }
    static final class BlockingTransport extends RecordingTransport {
        final CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        @Override public void send(String name,String id,Map<String,Object> body)throws Exception{
            entered.countDown();
            while(release.getCount()>0)try{release.await(100,TimeUnit.MILLISECONDS);}catch(InterruptedException expected){/* Simulates a socket write that ignores interrupt. */}
            super.send(name,id,body);
        }
    }
    @Test void transactionCommitPublishesAndRollbackNeverPublishes()throws Exception{
        var channel=new RecordingTransport();connect(session(1),channel);var success=change("commit","ENTERPRISE",1,"42");
        transaction.executeWithoutResult(status->{context.publishEvent(success);
            try{assertThat(channel.incoming.poll(150,TimeUnit.MILLISECONDS)).isNull();}catch(InterruptedException interrupted){throw new IllegalStateException(interrupted);}
        });
        assertThat(channel.take("resource-changed").id()).isEqualTo("commit");
        assertThatThrownBy(()->transaction.executeWithoutResult(status->{context.publishEvent(change("rollback","ENTERPRISE",1,"42"));throw new IllegalStateException("rollback");})).isInstanceOf(IllegalStateException.class);
        assertThat(channel.incoming.poll(150,TimeUnit.MILLISECONDS)).isNull();assertThat(channel.resource("rollback")).isFalse();
    }
    @Test void sameRoleUsersAndIndependentDevicesRemainIsolatedDuringScopedRevocation()throws Exception{
        var a=session(1);var device=session(1);var other=session(2);
        var ca=new RecordingTransport();var cb=new RecordingTransport();var cc=new RecordingTransport();connect(a,ca);connect(device,cb);connect(other,cc);
        transaction.executeWithoutResult(status->{context.publishEvent(new LoginSessionRevoked(1,a.sessionDigest()));assertThat(service.activeSlots()).isEqualTo(3);});
        await(()->ca.completed.get()==1&&service.activeSlots()==2);assertThat(cb.completed.get()).isZero();assertThat(cc.completed.get()).isZero();
        committed(change("independent","ENTERPRISE",2,"42"));assertThat(cb.take("resource-changed").id()).isEqualTo("independent");assertThat(cc.take("resource-changed").id()).isEqualTo("independent");assertThat(ca.resource("independent")).isFalse();
        transaction.executeWithoutResult(status->context.publishEvent(new AccountAccessChanged(1)));await(()->cb.completed.get()==1&&service.activeSlots()==1);assertThat(cc.completed.get()).isZero();
    }
    @Test void rollbackOfAccountRevocationKeepsExistingConnections()throws Exception{
        var channel=new RecordingTransport();connect(session(1),channel);
        assertThatThrownBy(()->transaction.executeWithoutResult(status->{context.publishEvent(new AccountAccessChanged(1));throw new IllegalStateException("rollback");})).isInstanceOf(IllegalStateException.class);
        committed(change("still-live","ENTERPRISE",1,"42"));assertThat(channel.take("resource-changed").id()).isEqualTo("still-live");assertThat(channel.completed.get()).isZero();
    }
    @Test void privateEventsOnlyReachTheOwnersAuthorizedDevicesAndContainNoFieldValues()throws Exception{
        var owner=session(1);var other=session(2);var a=new RecordingTransport();var b=new RecordingTransport();connect(owner,a);connect(other,b);
        committed(change("private","PRIVATE",1,"42"));var sent=a.take("resource-changed");
        assertThat(sent.body()).containsEntry("accountContext",owner.accountContext()).containsEntry("resourceId","42");
        assertThat(sent.body().keySet()).containsExactlyInAnyOrder("schemaVersion","occurredAt","accountContext","eventId","auditId","domain","resourceType","resourceId","resourceVersion","action","requestId");
        assertThat(b.incoming.poll(150,TimeUnit.MILLISECONDS)).isNull();assertThat(b.resource("private")).isFalse();
    }
    @Test void resourceAuthorizationIsRecheckedAfterTheSubscriptionWasEstablished()throws Exception{
        var channel=new RecordingTransport();connect(session(1),channel);committed(change("allowed","ENTERPRISE",1,"42"));channel.take("resource-changed");
        grants.put(1L,Set.of());committed(change("removed","ENTERPRISE",2,"42"));
        assertThat(channel.take("resync-required").body()).doesNotContainKeys("resourceId","auditId","eventId");
        assertThat(channel.incoming.poll(150,TimeUnit.MILLISECONDS)).isNull();assertThat(channel.resource("removed")).isFalse();
    }
    @Test void revokedDurableSessionIsRejectedBeforeTheNextFrameIsSent()throws Exception{
        var account=session(1);var channel=new RecordingTransport();connect(account,channel);live.remove(account.sessionDigest());
        committed(change("revoked","ENTERPRISE",2,"42"));await(()->channel.completed.get()==1&&service.activeSlots()==0);assertThat(channel.resource("revoked")).isFalse();
    }
    @Test void actualAccessExpiryCapsTheConnectionEvenWhenTheRefreshSessionLastsADay()throws Exception{
        var account=session(1);
        assertThatThrownBy(()->service.open(account.userId(),account.username(),account.sessionDigest(),account.accountContext(),Instant.now().minusSeconds(1)))
                .isInstanceOf(ResponseStatusException.class).satisfies(f->assertThat(((ResponseStatusException)f).getStatusCode().value()).isEqualTo(401));
        var emitter=service.open(account.userId(),account.username(),account.sessionDigest(),account.accountContext(),Instant.now().plusMillis(120));
        assertThat(emitter.getTimeout()).isBetween(1L,120L);await(()->service.activeSlots()==0);
    }
    @Test void everyServletTerminationCallbackReleasesTheConnectionExactlyOnce()throws Exception{
        for(String field:List.of("timeoutCallback","errorCallback","completionCallback")){
            var account=session(1);var emitter=service.open(account.userId(),account.username(),account.sessionDigest(),account.accountContext(),Instant.now().plusSeconds(30));
            Object callback=ReflectionTestUtils.getField(emitter,field);
            if(callback instanceof Runnable runnable){runnable.run();runnable.run();}
            else { @SuppressWarnings("unchecked") var error=(Consumer<Throwable>)callback;error.accept(new java.io.IOException("disconnected"));error.accept(new java.io.IOException("duplicate")); }
            await(()->service.activeSlots()==0);
        }
    }
    @Test void aBlockedSocketRetainsItsBoundedSlotWhileOtherUsersReceiveEvents()throws Exception{
        properties.setMaxConnections(2);properties.setMaxConnectionsPerUser(1);properties.setSendTimeoutMillis(1000);
        var slow=new BlockingTransport();blocked.add(slow);var connection=service.register(session(1),Instant.now().plusSeconds(30),slow);connection.begin();assertThat(slow.entered.await(5,TimeUnit.SECONDS)).isTrue();
        var healthy=new RecordingTransport();connect(session(2),healthy);
        ((AtomicLong)ReflectionTestUtils.getField(connection,"sendingSince")).set(System.nanoTime()-TimeUnit.SECONDS.toNanos(2));ReflectionTestUtils.invokeMethod(service,"tick");
        assertThat(service.activeSlots()).isEqualTo(2);
        assertThatThrownBy(()->service.register(session(3),Instant.now().plusSeconds(30),new RecordingTransport())).isInstanceOf(ResponseStatusException.class).satisfies(f->assertThat(((ResponseStatusException)f).getStatusCode().value()).isEqualTo(429));
        committed(change("healthy","ENTERPRISE",2,"42"));assertThat(healthy.take("resource-changed").id()).isEqualTo("healthy");
        slow.release.countDown();await(()->slow.completed.get()==1&&service.activeSlots()==1);
    }
    @Test void overflowClosesOnlyTheSlowConnectionAndDoesNotCreateUnboundedWriters()throws Exception{
        properties.setQueueCapacity(2);var slow=new BlockingTransport();blocked.add(slow);
        var connection=service.register(session(1),Instant.now().plusSeconds(30),slow);connection.begin();assertThat(slow.entered.await(5,TimeUnit.SECONDS)).isTrue();
        service.publish(change("fill","ENTERPRISE",1,"42"));service.publish(change("overflow","ENTERPRISE",1,"43"));
        assertThat(service.activeSlots()).isEqualTo(1);slow.release.countDown();await(()->slow.completed.get()==1&&service.activeSlots()==0);
        assertThat(slow.resource("fill")||slow.resource("overflow")).isFalse();
    }
    @Test void perUserBudgetAndApplicationShutdownReleaseAllConnections()throws Exception{
        properties.setMaxConnectionsPerUser(1);var first=new RecordingTransport();connect(session(1),first);
        assertThatThrownBy(()->service.register(session(1),Instant.now().plusSeconds(30),new RecordingTransport())).isInstanceOf(ResponseStatusException.class).satisfies(f->assertThat(((ResponseStatusException)f).getStatusCode().value()).isEqualTo(429));
        service.stop();await(()->first.completed.get()==1&&service.activeSlots()==0);
        assertThatThrownBy(()->service.register(session(2),Instant.now().plusSeconds(30),new RecordingTransport())).isInstanceOf(ResponseStatusException.class).satisfies(f->assertThat(((ResponseStatusException)f).getStatusCode().value()).isEqualTo(503));
    }
}
