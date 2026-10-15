package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentscope.core.tool.mcp.McpClientBuilder;
import io.agentscope.core.tool.mcp.McpClientWrapper;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;

/** 内网 MCP 通道；身份只从服务端生成的用户安装目录推导，不接受模型传入的路由或命令。 */
final class McpGatewayClient {
    private final LocalMcpProperties properties;
    private final ObjectMapper json;
    private final HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).followRedirects(HttpClient.Redirect.NEVER).build();
    McpGatewayClient(LocalMcpProperties properties,ObjectMapper json){this.properties=properties;this.json=json;}

    String base(){
        URI uri=URI.create(properties.getGatewayUrl());
        if(!Set.of("http","https").contains(uri.getScheme())||uri.getHost()==null||uri.getUserInfo()!=null||uri.getQuery()!=null||uri.getFragment()!=null||!uri.getPath().equals("/mcp/fetch"))throw new IllegalStateException("MCP_GATEWAY_CONFIG_INVALID");
        if(properties.getGatewaySecret().getBytes(StandardCharsets.UTF_8).length<32||properties.getGatewayKey().length()<32||!properties.getGatewayImage().matches("sha256:[a-f0-9]{64}"))throw new IllegalStateException("MCP_GATEWAY_CONFIG_INVALID");
        return uri.toString();
    }
    String credential(Path directory,String scope)throws Exception {
        Path path=directory.toAbsolutePath().normalize();int n=path.getNameCount();
        if(n<6||!path.getName(n-6).toString().equals("users")||!path.getName(n-4).toString().equals("mcp")||!path.getName(n-3).toString().equals("fetch")||!path.getName(n-2).toString().equals("installs"))throw new IllegalStateException("MCP_OWNER_PATH_INVALID");
        long owner=Long.parseLong(path.getName(n-5).toString());String operation=path.getFileName().toString();
        if(owner<1||!operation.matches("[a-f0-9-]{36}"))throw new IllegalStateException("MCP_OWNER_PATH_INVALID");
        long now=Instant.now().getEpochSecond();
        String body=Base64.getUrlEncoder().withoutPadding().encodeToString(json.writeValueAsBytes(Map.of("aud","doorhandle-mcp-runner","owner",owner,"installation",operation,"scope",scope,"iat",now,"exp",now+60,"nonce",UUID.randomUUID().toString())));
        Mac mac=Mac.getInstance("HmacSHA256");mac.init(new SecretKeySpec(properties.getGatewaySecret().getBytes(StandardCharsets.UTF_8),"HmacSHA256"));
        return body+"."+Base64.getUrlEncoder().withoutPadding().encodeToString(mac.doFinal(body.getBytes(StandardCharsets.US_ASCII)));
    }
    Map<String,Object> install(Path directory)throws Exception {
        base();String credential=credential(directory,"install");
        var request=HttpRequest.newBuilder(URI.create(base()+"/artifact")).timeout(Duration.ofSeconds(15)).header("Authorization","Bearer "+credential).header("X-MCP-Gateway-Key",properties.getGatewayKey()).GET().build();
        var response=http.send(request,HttpResponse.BodyHandlers.ofInputStream());
        byte[] bytes;try(var stream=response.body()){bytes=stream.readNBytes(524289);}
        if(response.statusCode()!=200||bytes.length>524288)throw new IllegalStateException("MCP_GATEWAY_ARTIFACT_UNAVAILABLE");
        var manifest=json.readValue(bytes,new TypeReference<LinkedHashMap<String,Object>>(){});
        if(!FetchMcpRuntime.VERSION.equals(manifest.get("version"))||!FetchMcpRuntime.SHA.equals(manifest.get("packageSha256"))||!properties.getGatewayImage().equals(manifest.get("image"))||!"STREAMABLE_HTTP".equals(manifest.get("transport")))throw new IllegalStateException("MCP_GATEWAY_ARTIFACT_MISMATCH");
        FetchMcpRuntime.secure(directory);Files.createDirectories(directory);FetchMcpRuntime.secure(directory);
        Files.write(directory.resolve("gateway-registration.json"),bytes,StandardOpenOption.CREATE_NEW);
        manifest.put("protectedFiles",List.of(Map.of("path","gateway-registration.json","sha256",FetchMcpRuntime.sha(bytes))));
        manifest.put("installation",directory.getFileName().toString());
        Files.writeString(directory.resolve("manifest.json"),json.writeValueAsString(manifest),StandardOpenOption.CREATE_NEW);
        return manifest;
    }
    void validate(Path directory,Map<String,Object> manifest)throws Exception {
        base();FetchMcpRuntime.secure(directory);
        if(!"STREAMABLE_HTTP".equals(manifest.get("transport"))||!properties.getGatewayImage().equals(manifest.get("image"))||!directory.getFileName().toString().equals(manifest.get("installation"))||!FetchMcpRuntime.VERSION.equals(manifest.get("version"))||!FetchMcpRuntime.SHA.equals(manifest.get("packageSha256")))throw new IllegalStateException("MCP_GATEWAY_REGISTRATION_CHANGED");
        if(!(manifest.get("protectedFiles") instanceof List<?> files)||files.size()!=1||!(files.get(0) instanceof Map<?,?> file)||!"gateway-registration.json".equals(file.get("path")))throw new IllegalStateException("MCP_GATEWAY_REGISTRATION_INVALID");
        Path registration=FetchMcpRuntime.safeFile(directory,"gateway-registration.json");
        if(!Files.isRegularFile(registration)||Files.size(registration)>524288||!FetchMcpRuntime.sha(Files.readAllBytes(registration)).equals(file.get("sha256")))throw new IllegalStateException("MCP_GATEWAY_REGISTRATION_INVALID");
    }
    record Connection(McpClientWrapper client,String credential) {}
    Connection open(Path directory)throws Exception {
        String credential=credential(directory,"execute");
        var client=McpClientBuilder.create("fetch").streamableHttpTransport(base()+"/mcp")
                .header("Authorization","Bearer "+credential).header("X-MCP-Gateway-Key",properties.getGatewayKey())
                .timeout(Duration.ofSeconds(25)).initializationTimeout(Duration.ofSeconds(12)).buildAsync().block(Duration.ofSeconds(15));
        if(client==null)throw new IllegalStateException("MCP_GATEWAY_CONNECT_FAILED");
        return new Connection(client,credential);
    }
    void cancel(String credential){
        try{var request=HttpRequest.newBuilder(URI.create(base()+"/cancel")).timeout(Duration.ofSeconds(5)).header("Authorization","Bearer "+credential).header("X-MCP-Gateway-Key",properties.getGatewayKey()).POST(HttpRequest.BodyPublishers.noBody()).build();http.send(request,HttpResponse.BodyHandlers.discarding());}
        catch(InterruptedException error){Thread.currentThread().interrupt();}catch(Exception ignored){/* 运行器自身仍强制执行超时与清理。 */}
    }
}
