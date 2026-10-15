package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.system.security.SensitiveDataSanitizer;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class Mem0ClientTest {
    @Test void disabledOrUnavailablePreferencesSkipBothRetrievalAndQueuedExtraction()throws Exception{
        var calls=new java.util.concurrent.atomic.AtomicInteger();
        var server=com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/memories",exchange->{calls.incrementAndGet();assertThat(exchange.getRequestHeaders().getFirst("X-Doorhandle-Memory-Token")).isEqualTo("fixture-bridge-token");byte[] bytes="{\"code\":200,\"data\":[]}".getBytes(java.nio.charset.StandardCharsets.UTF_8);exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();});server.start();
        try{
            var preferences=org.mockito.Mockito.mock(MemoryPreferenceService.class);var owner=new TenantContext(42L,"alice");var client=new Mem0Client(new SensitiveDataSanitizer(),preferences);
            org.springframework.test.util.ReflectionTestUtils.setField(client,"enabled",true);org.springframework.test.util.ReflectionTestUtils.setField(client,"bridgeToken","fixture-bridge-token");org.springframework.test.util.ReflectionTestUtils.setField(client,"serviceUrl","http://127.0.0.1:"+server.getAddress().getPort());
            org.mockito.Mockito.when(preferences.get(owner)).thenReturn(new com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Preference(false,false,1,null));
            assertThat(client.searchAccountMemories(owner,"s1","问题",5)).isEmpty();client.addMemoryAsync(owner,"s1","待保存",java.util.Map.of());assertThat(calls).hasValue(0);
            org.mockito.Mockito.when(preferences.get(owner)).thenReturn(new com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Preference(true,false,2,null));client.searchAccountMemories(owner,"s2","问题",5);assertThat(calls).hasValue(1);client.addMemoryAsync(owner,"s2","排队之后关闭保存",java.util.Map.of());assertThat(calls).hasValue(1);
            org.mockito.Mockito.when(preferences.get(owner)).thenThrow(new IllegalStateException("fixture SQL unavailable"));client.searchAccountMemories(owner,"s2","问题",5);client.addMemoryAsync(owner,"s2","不得保存",java.util.Map.of());assertThat(calls).hasValue(1);
        }finally{server.stop(0);}
    }
    @Test void managementErrorsRemainFailuresAndRequirePrivateBridgeAuthentication()throws Exception{
        var client=new Mem0Client(new SensitiveDataSanitizer());org.springframework.test.util.ReflectionTestUtils.setField(client,"enabled",true);
        assertThat(org.assertj.core.api.Assertions.catchThrowable(()->client.listOwned(new TenantContext(42L,"alice"),20))).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        var server=com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1",0),0);server.createContext("/memories/owned/delete",exchange->{byte[] bytes="{\"detail\":\"SECRET_BODY\"}".getBytes();exchange.sendResponseHeaders(404,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();});server.start();
        try{
            org.springframework.test.util.ReflectionTestUtils.setField(client,"bridgeToken","fixture-bridge-token");org.springframework.test.util.ReflectionTestUtils.setField(client,"serviceUrl","http://127.0.0.1:"+server.getAddress().getPort());
            org.assertj.core.api.Assertions.assertThatThrownBy(()->client.deleteOwned(new TenantContext(42L,"alice"),"other","a".repeat(64))).hasMessageContaining("404").hasMessageNotContaining("SECRET_BODY");
        }finally{server.stop(0);}
    }
    @Test void accountSearchSendsStableUserAndAppScopeWithSourceSessionToHttpBridge()throws Exception{
        var bodies=new java.util.ArrayList<com.fasterxml.jackson.databind.JsonNode>();var json=new com.fasterxml.jackson.databind.ObjectMapper();
        var server=com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/memories/search",exchange->{bodies.add(json.readTree(exchange.getRequestBody()));byte[] result="{\"code\":200,\"data\":[]}".getBytes(java.nio.charset.StandardCharsets.UTF_8);exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(200,result.length);exchange.getResponseBody().write(result);exchange.close();});server.start();
        try{
            var client=new Mem0Client(new SensitiveDataSanitizer());org.springframework.test.util.ReflectionTestUtils.setField(client,"enabled",true);org.springframework.test.util.ReflectionTestUtils.setField(client,"serviceUrl","http://127.0.0.1:"+server.getAddress().getPort());
            client.searchAccountMemories(new TenantContext(42L,"alice"),"s1","报告",5);client.searchAccountMemories(new TenantContext(42L,"alice"),"s2","报告",5);client.searchAccountMemories(new TenantContext(43L,"bob"),"s2","报告",5);
            assertThat(bodies).hasSize(3);assertThat(bodies.get(0).path("scope").asText()).isEqualTo("ACCOUNT");assertThat(bodies.get(1).path("user_id").asText()).isEqualTo(bodies.get(0).path("user_id").asText());assertThat(bodies.get(2).path("user_id").asText()).isNotEqualTo(bodies.get(0).path("user_id").asText());assertThat(bodies.get(0).path("app_id").asText()).isEqualTo("doorhandlecatch");assertThat(bodies.get(0).path("run_id").asText()).isEqualTo("s1");assertThat(bodies.get(1).path("run_id").asText()).isEqualTo("s2");
        }finally{server.stop(0);}
    }
    @Test
    void exposesNoStringScopedMemoryOperations() {
        assertThat(Arrays.stream(Mem0Client.class.getMethods())
                .filter(method -> Set.of("addMemory", "addMemoryAsync", "searchMemories", "searchAccountMemories", "listOwned", "deleteOwned")
                        .contains(method.getName()))
                .filter(method -> method.getParameterCount() > 0)
                .filter(method -> method.getParameterTypes()[0] == String.class))
                .isEmpty();
    }

    @Test
    void buildsNamespacedUserApplicationAndRunScope() {
        Mem0Client client = new Mem0Client(new SensitiveDataSanitizer());

        assertThat(client.buildScope(new TenantContext(42L, "alice"), "sess_abc"))
                .containsEntry("user_id", "doorhandlecatch:user:42")
                .containsEntry("app_id", "doorhandlecatch")
                .containsEntry("run_id", "sess_abc");
    }
}
