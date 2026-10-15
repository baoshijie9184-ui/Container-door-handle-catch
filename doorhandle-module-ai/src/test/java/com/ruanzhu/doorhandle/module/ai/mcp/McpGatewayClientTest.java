package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

class McpGatewayClientTest {
    @TempDir Path root;
    private final ObjectMapper json = new ObjectMapper();
    private LocalMcpProperties properties(int port) {
        var p = new LocalMcpProperties(); p.setTransport("GATEWAY");
        p.setGatewayUrl("http://127.0.0.1:"+port+"/mcp/fetch");
        p.setGatewaySecret("test-secret-with-at-least-32-bytes-000");
        p.setGatewayKey("gateway-key-with-at-least-32-bytes-000");
        p.setGatewayImage("sha256:"+"a".repeat(64)); return p;
    }
    @Test void signsServerOwnedIdentityAndRejectsOtherPaths() throws Exception {
        var p=properties(8080);var client=new McpGatewayClient(p,json);
        Path path=root.resolve("users/42/mcp/fetch/installs/"+UUID.randomUUID());
        String[] token=client.credential(path,"execute").split("\\.");
        var identity=json.readTree(Base64.getUrlDecoder().decode(token[0]));
        assertThat(identity.get("owner").asLong()).isEqualTo(42);
        assertThat(identity.get("installation").asText()).isEqualTo(path.getFileName().toString());
        assertThat(identity.get("scope").asText()).isEqualTo("execute");
        assertThat(identity.get("exp").asLong()-identity.get("iat").asLong()).isEqualTo(60);
        Mac mac=Mac.getInstance("HmacSHA256");mac.init(new SecretKeySpec(p.getGatewaySecret().getBytes(StandardCharsets.UTF_8),"HmacSHA256"));
        assertThat(Base64.getUrlDecoder().decode(token[1])).isEqualTo(mac.doFinal(token[0].getBytes(StandardCharsets.US_ASCII)));
        assertThatThrownBy(()->client.credential(root.resolve("other/42/mcp/fetch/installs/"+UUID.randomUUID()),"execute")).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(()->client.credential(root.resolve("users/0/mcp/fetch/installs/"+UUID.randomUUID()),"execute")).isInstanceOf(IllegalStateException.class);
    }
    @Test void installsPinnedGatewayRegistrationAndDetectsTamperingAndImageMigration() throws Exception {
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        var p=properties(server.getAddress().getPort());
        server.createContext("/mcp/fetch/artifact",exchange->{
            assertThat(exchange.getRequestHeaders().getFirst("X-MCP-Gateway-Key")).isEqualTo(p.getGatewayKey());
            byte[] body=json.writeValueAsBytes(Map.of("version",FetchMcpRuntime.VERSION,"packageSha256",FetchMcpRuntime.SHA,
                    "transport","STREAMABLE_HTTP","image",p.getGatewayImage(),"artifacts",List.of(),"licenses",List.of()));
            exchange.sendResponseHeaders(200,body.length);exchange.getResponseBody().write(body);exchange.close();
        });server.start();
        try {
            var client=new McpGatewayClient(p,json);
            Path path=root.resolve("users/42/mcp/fetch/installs/"+UUID.randomUUID());
            var manifest=client.install(path);client.validate(path,manifest);
            var runtime=new FetchMcpRuntime(p,json);
            assertThat(runtime.requiresMigration(manifest)).isFalse();
            assertThat(runtime.requiresMigration(Map.of("transport","STDIO"))).isTrue();
            p.setGatewayImage("sha256:"+"b".repeat(64));
            assertThat(runtime.requiresMigration(manifest)).isTrue();
            assertThatThrownBy(()->client.validate(path,manifest)).isInstanceOf(IllegalStateException.class);
            p.setGatewayImage("sha256:"+"a".repeat(64));
            Files.writeString(path.resolve("gateway-registration.json"),"tampered");
            assertThatThrownBy(()->client.validate(path,manifest)).isInstanceOf(IllegalStateException.class);
        } finally {server.stop(0);}
    }
}
