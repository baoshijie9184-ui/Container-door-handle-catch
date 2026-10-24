package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.ruanzhu.doorhandle.contracts.agent.MemoryModelConfigApi;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.*;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import java.util.Map;

/** Metadata-only private bridge. A timeout never triggers extraction or an automatic request replay. */
@Service
@ConditionalOnProperty(prefix="agentscope.model-config",name="enabled",havingValue="true")
public class MemoryModelConfigurationBridge implements MemoryModelConfigApi {
    private final String base,token;
    private final RestTemplate http;
    public MemoryModelConfigurationBridge(@Value("${mem0.service-url:http://localhost:8081}") String base,
                                          @Value("${mem0.bridge-token:}") String token){
        this.base=base.replaceAll("/$","")+"/internal/model-config";this.token=token;
        var factory=new SimpleClientHttpRequestFactory();factory.setConnectTimeout(2000);factory.setReadTimeout(5000);
        http=new RestTemplate(factory);
    }
    private JsonNode exchange(String endpoint,HttpMethod method,Object body){
        if(token==null||token.isBlank())throw new IllegalStateException("记忆配置桥接认证尚未设置");
        try{
            var headers=new HttpHeaders();headers.setContentType(MediaType.APPLICATION_JSON);headers.set("X-Doorhandle-Memory-Token",token);
            var response=http.exchange(base+endpoint,method,new HttpEntity<>(body,headers),JsonNode.class);
            if(response.getStatusCode().value()!=200||response.getBody()==null)throw new IllegalStateException();
            return response.getBody();
        }catch(RuntimeException ignored){throw new IllegalStateException("记忆模型配置结果需要核对，不重新提炼");}
    }
    @Override public void prepare(long revision,String envelope){
        var response=exchange("/prepare",HttpMethod.POST,Map.of("revision",revision,"envelope",envelope));
        if(!"PREPARED".equals(response.path("status").asText())||response.path("revision").asLong(-1)!=revision)throw new IllegalStateException("记忆配置准备回执无效");
    }
    @Override public void apply(long revision){
        var response=exchange("/apply",HttpMethod.POST,Map.of("revision",revision));
        if(!"APPLIED".equals(response.path("status").asText())||response.path("revision").asLong(-1)!=revision)throw new IllegalStateException("记忆配置应用回执无效");
    }
    @Override public long appliedRevision(){var response=exchange("/status",HttpMethod.GET,null);if(!response.path("revision").canConvertToLong()||response.path("revision").asLong()<0)throw new IllegalStateException("记忆版本回执无效");return response.path("revision").asLong();}
    @Override public void revokeCredential(String fingerprint){var response=exchange("/revoke",HttpMethod.POST,Map.of("fingerprint",fingerprint));if(!"REVOKED".equals(response.path("status").asText()))throw new IllegalStateException("记忆凭证撤销回执无效");}
}
