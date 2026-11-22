package com.ruanzhu.doorhandle.module.app.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.observability.ObservabilityProperties;
import com.ruanzhu.doorhandle.module.app.config.properties.AppCorsProperties;
import com.ruanzhu.doorhandle.module.system.security.JwtAuthenticationFilter;
import com.ruanzhu.doorhandle.module.system.util.JwtUtil;
import jakarta.servlet.Filter;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.boot.web.servlet.context.ServletWebServerApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.core.annotation.Order;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class PrometheusSecurityConfigurationTest {
    @TempDir Path temporary;
    @Test void onlyExactMachineCredentialCanReadMetricsAndDoesNotUnlockOtherEndpoints()throws Exception{
        String token="machine-private-token-with-32-characters";
        Path secret=temporary.resolve("metrics-token");Files.writeString(secret,token);
        var properties=new ObservabilityProperties();properties.setMetricsTokenFile(secret.toString());
        new WebApplicationContextRunner().withUserConfiguration(WebConfig.class,PrometheusSecurityConfiguration.class)
                .withBean(ObservabilityProperties.class,()->properties).run(context->{
                    var mvc=MockMvcBuilders.webAppContextSetup(context).addFilters(context.getBean("springSecurityFilterChain",Filter.class)).build();
                    mvc.perform(get("/actuator/prometheus")).andExpect(status().isUnauthorized());
                    mvc.perform(get("/actuator/prometheus").param("token",token)).andExpect(status().isUnauthorized());
                    mvc.perform(get("/actuator/prometheus").header("Authorization","Bearer business-jwt" )).andExpect(status().isUnauthorized());
                    mvc.perform(get("/actuator/prometheus").header("Authorization","Bearer "+token)).andExpect(status().isOk()).andExpect(content().string("fixture_metric 1\n"));
                    mvc.perform(post("/actuator/prometheus").header("Authorization","Bearer "+token)).andExpect(status().isMethodNotAllowed());
                    mvc.perform(get("/actuator/env").header("Authorization","Bearer "+token)).andExpect(status().isUnauthorized());
                });
    }
    @Test void missingMachineSecretKeepsEndpointClosed(){
        new WebApplicationContextRunner().withUserConfiguration(WebConfig.class,PrometheusSecurityConfiguration.class)
                .withBean(ObservabilityProperties.class,ObservabilityProperties::new).run(context->{
                    var mvc=MockMvcBuilders.webAppContextSetup(context).addFilters(context.getBean("springSecurityFilterChain",Filter.class)).build();
                    mvc.perform(get("/actuator/prometheus").header("Authorization","Bearer arbitrary-token" )).andExpect(status().isUnauthorized());
                });
    }
    @Test void servletOnlyAppliesJwtToTheBusinessSecurityChain()throws Exception{
        String token="machine-private-token-with-32-characters";
        Path secret=temporary.resolve("metrics-token");Files.writeString(secret,token);
        try(var context=(ServletWebServerApplicationContext)new SpringApplicationBuilder(ServletApp.class)
                .run("--server.port=0","--server.address=127.0.0.1","--spring.jmx.enabled=false",
                     "--management.endpoints.enabled-by-default=false","--fixture.metrics-token-file="+secret)){
            var base=URI.create("http://127.0.0.1:"+context.getWebServer().getPort());
            var client=HttpClient.newHttpClient();
            var metrics=client.send(HttpRequest.newBuilder(base.resolve("/actuator/prometheus"))
                .header("Authorization","Bearer "+token).build(),HttpResponse.BodyHandlers.ofString());
            assertThat(metrics.statusCode()).isEqualTo(200);
            assertThat(metrics.body()).isEqualTo("fixture_metric 1\n");
            var business=client.send(HttpRequest.newBuilder(base.resolve("/actuator/env"))
                .header("Authorization","Bearer "+token).build(),HttpResponse.BodyHandlers.discarding());
            assertThat(business.statusCode()).isEqualTo(401);
        }
    }
    @Configuration(proxyBeanMethods=false)
    @EnableAutoConfiguration(exclude=DataSourceAutoConfiguration.class)
    @Import({SecurityConfig.class,AppCorsProperties.class,PrometheusSecurityConfiguration.class,FixtureController.class})
    static class ServletApp {
        @Bean ObservabilityProperties observability(@Value("${fixture.metrics-token-file}") String file){
            var properties=new ObservabilityProperties();
            properties.setMetricsTokenFile(file);
            return properties;
        }
        @Bean UserDetailsService fixtureUsers(){return mock(UserDetailsService.class);}
        @Bean JwtAuthenticationFilter jwt(UserDetailsService users,ObjectMapper json){
            return new JwtAuthenticationFilter(mock(JwtUtil.class),users,json);
        }
    }
    @Configuration @EnableWebMvc @EnableWebSecurity
    static class WebConfig {
        @Bean FixtureController fixtureController(){return new FixtureController();}
        @Bean @Order(10) SecurityFilterChain otherEndpoints(HttpSecurity http)throws Exception{
            return http.authorizeHttpRequests(a->a.anyRequest().authenticated()).httpBasic(b->{}).build();
        }
    }
    @RestController static class FixtureController {
        @GetMapping("/actuator/prometheus") String metrics(){return "fixture_metric 1\n";}
        @GetMapping("/actuator/env") String other(){return "must remain private";}
    }
}
