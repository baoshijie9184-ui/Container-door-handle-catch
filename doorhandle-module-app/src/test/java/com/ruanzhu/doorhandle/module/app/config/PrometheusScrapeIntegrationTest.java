package com.ruanzhu.doorhandle.module.app.config;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.observability.ObservabilityProperties;
import io.micrometer.prometheus.PrometheusMeterRegistry;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.boot.autoconfigure.data.redis.RedisAutoConfiguration;
import org.springframework.boot.autoconfigure.data.redis.RedisRepositoriesAutoConfiguration;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;

/** ECS-only real Spring/Actuator/Micrometer -> owned Prometheus; no business scan or database. */
@EnabledIfEnvironmentVariable(named="DOORHANDLE_REQUIRE_OBSERVABILITY_TESTS",matches="true")
// SpringBootTest otherwise disables real metric exporters and supplies only SimpleMeterRegistry.
@AutoConfigureObservability(metrics=true,tracing=false)
@SpringBootTest(classes=PrometheusScrapeIntegrationTest.MinimalApplication.class,
        webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties={"server.address=127.0.0.1","management.endpoints.web.exposure.include=health,prometheus","management.tracing.enabled=false",
                "spring.main.banner-mode=off","spring.jmx.enabled=false"})
class PrometheusScrapeIntegrationTest {
    @Configuration(proxyBeanMethods=false)
    @EnableAutoConfiguration(exclude={DataSourceAutoConfiguration.class,RedisAutoConfiguration.class,RedisRepositoriesAutoConfiguration.class})
    @Import(PrometheusSecurityConfiguration.class)
    static class MinimalApplication {
        @Bean ObservabilityProperties fixtureObservabilityProperties(){
            var properties=new ObservabilityProperties();properties.setMetricsTokenFile(required("DOORHANDLE_TEST_OBSERVABILITY_TOKEN_FILE"));return properties;
        }
    }
    @LocalServerPort int port;
    @Autowired PrometheusMeterRegistry meters;
    @Autowired ObjectMapper json;
    private final HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).followRedirects(HttpClient.Redirect.NEVER).build();
    private static String required(String name){String value=System.getenv(name);if(value==null||value.isBlank())throw new IllegalStateException("Required owned observability fixture is missing");return value;}
    private static URI loopback(String value){var uri=URI.create(value);if(!"http".equals(uri.getScheme())||!"127.0.0.1".equals(uri.getHost())||uri.getPort()<1024||uri.getUserInfo()!=null||uri.getQuery()!=null||uri.getFragment()!=null)throw new IllegalArgumentException("Only the owned loopback fixture is allowed");return uri;}
    private HttpResponse<String> get(URI uri,String token)throws Exception{
        var builder=HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(5)).GET();if(token!=null)builder.header("Authorization","Bearer "+token);
        return http.send(builder.build(),HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }
    private JsonNode query(URI prometheus,String expression)throws Exception{
        var response=get(prometheus.resolve("/api/v1/query?query="+URLEncoder.encode(expression,StandardCharsets.UTF_8)),null);
        assertThat(response.statusCode()).isEqualTo(200);JsonNode data=json.readTree(response.body());assertThat(data.path("status").asText()).isEqualTo("success");return data;
    }
    private JsonNode awaitSample(URI prometheus,String expression,double minimum)throws Exception{
        long deadline=System.nanoTime()+Duration.ofSeconds(45).toNanos();JsonNode result=null;
        while(System.nanoTime()<deadline){result=query(prometheus,expression);var samples=result.path("data").path("result");if(samples.isArray()&&samples.size()==1&&Double.parseDouble(samples.get(0).path("value").get(1).asText())>=minimum)return result;Thread.sleep(200);}
        throw new AssertionError("Owned Prometheus did not observe the Java metric within the acceptance window");
    }
    @Test void realPrometheusScrapesAuthenticatedActuatorCountersAndHistogram()throws Exception{
        URI prometheus=loopback(required("DOORHANDLE_TEST_PROMETHEUS_URL"));
        Path targets=Path.of(required("DOORHANDLE_TEST_OBSERVABILITY_TARGETS")).toRealPath();
        Path tokenFile=Path.of(required("DOORHANDLE_TEST_OBSERVABILITY_TOKEN_FILE")).toRealPath();
        assertThat(targets.isAbsolute()&&Files.isDirectory(targets)).isTrue();String token=Files.readString(tokenFile).strip();
        URI metrics=URI.create("http://127.0.0.1:"+port+"/actuator/prometheus");
        assertThat(get(metrics,null).statusCode()).isEqualTo(401);
        assertThat(get(metrics,"wrong-machine-token").statusCode()).isEqualTo(401);
        meters.counter("doorhandle.fixture.operations").increment(3);
        io.micrometer.core.instrument.Timer.builder("doorhandle.fixture.operation").publishPercentileHistogram().register(meters).record(Duration.ofMillis(12));
        var authorized=get(metrics,token);assertThat(authorized.statusCode()).isEqualTo(200);
        assertThat(authorized.body()).contains("doorhandle_fixture_operations_total","doorhandle_fixture_operation_seconds_bucket");
        Path target=targets.resolve("java.json"),temporary=targets.resolve("java.tmp");
        Files.writeString(temporary,json.writeValueAsString(List.of(Map.of("targets",List.of("127.0.0.1:"+port),
                "labels",Map.of("fixture","java","__metrics_path__","/actuator/prometheus")))),StandardCharsets.UTF_8);
        Files.move(temporary,target,StandardCopyOption.ATOMIC_MOVE);
        try {
            var observations=new LinkedHashMap<String,Object>();
            observations.put("up",awaitSample(prometheus,"up{fixture=\"java\"}",1));
            observations.put("counter",awaitSample(prometheus,"doorhandle_fixture_operations_total{fixture=\"java\"}",3));
            observations.put("histogramCount",awaitSample(prometheus,"doorhandle_fixture_operation_seconds_count{fixture=\"java\"}",1));
            observations.put("histogramBucket",awaitSample(prometheus,"doorhandle_fixture_operation_seconds_bucket{fixture=\"java\",le=\"+Inf\"}",1));
            observations.put("histogramSum",awaitSample(prometheus,"doorhandle_fixture_operation_seconds_sum{fixture=\"java\"}",0.012));
            var receipt=Map.of("schemaVersion",1,"runtime","java","status","PASS","missingTokenStatus",401,"wrongTokenStatus",401,
                    "authenticatedStatus",200,"providerCalls",0,"observations",observations);
            Path evidence=targets.getParent().resolve("evidence/java-scrape.json");Files.writeString(evidence,json.writeValueAsString(receipt),StandardCharsets.UTF_8);
        } finally {Files.deleteIfExists(target);}
    }
}
