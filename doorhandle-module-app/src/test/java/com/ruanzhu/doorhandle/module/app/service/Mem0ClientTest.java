package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.system.security.SensitiveDataSanitizer;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class Mem0ClientTest {
    @Test void reviewHttpBridgePreservesPendingStatesOwnershipVersionsAndUnknownUsage()throws Exception{
        var json=new com.fasterxml.jackson.databind.ObjectMapper();var paths=new java.util.ArrayList<String>();var bodies=new java.util.ArrayList<com.fasterxml.jackson.databind.JsonNode>();
        var payload=json.readTree("""
                {"id":"review","sourceId":"mine","status":"RUNNING","revision":0,"source":null,"sourceStale":false,
                "judgmentStatus":"PENDING","candidates":[],"decisions":[],"createdAt":"2026-10-18T12:00:00+08:00",
                "updatedAt":"2026-10-18T12:00:00+08:00","searchLimit":20,"modelCalled":null,"modelName":null,
                "modelMillis":null,"inputTokens":null,"outputTokens":null,"totalTokens":null,"usageSource":"UNKNOWN"}
                """);
        var response=new java.util.concurrent.atomic.AtomicReference<com.fasterxml.jackson.databind.JsonNode>(payload);
        var owner=new TenantContext(42L,"alice");var server=com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/memories/reviews",exchange->{
            var body=json.readTree(exchange.getRequestBody());bodies.add(body);String path=exchange.getRequestURI().getPath();paths.add(path);
            assertThat(body.path("user_id").asText()).isEqualTo(owner.mem0UserId());assertThat(body.path("app_id").asText()).isEqualTo("doorhandlecatch");
            assertThat(exchange.getRequestHeaders().getFirst("X-Doorhandle-Memory-Token")).isEqualTo("fixture");assertThat(exchange.getRequestHeaders().getFirst("X-Doorhandle-Memory-Protocol")).isEqualTo("2");
            int code=path.endsWith("start")?202:200;
            Object data=path.endsWith("list")?java.util.List.of(java.util.Map.of("id","review","sourceId","mine","status","RUNNING","createdAt","2026-10-18T12:00:00+08:00")):response.get();
            byte[] bytes=json.writeValueAsBytes(java.util.Map.of("code",code,"data",data));exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(code,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();
        });server.start();
        try{
            var client=new Mem0Client(new SensitiveDataSanitizer());org.springframework.test.util.ReflectionTestUtils.setField(client,"enabled",true);org.springframework.test.util.ReflectionTestUtils.setField(client,"bridgeToken","fixture");org.springframework.test.util.ReflectionTestUtils.setField(client,"serviceUrl","http://127.0.0.1:"+server.getAddress().getPort());
            var pending=client.startReview(owner,"mine",new com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.StartReview("review","a".repeat(64),3));
            assertThat(pending.status()).isEqualTo("RUNNING");assertThat(pending.inputTokens()).isNull();assertThat(pending.modelCalled()).isNull();
            assertThat(bodies.get(0).path("expected_revision").asInt()).isEqualTo(3);assertThat(bodies.get(0).path("memory_id").asText()).isEqualTo("mine");
            assertThat(client.reviewHistory(owner)).hasSize(1);assertThat(client.getReview(owner,"review").usageSource()).isEqualTo("UNKNOWN");
            var ready=payload.deepCopy();((com.fasterxml.jackson.databind.node.ObjectNode)ready).put("status","READY").put("revision",1).put("judgmentStatus","COMPLETE").put("modelCalled",true).put("outputTokens",0).put("inputTokens",17).put("totalTokens",17).put("usageSource","PROVIDER");response.set(ready);
            assertThat(client.getReview(owner,"review").outputTokens()).isZero();
            var decision=new com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.ResolveReview("decision",1,"candidate","KEEP_BOTH",true);
            client.resolveReview(owner,"review",decision);assertThat(bodies.get(bodies.size()-1).path("decision_id").asText()).isEqualTo("decision");assertThat(bodies.get(bodies.size()-1).path("request_id").asText()).isEqualTo("review");
            var invalid=ready.deepCopy();((com.fasterxml.jackson.databind.node.ObjectNode)invalid).put("inputTokens",-1);response.set(invalid);
            org.assertj.core.api.Assertions.assertThatThrownBy(()->client.getReview(owner,"review")).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
            response.set(((com.fasterxml.jackson.databind.node.ObjectNode)ready.deepCopy()).put("id","another-review"));
            org.assertj.core.api.Assertions.assertThatThrownBy(()->client.getReview(owner,"review")).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
            assertThat(paths.subList(0,5)).containsExactly("/memories/reviews/start","/memories/reviews/list","/memories/reviews/get","/memories/reviews/get","/memories/reviews/resolve");
        }finally{server.stop(0);}
    }
    @Test void lifecycleBridgeUsesPrivateRoutesAndRejectsMismatchedCompletionProof()throws Exception{
        var json=new com.fasterxml.jackson.databind.ObjectMapper();var paths=new java.util.ArrayList<String>();var stale=new java.util.concurrent.atomic.AtomicBoolean();
        var owner=new TenantContext(42L,"alice");var server=com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/memories",exchange->{
            var body=json.readTree(exchange.getRequestBody());String path=exchange.getRequestURI().getPath();paths.add(path);
            assertThat(body.path("user_id").asText()).isEqualTo(owner.mem0UserId());assertThat(exchange.getRequestHeaders().getFirst("X-Doorhandle-Memory-Token")).isEqualTo("fixture");assertThat(exchange.getRequestHeaders().getFirst("X-Doorhandle-Memory-Protocol")).isEqualTo("2");
            var data=new com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Lifecycle("mine",stale.get()?0:1,"EXCLUDED",null,false,"NONE",null);
            byte[] response=json.writeValueAsBytes(java.util.Map.of("code",200,"data",path.endsWith("/list")?java.util.List.of(data):data));exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(200,response.length);exchange.getResponseBody().write(response);exchange.close();
        });server.start();
        try{
            var client=new Mem0Client(new SensitiveDataSanitizer());org.springframework.test.util.ReflectionTestUtils.setField(client,"enabled",true);org.springframework.test.util.ReflectionTestUtils.setField(client,"bridgeToken","fixture");org.springframework.test.util.ReflectionTestUtils.setField(client,"serviceUrl","http://127.0.0.1:"+server.getAddress().getPort());
            var request=new com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.ChangeLifecycle("key","a".repeat(64),0,"EXCLUDED",null,false,true);
            assertThat(client.changeLifecycle(owner,"mine",request).revision()).isEqualTo(1);
            assertThat(client.lifecycleHistory(owner)).hasSize(1);assertThat(client.verifyCleanup(owner,"mine").memoryId()).isEqualTo("mine");
            stale.set(true);assertThat(org.assertj.core.api.Assertions.catchThrowable(()->client.changeLifecycle(owner,"mine",request))).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
            assertThat(paths).containsExactly("/memories/owned/lifecycle","/memories/lifecycle/list","/memories/lifecycle/verify","/memories/owned/lifecycle");
        }finally{server.stop(0);}
    }
    @Test void anAcceptedExtractionIsPendingAndItsStableTurnIdIsSentWithoutFalseSuccess()throws Exception{
        var json=new com.fasterxml.jackson.databind.ObjectMapper();var bodies=new java.util.ArrayList<com.fasterxml.jackson.databind.JsonNode>();
        var preferences=org.mockito.Mockito.mock(MemoryPreferenceService.class);var owner=new TenantContext(42L,"alice");
        org.mockito.Mockito.when(preferences.get(owner)).thenReturn(new com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Preference(true,true,0,null));
        var server=com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/memories/add",exchange->{var body=json.readTree(exchange.getRequestBody());bodies.add(body);byte[] response=json.writeValueAsBytes(java.util.Map.of("code",202,"data",java.util.Map.of("operation",java.util.Map.of("requestId",body.path("request_id").asText(),"status","RUNNING"))));exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(202,response.length);exchange.getResponseBody().write(response);exchange.close();});server.start();
        try{
            var client=new Mem0Client(new SensitiveDataSanitizer(),preferences);org.springframework.test.util.ReflectionTestUtils.setField(client,"enabled",true);org.springframework.test.util.ReflectionTestUtils.setField(client,"bridgeToken","fixture");org.springframework.test.util.ReflectionTestUtils.setField(client,"serviceUrl","http://127.0.0.1:"+server.getAddress().getPort());
            assertThat(client.addMemory(owner,"s1","private",java.util.Map.of("turn_id",12,"timestamp",1))).containsEntry("status","RUNNING");
            client.addMemory(owner,"s1","private",java.util.Map.of("turn_id",12,"timestamp",2));
            assertThat(bodies).hasSize(2);String id=bodies.get(0).path("request_id").asText();assertThat(id).matches("[a-f0-9]{64}");assertThat(bodies.get(1).path("request_id").asText()).isEqualTo(id);
            org.mockito.Mockito.verify(preferences,org.mockito.Mockito.never()).deletionOutcome(org.mockito.Mockito.any(),org.mockito.Mockito.anyString(),org.mockito.Mockito.anyString());
        }finally{server.stop(0);}
    }
    @Test void auditFailurePreventsCallingTheMemoryBridge(){
        var preferences=org.mockito.Mockito.mock(MemoryPreferenceService.class);var owner=new TenantContext(42L,"alice");
        org.mockito.Mockito.when(preferences.get(owner)).thenReturn(new com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Preference(true,true,0,null));
        org.mockito.Mockito.when(preferences.reserveAutomatic(org.mockito.Mockito.eq(owner),org.mockito.Mockito.anyString(),org.mockito.Mockito.anyString())).thenThrow(new IllegalStateException("fixture audit unavailable"));
        var client=new Mem0Client(new SensitiveDataSanitizer(),preferences);org.springframework.test.util.ReflectionTestUtils.setField(client,"enabled",true);org.springframework.test.util.ReflectionTestUtils.setField(client,"serviceUrl","invalid-no-http-request");
        assertThat(client.addMemory(owner,"s1","private",java.util.Map.of())).isEmpty();org.mockito.Mockito.verify(preferences,org.mockito.Mockito.never()).deletionOutcome(org.mockito.Mockito.any(),org.mockito.Mockito.anyString(),org.mockito.Mockito.anyString());
    }
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
