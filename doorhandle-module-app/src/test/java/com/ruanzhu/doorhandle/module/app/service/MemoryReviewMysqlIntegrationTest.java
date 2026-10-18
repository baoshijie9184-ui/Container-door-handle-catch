package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos;
import com.ruanzhu.doorhandle.module.system.security.SensitiveDataSanitizer;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.server.ResponseStatusException;

import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.*;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

import static org.assertj.core.api.Assertions.*;

/** Real ECS MySQL + native private Mem0 HTTP/Chroma/SQLite. Synthetic, non-paid model only. */
@EnabledIfSystemProperty(named="agent.memory.review.mysql",matches="true")
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class MemoryReviewMysqlIntegrationTest {
    static final ObjectMapper JSON=new ObjectMapper();
    static JsonNode config,fixtures;
    static JdbcTemplate jdbc;
    static MemoryPreferenceService preferences;
    static Mem0Client client;
    static PersonalMemoryService service;
    static Path report;
    static final List<String> checks=new ArrayList<>();

    @BeforeAll static void initialize()throws Exception{
        Path root=Path.of(System.getProperty("agent.memory.review.project")).toAbsolutePath().normalize();
        Path privateConfig=Path.of(System.getProperty("agent.memory.review.config")).toAbsolutePath().normalize();
        assertThat(privateConfig.startsWith(root.resolve("work"))).isTrue();
        config=JSON.readTree(Files.readString(privateConfig));
        String database=config.path("database").asText(),url=config.path("url").asText();
        assertThat(database).matches("doorhandle_wb_verify_[a-f0-9]{10}");
        assertThat(url).startsWith("jdbc:mysql://127.0.0.1:").contains("/"+database+"?");
        jdbc=new JdbcTemplate(new DriverManagerDataSource(url,config.path("username").asText(),config.path("password").asText()));
        assertThat(jdbc.queryForObject("SELECT DATABASE()",String.class)).isEqualTo(database);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",Integer.class)).isZero();
        String ddl=Files.readString(root.resolve("sql/mysql/migration-V26-personal-memory-governance.sql"));
        for(String statement:ddl.split(";"))if(!statement.isBlank())jdbc.execute(statement);
        preferences=new MemoryPreferenceService(jdbc,new DataSourceTransactionManager(jdbc.getDataSource()));
        fixtures=JSON.readTree(Files.readString(Path.of(config.path("bridgeFixture").asText())));
        client=bridge(fixtures.path("bridgeUrl").asText());service=new PersonalMemoryService(client,preferences);
        report=root.resolve("work/memory-review-mysql-result.json");
    }

    static Mem0Client bridge(String url){
        assertThat(url).startsWith("http://127.0.0.1:");
        var bridge=new Mem0Client(new SensitiveDataSanitizer(),preferences);
        ReflectionTestUtils.setField(bridge,"enabled",true);ReflectionTestUtils.setField(bridge,"serviceUrl",url);
        ReflectionTestUtils.setField(bridge,"bridgeToken",fixtures.path("bridgeToken").asText());
        return bridge;
    }
    static TenantContext owner(String name){return new TenantContext(fixtures.path("cases").path(name).path("ownerId").asLong(),"integration-"+name);}
    static String source(String name){return fixtures.path("cases").path(name).path("sourceId").asText();}
    static String candidate(String name){return fixtures.path("cases").path(name).path("candidateId").asText();}
    static MemoryDtos.Review start(String name)throws Exception{
        var actor=owner(name);var item=service.get(actor,source(name));
        var review=service.startReview(actor,item.id(),new MemoryDtos.StartReview(UUID.randomUUID().toString(),item.digest(),item.lifecycle().revision()));
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(8);
        while(review.status().equals("RUNNING")&&System.nanoTime()<deadline){Thread.sleep(30);review=service.getReview(actor,review.id());}
        assertThat(review.status()).isEqualTo("READY");assertThat(review.candidates()).singleElement().satisfies(pair->assertThat(pair.id()).isEqualTo(candidate(name)));
        return review;
    }
    static MemoryDtos.ResolveReview decision(MemoryDtos.Review review,String candidate,String id){return new MemoryDtos.ResolveReview(id,review.revision(),candidate,"KEEP_SOURCE",true);}

    @Test @Order(1) void realHttpDecisionIsOwnedDurableAndExactlyOnce()throws Exception{
        var owner=owner("normal");var review=start("normal");
        assertThat(review.source().sourceSessionId()).isEqualTo("first");assertThat(review.candidates().get(0).item().sourceSessionId()).isEqualTo("second");
        assertThatThrownBy(()->service.getReview(owner("unknown"),review.id())).hasMessageContaining("404");
        var request=decision(review,candidate("normal"),UUID.randomUUID().toString());
        assertThat(service.resolveReview(owner,review.id(),request).decisions()).hasSize(1);
        assertThat(service.resolveReview(owner,review.id(),request).decisions()).hasSize(1);
        assertThat(client.getOwned(owner,candidate("normal")).lifecycle().revision()).isEqualTo(1);
        assertThat(client.getOwned(owner,candidate("normal")).lifecycle().state()).isEqualTo("EXCLUDED");
        assertThat(preferences.audit(owner)).singleElement().satisfies(a->{assertThat(a.outcome()).isEqualTo("SUCCEEDED");assertThat(a.action()).isEqualTo("REVIEW_DECISION");});
        assertThat(preferences.audit(owner("unknown"))).isEmpty();
        checks.add("Native HTTP and real MySQL decision is owned, audited and not redispatched on replay");
    }

    @Test @Order(2) void lostCompletionIsReconciledWithoutRepeatingTheActualBridgeMutation()throws Exception{
        var actor=owner("unknown");var review=start("unknown");var calls=new AtomicInteger();var upstream=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(2)).build();
        var proxy=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        proxy.createContext("/memories",exchange->{
            try{
                var request=HttpRequest.newBuilder(URI.create(fixtures.path("bridgeUrl").asText()+exchange.getRequestURI())).timeout(Duration.ofSeconds(5))
                    .header("Content-Type","application/json").header("X-Doorhandle-Memory-Token",fixtures.path("bridgeToken").asText()).header("X-Doorhandle-Memory-Protocol","2")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(exchange.getRequestBody().readAllBytes())).build();
                var response=upstream.send(request,HttpResponse.BodyHandlers.ofByteArray());
                boolean mutation=exchange.getRequestURI().getPath().endsWith("/resolve");
                if(mutation){calls.incrementAndGet();assertThat(response.statusCode()).isEqualTo(200);}
                byte[] bytes=mutation?"{\"detail\":\"fixture response lost after completion\"}".getBytes():response.body();
                exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(mutation?503:response.statusCode(),bytes.length);exchange.getResponseBody().write(bytes);
            }catch(Exception error){throw new RuntimeException(error);}finally{exchange.close();}
        });proxy.start();
        try{
            var proxied=new PersonalMemoryService(bridge("http://127.0.0.1:"+proxy.getAddress().getPort()),preferences);
            var request=decision(review,candidate("unknown"),UUID.randomUUID().toString());
            assertThatThrownBy(()->proxied.resolveReview(actor,review.id(),request)).hasMessageContaining("503");
            assertThat(preferences.audit(actor)).singleElement().satisfies(a->assertThat(a.outcome()).isEqualTo("UNKNOWN"));
            assertThatThrownBy(()->proxied.resolveReview(actor,review.id(),request)).hasMessageContaining("409");
            assertThat(proxied.getReview(actor,review.id()).decisions()).hasSize(1);
            assertThat(proxied.resolveReview(actor,review.id(),request).decisions()).hasSize(1);
            assertThat(calls).hasValue(1);assertThat(client.getOwned(actor,candidate("unknown")).lifecycle().revision()).isEqualTo(1);
            assertThat(preferences.audit(actor)).singleElement().satisfies(a->assertThat(a.outcome()).isEqualTo("SUCCEEDED"));
            checks.add("Lost real HTTP completion reconciles MySQL UNKNOWN from original SQLite decision without replay");
        }finally{proxy.stop(0);}
    }

    @Test @Order(3) void nativeBodyChangeInvalidatesReviewAndDisabledReadPreventsAnalysis()throws Exception{
        var actor=owner("stale");var review=start("stale");var item=service.get(actor,candidate("stale"));
        service.update(actor,item.id(),new MemoryDtos.Update(UUID.randomUUID().toString(),item.digest(),"用户更正为 CSV 报告",true));
        assertThat(service.getReview(actor,review.id()).candidates().get(0).stale()).isTrue();
        assertThatThrownBy(()->service.resolveReview(actor,review.id(),decision(review,item.id(),UUID.randomUUID().toString()))).hasMessageContaining("409");
        assertThat(client.getOwned(actor,item.id()).lifecycle().revision()).isZero();
        preferences.change(actor,new MemoryDtos.ChangePreference(0,false,true));
        var source=service.get(actor,source("stale"));
        assertThatThrownBy(()->service.startReview(actor,source.id(),new MemoryDtos.StartReview(UUID.randomUUID().toString(),source.digest(),0))).hasMessageContaining("403");
        checks.add("Native update invalidates old advice and disabled read blocks new analysis");
    }

    @Test @Order(4) void simultaneousSameRequestHasOneAuditAndOneNativeLifecycleChange()throws Exception{
        var actor=owner("concurrent");var review=start("concurrent");var request=decision(review,candidate("concurrent"),UUID.randomUUID().toString());
        var gate=new CountDownLatch(1);var successes=new AtomicInteger();var conflicts=new AtomicInteger();var pool=Executors.newFixedThreadPool(6);
        try{
            var futures=new ArrayList<Future<?>>();
            for(int i=0;i<6;i++)futures.add(pool.submit(()->{try{gate.await();service.resolveReview(actor,review.id(),request);successes.incrementAndGet();}catch(ResponseStatusException error){assertThat(error.getStatusCode().value()).isEqualTo(409);conflicts.incrementAndGet();}catch(InterruptedException error){Thread.currentThread().interrupt();throw new IllegalStateException(error);}}));
            gate.countDown();for(var future:futures)future.get(15,TimeUnit.SECONDS);
            assertThat(successes.get()).isGreaterThanOrEqualTo(1);assertThat(successes.get()+conflicts.get()).isEqualTo(6);
            assertThat(preferences.audit(actor)).singleElement().satisfies(a->assertThat(a.outcome()).isEqualTo("SUCCEEDED"));
            assertThat(client.getOwned(actor,candidate("concurrent")).lifecycle().revision()).isEqualTo(1);
            assertThat(client.getReview(actor,review.id()).decisions()).hasSize(1);
            checks.add("Six concurrent real MySQL requests produce one audit row and one native change");
        }finally{pool.shutdownNow();}
    }

    @Test @Order(5) void missingMysqlAuditBlocksNativeMutationAndRestoresTheIsolatedTable()throws Exception{
        var actor=owner("audit");var review=start("audit");
        jdbc.execute("RENAME TABLE agent_memory_audit TO agent_memory_audit_temporarily_unavailable");
        try{
            assertThatThrownBy(()->service.resolveReview(actor,review.id(),decision(review,candidate("audit"),UUID.randomUUID().toString()))).isInstanceOf(org.springframework.dao.DataAccessException.class);
            assertThat(client.getOwned(actor,candidate("audit")).lifecycle().revision()).isZero();
            assertThat(client.getReview(actor,review.id()).decisions()).isEmpty();
        }finally{jdbc.execute("RENAME TABLE agent_memory_audit_temporarily_unavailable TO agent_memory_audit");}
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_memory_audit WHERE content_digest NOT REGEXP '^[a-f0-9]{64}$' AND content_digest IS NOT NULL",Integer.class)).isZero();
        checks.add("Unavailable real MySQL audit prevents native mutation; audit contains digests only");
    }

    @AfterAll static void results()throws Exception{
        if(report!=null)Files.writeString(report,JSON.writerWithDefaultPrettyPrinter().writeValueAsString(Map.of("actualMysql",true,"nativeMemoryHttp",true,"providerMode","scripted","checks",checks,"passed",checks.size()==5,"productionBusinessDatabaseModified",false)));
    }
}
