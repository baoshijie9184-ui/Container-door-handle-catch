package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import io.agentscope.core.model.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import static com.ruanzhu.doorhandle.module.ai.model.ModelFailureClassifier.Failure.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class RedisModelCircuitTest {
    @Test void coordinationFailureNeverCallsPrimaryOrFallbackSupplier(){
        var redis=mock(StringRedisTemplate.class);
        when(redis.execute(any(org.springframework.data.redis.core.script.RedisScript.class),anyList(),any(Object[].class)))
                .thenThrow(new org.springframework.data.redis.RedisConnectionFailureException("fixture unavailable"));
        var primary=mock(Model.class);var fallback=mock(Model.class);
        var circuit=new RedisModelCircuit(redis,3,"dashscope:fixture",2,Duration.ofSeconds(1),Duration.ofSeconds(2),Duration.ofSeconds(3));
        var model=new ManagedAgentModel(List.of(new ManagedAgentModel.Candidate("a",primary,circuit),new ManagedAgentModel.Candidate("b",fallback,circuit)),null,new AgentModelProperties(),true);
        assertThatThrownBy(()->model.stream(List.of(),List.of(),null).blockLast()).isInstanceOf(RedisModelCircuit.Unavailable.class);
        verifyNoInteractions(primary,fallback);
    }

    @Nested @EnabledIfSystemProperty(named="agent.redis.test",matches="true")
    class RealRedis {
        LettuceConnectionFactory firstFactory,secondFactory;
        StringRedisTemplate first,second;
        long revision;
        @BeforeEach void start(){
            int port=Integer.getInteger("agent.redis.test.port",16379);
            firstFactory=new LettuceConnectionFactory("127.0.0.1",port);secondFactory=new LettuceConnectionFactory("127.0.0.1",port);
            firstFactory.afterPropertiesSet();secondFactory.afterPropertiesSet();
            first=new StringRedisTemplate(firstFactory);second=new StringRedisTemplate(secondFactory);
            assertThat(first.getConnectionFactory().getConnection().ping()).isEqualTo("PONG");
            revision=System.nanoTime();
        }
        @AfterEach void stop(){
            for(var key:first.keys("doorhandlecatch:agent:model-circuit:{"+revision+":*"))first.delete(key);
            firstFactory.destroy();secondFactory.destroy();
        }
        RedisModelCircuit circuit(StringRedisTemplate client,String id){return new RedisModelCircuit(client,revision,id,2,Duration.ofMillis(80),Duration.ofMillis(80),Duration.ofSeconds(1));}
        @Test void independentInstancesShareQuotaAndOnlyOneRecoveryProbeIsAllowed() throws Exception {
            var a=circuit(first,"same-model");var b=circuit(second,"same-model");
            var old=b.acquire();a.failure(a.acquire(),QUOTA);
            assertThat(b.acquire()).isNull();b.success(old);assertThat(a.acquire()).isNull();
            Thread.sleep(100);
            var pool=Executors.newFixedThreadPool(8);var gate=new CountDownLatch(1);
            try{
                var jobs=new ArrayList<Future<ModelCircuit.Permit>>();
                for(int i=0;i<40;i++){var candidate=i%2==0?a:b;jobs.add(pool.submit(()->{gate.await();return candidate.acquire();}));}
                gate.countDown();var admitted=new ArrayList<ModelCircuit.Permit>();for(var job:jobs){var permit=job.get(3,TimeUnit.SECONDS);if(permit!=null)admitted.add(permit);}
                assertThat(admitted).hasSize(1);assertThat(a.health().state()).isEqualTo("HALF_OPEN");
                b.success(admitted.get(0));assertThat(a.health().state()).isEqualTo("CLOSED");assertThat(a.acquire().probe()).isFalse();
            }finally{pool.shutdownNow();}
        }
        @Test void cancelledOrDeadProbeCannotReleaseANewerOwner() throws Exception {
            var a=circuit(first,"fenced-model");var b=circuit(second,"fenced-model");a.failure(a.acquire(),AUTH);Thread.sleep(100);
            var old=a.acquire();a.release(old);var current=b.acquire();a.release(old);a.success(old);
            assertThat(a.acquire()).isNull();assertThat(a.health().state()).isEqualTo("HALF_OPEN");
            // Simulate the server-time lease expiring after an application process dies.
            var keys=first.keys("doorhandlecatch:agent:model-circuit:{"+revision+":*");assertThat(keys).hasSize(1);
            first.opsForHash().put(keys.iterator().next(),"probeUntil","0");
            var replacement=a.acquire();assertThat(replacement).isNotNull();b.success(current);b.release(current);assertThat(b.acquire()).isNull();
            a.success(replacement);assertThat(b.health().state()).isEqualTo("CLOSED");
        }
        @Test void revisionsAndModelsHaveIndependentHealth(){
            var a=circuit(first,"a");a.failure(a.acquire(),QUOTA);
            assertThat(circuit(second,"b").acquire()).isNotNull();
            var newer=new RedisModelCircuit(second,revision+1,"a",2,Duration.ofSeconds(1),Duration.ofSeconds(1),Duration.ofSeconds(1));
            try{assertThat(newer.acquire()).isNotNull();}finally{second.delete(second.keys("doorhandlecatch:agent:model-circuit:{"+(revision+1)+":*"));}
        }
    }
}
