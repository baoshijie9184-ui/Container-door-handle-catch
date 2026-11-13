package com.ruanzhu.doorhandle.module.app.config;

import com.ruanzhu.doorhandle.framework.observability.ObservabilityProperties;
import com.ruanzhu.doorhandle.framework.observability.TelemetrySecrets;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.filter.OncePerRequestFilter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** 独立机器凭据只放行 Prometheus，不赋予业务用户权限，也不开放其他 Actuator。 */
@Configuration(proxyBeanMethods=false)
public class PrometheusSecurityConfiguration {
    @Bean @Order(0)
    SecurityFilterChain prometheusSecurity(HttpSecurity http,ObservabilityProperties properties)throws Exception{
        byte[] token=properties.getMetricsTokenFile().isBlank()?null:TelemetrySecrets.read(properties.getMetricsTokenFile()).getBytes(StandardCharsets.UTF_8);
        var filter=new OncePerRequestFilter(){
            @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain)throws ServletException,IOException{
                String supplied=request.getHeader("Authorization");
                boolean valid=token!=null&&supplied!=null&&supplied.startsWith("Bearer ")&&supplied.length()<=2055
                        &&MessageDigest.isEqual(token,supplied.substring(7).getBytes(StandardCharsets.UTF_8));
                if(!valid){response.setStatus(401);response.setHeader("WWW-Authenticate","Bearer");return;}
                if(!request.getMethod().equals("GET")){response.setStatus(405);return;}
                chain.doFilter(request,response);
            }
        };
        http.securityMatcher("/actuator/prometheus").csrf(AbstractHttpConfigurer::disable)
                .sessionManagement(s->s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(a->a.anyRequest().permitAll()).addFilterBefore(filter,UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }
}
