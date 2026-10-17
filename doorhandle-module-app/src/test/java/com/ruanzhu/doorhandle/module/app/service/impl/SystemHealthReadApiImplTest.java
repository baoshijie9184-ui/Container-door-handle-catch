package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import org.springframework.boot.actuate.health.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class SystemHealthReadApiImplTest {
    final AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR);
    final AgentActor employee=new AgentActor(2,"staff",AgentActor.Role.INSPECTOR);
    SystemHealthReadApiImpl service(HealthEndpoint endpoint,Duration budget,Duration ttl) {
        var beans=new DefaultListableBeanFactory();if(endpoint!=null)beans.registerSingleton("healthEndpoint",endpoint);
        return new SystemHealthReadApiImpl(beans.getBeanProvider(HealthEndpoint.class),budget,ttl);
    }
    @Test void realActuatorProbesOnlyNamedComponentsAndDropsAllDetails() throws Exception {
        var group=mock(HealthEndpointGroup.class);when(group.isMember(anyString())).thenReturn(true);
        when(group.showDetails(any())).thenReturn(true);when(group.showComponents(any())).thenReturn(true);
        when(group.getStatusAggregator()).thenReturn(new SimpleStatusAggregator());
        var industrial=mock(HealthIndicator.class);var contributions=new LinkedHashMap<String,HealthContributor>();
        for(String id:List.of("livenessState","readinessState","diskSpace","db","redis"))
            contributions.put(id,(HealthIndicator)()->Health.up().withDetail("url","jdbc:PRIVATE_PASSWORD").withDetail("path","PRIVATE_DISK_PATH").build());
        contributions.put("industrialPlatform",industrial);
        var endpoint=new HealthEndpoint(new DefaultHealthContributorRegistry(contributions),HealthEndpointGroups.of(group,Map.of()),Duration.ofSeconds(2));
        try(var service=service(endpoint,Duration.ofSeconds(1),Duration.ofSeconds(30))){
            var result=service.snapshot(boss);assertThat(result.status()).isEqualTo("UP");assertThat(result.components()).hasSize(5);
            assertThat(result.components()).allMatch(c->c.status().equals("UP")&&c.evidence().equals("ACTUATOR"));
            assertThat(result.notMonitored()).contains("kafka","detectionWorker","mem0","oss","higress","mcpGateway");
            assertThat(Duration.between(result.checkedAt(),result.expiresAt())).isEqualTo(Duration.ofSeconds(30));
            assertThat(new ObjectMapper().findAndRegisterModules().writeValueAsString(result)).doesNotContain("PRIVATE_","url","path","details","industrialPlatform");
            verifyNoInteractions(industrial);
        }
    }
    @Test void missingFailedAndUnrecognizedChecksAreUnknownWithoutExposingCauses() throws Exception {
        var endpoint=mock(HealthEndpoint.class);
        when(endpoint.healthForPath("livenessState")).thenReturn(Health.status("PRIVATE_STATUS").build());
        when(endpoint.healthForPath("db")).thenThrow(new IllegalStateException("PRIVATE_DATABASE_ERROR"));
        when(endpoint.healthForPath("redis")).thenReturn(Health.down().withDetail("exception","PRIVATE_REDIS_ERROR").build());
        try(var service=service(endpoint,Duration.ofSeconds(1),Duration.ZERO)){
            var result=service.snapshot(boss);assertThat(result.status()).isEqualTo("DOWN");
            assertThat(result.components()).contains(new SystemHealthReadApi.Component("db","UNKNOWN","CHECK_FAILED"),
                    new SystemHealthReadApi.Component("diskSpace","UNKNOWN","NOT_REGISTERED"),new SystemHealthReadApi.Component("livenessState","UNKNOWN","ACTUATOR"));
            assertThat(new ObjectMapper().findAndRegisterModules().writeValueAsString(result)).doesNotContain("PRIVATE_");
        }
    }
    @Test void absentActuatorNeverMeansHealthyAndUnauthorizedReadsDoNotProbe(){
        var endpoint=mock(HealthEndpoint.class);
        try(var service=service(endpoint,Duration.ofSeconds(1),Duration.ZERO)){
            assertThatThrownBy(()->service.snapshot(employee)).isInstanceOf(SecurityException.class);verifyNoInteractions(endpoint);
        }
        try(var service=service(null,Duration.ofSeconds(1),Duration.ZERO)){
            var result=service.snapshot(boss);assertThat(result.status()).isEqualTo("UNKNOWN");
            assertThat(result.components()).allMatch(c->c.evidence().equals("NOT_REGISTERED"));
        }
    }
    @Test void snapshotCacheKeepsOriginalTimestampsAndDoesNotGrantEmployeeAccess(){
        var endpoint=mock(HealthEndpoint.class);when(endpoint.healthForPath(any(String[].class))).thenReturn(Health.up().build());
        try(var service=service(endpoint,Duration.ofSeconds(1),Duration.ofSeconds(30))){
            var first=service.snapshot(boss);assertThat(service.snapshot(boss)).isSameAs(first);
            assertThatThrownBy(()->service.snapshot(employee)).isInstanceOf(SecurityException.class);
            verify(endpoint,times(5)).healthForPath(any(String[].class));
        }
    }
    @Test void concurrentReadersShareOneBoundedProbeCycle() throws Exception {
        var endpoint=mock(HealthEndpoint.class);when(endpoint.healthForPath(any(String[].class))).thenReturn(Health.up().build());
        var readers=Executors.newFixedThreadPool(4);
        try(var service=service(endpoint,Duration.ofSeconds(1),Duration.ofSeconds(30))){
            var calls=new ArrayList<Future<SystemHealthReadApi.Snapshot>>();
            for(int i=0;i<8;i++)calls.add(readers.submit(()->service.snapshot(boss)));
            var first=calls.get(0).get(2,TimeUnit.SECONDS);
            for(var call:calls)assertThat(call.get(2,TimeUnit.SECONDS)).isSameAs(first);
            verify(endpoint,times(5)).healthForPath(any(String[].class));
        }finally{readers.shutdownNow();}
    }
    @Test void uninterruptibleSlowChecksCannotExceedWorkerBoundOrTotalWaitBudget(){
        var endpoint=mock(HealthEndpoint.class);var release=new CountDownLatch(1);var active=new AtomicInteger();var maximum=new AtomicInteger();
        when(endpoint.healthForPath(any(String[].class))).thenAnswer(inv->{int count=active.incrementAndGet();maximum.accumulateAndGet(count,Math::max);
            try{while(release.getCount()>0){try{release.await();}catch(InterruptedException ignored){}}return Health.up().build();}finally{active.decrementAndGet();}});
        try(var service=service(endpoint,Duration.ofMillis(100),Duration.ZERO)){
            long start=System.nanoTime();var result=service.snapshot(boss);
            assertThat(Duration.ofNanos(System.nanoTime()-start)).isLessThan(Duration.ofSeconds(1));
            assertThat(result.status()).isEqualTo("UNKNOWN");assertThat(result.components()).anyMatch(c->c.evidence().equals("TIMED_OUT"));
            service.snapshot(boss);assertThat(maximum.get()).isLessThanOrEqualTo(3);
        }finally{release.countDown();}
    }
}
