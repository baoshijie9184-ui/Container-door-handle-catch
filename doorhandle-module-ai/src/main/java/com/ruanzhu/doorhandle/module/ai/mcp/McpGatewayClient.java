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
        return credential(directory,scope,UUID.randomUUID().toString(),null);
    }
    String credential(Path directory,String scope,String nonce,String pool)throws Exception {
        return credential(directory,scope,nonce,pool,null);
    }
    private String credential(Path directory,String scope,String nonce,String pool,String image)throws Exception {
        Path path=directory.toAbsolutePath().normalize();int n=path.getNameCount();
        if(n<6||!path.getName(n-6).toString().equals("users")||!path.getName(n-4).toString().equals("mcp")||!path.getName(n-3).toString().equals("fetch")||!path.getName(n-2).toString().equals("installs"))throw new IllegalStateException("MCP_OWNER_PATH_INVALID");
        long owner=Long.parseLong(path.getName(n-5).toString());String operation=path.getFileName().toString();
        if(owner<1||!operation.matches("[a-f0-9-]{36}"))throw new IllegalStateException("MCP_OWNER_PATH_INVALID");
        long now=Instant.now().getEpochSecond();
        if(!UUID.fromString(nonce).toString().equals(nonce)||pool!=null&&!pool.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("MCP_CONTROL_IDENTITY_INVALID");
        var identity=new LinkedHashMap<String,Object>();identity.putAll(Map.of("aud","doorhandle-mcp-runner","owner",owner,"installation",operation,"scope",scope,"iat",now,"exp",now+60,"nonce",nonce));
        if(pool!=null)identity.put("pool_id",pool);
        if(image!=null){if(!new FetchReleasePolicy(properties).approved(Map.of("version",FetchMcpRuntime.VERSION,"packageSha256",FetchMcpRuntime.SHA,"transport","STREAMABLE_HTTP","image",image)))throw new IllegalArgumentException("MCP_RELEASE_NOT_APPROVED");identity.put("image",image);}
        return signed(identity);
    }
    private String signed(Map<String,Object> identity)throws Exception {
        String body=Base64.getUrlEncoder().withoutPadding().encodeToString(json.writeValueAsBytes(identity));
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
        if(!new FetchReleasePolicy(properties).approved(manifest)||!directory.getFileName().toString().equals(manifest.get("installation")))throw new IllegalStateException("MCP_GATEWAY_REGISTRATION_CHANGED");
        if(!(manifest.get("protectedFiles") instanceof List<?> files)||files.size()!=1||!(files.get(0) instanceof Map<?,?> file)||!"gateway-registration.json".equals(file.get("path")))throw new IllegalStateException("MCP_GATEWAY_REGISTRATION_INVALID");
        Path registration=FetchMcpRuntime.safeFile(directory,"gateway-registration.json");
        if(!Files.isRegularFile(registration)||Files.size(registration)>524288||!FetchMcpRuntime.sha(Files.readAllBytes(registration)).equals(file.get("sha256")))throw new IllegalStateException("MCP_GATEWAY_REGISTRATION_INVALID");
    }
    record Connection(McpClientWrapper client,String credential) {}
    Connection open(Path directory)throws Exception {
        return open(directory,UUID.randomUUID().toString(),null);
    }
    Connection open(Path directory,String nonce,String pool)throws Exception {
        return open(directory,nonce,pool,properties.getGatewayImage());
    }
    Connection open(Path directory,String nonce,String pool,String image)throws Exception {
        String credential=credential(directory,"execute",nonce,pool,image);
        var client=McpClientBuilder.create("fetch").streamableHttpTransport(base()+"/mcp")
                .header("Authorization","Bearer "+credential).header("X-MCP-Gateway-Key",properties.getGatewayKey())
                .timeout(Duration.ofSeconds(25)).initializationTimeout(Duration.ofSeconds(12)).buildAsync().block(Duration.ofSeconds(15));
        if(client==null)throw new IllegalStateException("MCP_GATEWAY_CONNECT_FAILED");
        return new Connection(client,credential);
    }
    String executionPool(Path directory)throws Exception {
        var request=HttpRequest.newBuilder(URI.create(base()+"/pool")).timeout(Duration.ofSeconds(8)).header("Authorization","Bearer "+credential(directory,"execute")).header("X-MCP-Gateway-Key",properties.getGatewayKey()).GET().build();
        var response=http.send(request,HttpResponse.BodyHandlers.ofInputStream());byte[] bytes;
        try(var stream=response.body()){bytes=stream.readNBytes(1025);}
        if(response.statusCode()!=200||bytes.length>1024)throw new IllegalStateException("MCP_EXECUTION_POOL_UNAVAILABLE");
        var pool=json.readTree(bytes).path("poolId");if(!pool.isTextual()||!pool.asText().matches("[a-f0-9]{32}"))throw new IllegalStateException("MCP_EXECUTION_POOL_INVALID");return pool.asText();
    }
    StopReceipt cancel(Path directory,String nonce,String pool){
        try{return cancel(credential(directory,"execute",nonce,pool));}
        catch(Exception error){return new StopReceipt(nonce,false,false,"NEEDS_REVIEW");}
    }
    record StopReceipt(String executionNonce,boolean exitVerified,boolean cleanupConfirmed,String state){
        Map<String,Object> evidence(){return Map.of("executionNonce",executionNonce,"exitVerified",exitVerified,"cleanupConfirmed",cleanupConfirmed,"state",state,"transport","STREAMABLE_HTTP");}
    }
    Map<String,Object> imageInventory(Path directory)throws Exception {
        var request=HttpRequest.newBuilder(URI.create(base()+"/images")).timeout(Duration.ofSeconds(45)).header("Authorization","Bearer "+credential(directory,"image-inspect")).header("X-MCP-Gateway-Key",properties.getGatewayKey()).GET().build();
        var data=imageResponse(request,16384);
        if(!Integer.valueOf(2).equals(data.get("protocol"))||!properties.getGatewayImage().equals(data.get("currentImage"))||!(data.get("poolId") instanceof String pool)||!pool.matches("[a-f0-9]{32}")||!(data.get("items") instanceof List<?> items)||items.size()>8)throw new IllegalStateException("MCP_IMAGE_INVENTORY_INVALID");
        return data;
    }
    Map<String,Object> imageControl(Path directory,String image,String action,String requestId,String pool)throws Exception {
        if(!Set.of("prepare","delete","receipt").contains(action)||image==null||!image.matches("sha256:[a-f0-9]{64}")||pool==null||!pool.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("MCP_IMAGE_CONTROL_INVALID");
        if(!"receipt".equals(action)&&!new FetchReleasePolicy(properties).approved(Map.of("version",FetchMcpRuntime.VERSION,"packageSha256",FetchMcpRuntime.SHA,"transport","STREAMABLE_HTTP","image",image)))throw new IllegalArgumentException("MCP_IMAGE_NOT_APPROVED");
        var token=credential(directory,"image-"+action,requestId,pool).split("\\.");var claims=json.readValue(Base64.getUrlDecoder().decode(token[0]),new TypeReference<LinkedHashMap<String,Object>>(){});claims.put("image",image);claims.put("image_policy",4);
        var request=HttpRequest.newBuilder(URI.create(base()+"/images/"+action)).timeout(Duration.ofSeconds(120)).header("Authorization","Bearer "+signed(claims)).header("X-MCP-Gateway-Key",properties.getGatewayKey()).POST(HttpRequest.BodyPublishers.noBody()).build();
        var data=imageResponse(request,8192);
        if(!image.equals(data.get("image"))||!requestId.equals(data.get("request"))||!pool.equals(data.get("poolId"))||!(data.get("owner") instanceof Number owner)||owner.longValue()!=((Number)claims.get("owner")).longValue()||!(data.get("imageAbsent") instanceof Boolean)||!Set.of("FENCED","PREPARED","ARCHIVING","REMOVING","REMOVED","NEEDS_REVIEW").contains(data.get("state")))throw new IllegalStateException("MCP_IMAGE_RECEIPT_MISMATCH");
        if("REMOVED".equals(data.get("state"))&&(!Boolean.TRUE.equals(data.get("imageAbsent"))||!(data.get("archiveSha256") instanceof String digest)||!digest.matches("[a-f0-9]{64}")))throw new IllegalStateException("MCP_IMAGE_REMOVAL_UNVERIFIED");
        if(data.get("archiveSha256")!=null&&(!(data.get("archiveSha256") instanceof String hash)||!hash.matches("[a-f0-9]{64}")))throw new IllegalStateException("MCP_IMAGE_ARCHIVE_INVALID");
        return data;
    }
    private Map<String,Object> imageResponse(HttpRequest request,int limit)throws Exception {
        var response=http.send(request,HttpResponse.BodyHandlers.ofInputStream());byte[] bytes;try(var stream=response.body()){bytes=stream.readNBytes(limit+1);}
        if(response.statusCode()!=200||bytes.length>limit)throw new IllegalStateException("MCP_IMAGE_CONTROL_UNAVAILABLE");return json.readValue(bytes,new TypeReference<LinkedHashMap<String,Object>>(){});
    }
    Map<String,Object> installationController(Path directory,String controller,String started,String pool)throws Exception {
        if(controller==null||!controller.matches("[a-f0-9]{12,64}")||started!=null&&(controller.length()!=64||pool==null||!pool.matches("[a-f0-9]{32}")))throw new IllegalArgumentException("MCP_INSTALL_CONTROLLER_INVALID");
        var original=credential(directory,"install-control").split("\\.");
        var claims=json.readValue(Base64.getUrlDecoder().decode(original[0]),new TypeReference<LinkedHashMap<String,Object>>(){});
        claims.put("controller_id",controller);if(started!=null){claims.put("controller_started",started);claims.put("pool_id",pool);}
        var request=HttpRequest.newBuilder(URI.create(base()+"/install-controller")).timeout(Duration.ofSeconds(8)).header("Authorization","Bearer "+signed(claims)).header("X-MCP-Gateway-Key",properties.getGatewayKey()).GET().build();
        var response=http.send(request,HttpResponse.BodyHandlers.ofInputStream());byte[] bytes;try(var stream=response.body()){bytes=stream.readNBytes(2049);}
        if(response.statusCode()!=200||bytes.length>2048)throw new IllegalStateException("MCP_INSTALL_CONTROLLER_UNAVAILABLE");var data=json.readTree(bytes);
        if(!data.path("owner").isIntegralNumber()||data.path("owner").asLong()!=((Number)claims.get("owner")).longValue()||!Objects.equals(claims.get("installation"),data.path("installation").asText())||!Objects.equals(claims.get("nonce"),data.path("requestNonce").asText())||!controller.equals(data.path("requestedController").asText())||started!=null&&!started.equals(data.path("requestedStarted").asText()))throw new IllegalStateException("MCP_INSTALL_CONTROLLER_RECEIPT_MISMATCH");
        if(!data.path("poolId").asText().matches("[a-f0-9]{32}")||pool!=null&&!pool.equals(data.path("poolId").asText()))throw new IllegalStateException("MCP_INSTALL_CONTROLLER_POOL_CHANGED");
        if(started!=null)return Map.of("stopped",data.path("stopped").isBoolean()&&data.path("stopped").asBoolean());
        String id=data.path("controllerId").asText(),generation=data.path("controllerStarted").asText();
        if(!id.matches("[a-f0-9]{64}")||!id.startsWith(controller)||generation.isBlank()||generation.length()>64)throw new IllegalStateException("MCP_INSTALL_CONTROLLER_INVALID");
        return Map.of("id",id,"started",generation,"pool",data.path("poolId").asText());
    }
    private Map<String,Object> original(String credential)throws Exception{
        var parts=credential.split("\\.");if(parts.length!=2)throw new IllegalArgumentException("MCP_CONTROL_IDENTITY_INVALID");
        Mac mac=Mac.getInstance("HmacSHA256");mac.init(new SecretKeySpec(properties.getGatewaySecret().getBytes(StandardCharsets.UTF_8),"HmacSHA256"));
        if(!java.security.MessageDigest.isEqual(mac.doFinal(parts[0].getBytes(StandardCharsets.US_ASCII)),Base64.getUrlDecoder().decode(parts[1])))throw new IllegalArgumentException("MCP_CONTROL_IDENTITY_INVALID");
        var body=json.readValue(Base64.getUrlDecoder().decode(parts[0]),new TypeReference<LinkedHashMap<String,Object>>(){});
        if(!"doorhandle-mcp-runner".equals(body.get("aud"))||!"execute".equals(body.get("scope"))||!(body.get("owner") instanceof Number owner)||owner.longValue()<1)throw new IllegalArgumentException("MCP_CONTROL_IDENTITY_INVALID");
        for(String field:List.of("nonce","installation"))if(!(body.get(field) instanceof String value)||!UUID.fromString(value).toString().equals(value))throw new IllegalArgumentException("MCP_CONTROL_IDENTITY_INVALID");return body;
    }
    StopReceipt cancel(String credential){
        String nonce="";
        try{
            var old=original(credential);nonce=(String)old.get("nonce");long now=Instant.now().getEpochSecond();
            var identity=new LinkedHashMap<String,Object>();identity.putAll(Map.of("aud","doorhandle-mcp-runner","owner",old.get("owner"),"installation",old.get("installation"),"scope","control","execution_nonce",nonce,"nonce",UUID.randomUUID().toString(),"iat",now,"exp",now+60));
            if(old.containsKey("pool_id"))identity.put("pool_id",old.get("pool_id"));String control=signed(identity);
            var request=HttpRequest.newBuilder(URI.create(base()+"/cancel")).timeout(Duration.ofSeconds(20)).header("Authorization","Bearer "+control).header("X-MCP-Gateway-Key",properties.getGatewayKey()).POST(HttpRequest.BodyPublishers.noBody()).build();
            var response=http.send(request,HttpResponse.BodyHandlers.ofInputStream());byte[] bytes;try(var stream=response.body()){bytes=stream.readNBytes(16385);}
            if(response.statusCode()!=200||bytes.length>16384)return new StopReceipt(nonce,false,false,"NEEDS_REVIEW");
            var receipt=json.readTree(bytes);
            if(old.containsKey("pool_id")&&!Objects.equals(old.get("pool_id"),receipt.path("poolId").asText()))return new StopReceipt(nonce,false,false,"NEEDS_REVIEW");
            if(!receipt.path("owner").isIntegralNumber()||receipt.path("owner").asLong()!=((Number)old.get("owner")).longValue()||!Objects.equals(old.get("installation"),receipt.path("installation").asText())||!nonce.equals(receipt.path("nonce").asText())||!receipt.path("exitVerified").isBoolean()||!receipt.path("cleanupConfirmed").isBoolean())return new StopReceipt(nonce,false,false,"NEEDS_REVIEW");
            boolean exited=receipt.path("exitVerified").booleanValue(),cleaned=receipt.path("cleanupConfirmed").booleanValue();
            if(cleaned&&!exited)return new StopReceipt(nonce,false,false,"NEEDS_REVIEW");return new StopReceipt(nonce,exited,cleaned,cleaned?"REMOVED":exited?"EXITED":"NEEDS_REVIEW");
        }catch(InterruptedException error){Thread.currentThread().interrupt();}catch(Exception ignored){/* A request or a legacy HTTP 200 is not an exit receipt. */}
        return new StopReceipt(nonce,false,false,"NEEDS_REVIEW");
    }
}
