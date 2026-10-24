package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** Fixed local lifecycle commands. The helper never receives tool arguments, arbitrary executables or URLs. */
final class NativeFetchProcessClient {
    private final LocalMcpProperties properties;private final ObjectMapper json;
    NativeFetchProcessClient(LocalMcpProperties properties,ObjectMapper json){this.properties=properties;this.json=json;}
    Path helper()throws Exception {
        var path=Path.of(properties.getNativeProcessHelper().replace("${user.dir}",System.getProperty("user.dir"))).toAbsolutePath().normalize();
        FetchMcpRuntime.secure(path);if(!Files.isRegularFile(path)||Files.size(path)>65536)throw new IllegalStateException("MCP_NATIVE_HELPER_INVALID");return path;
    }
    String pool(Path directory)throws Exception {
        var result=command("pool",directory,null,null);var pool=result.path("poolId");
        if(!pool.isTextual()||!pool.asText().matches("[a-f0-9]{32}"))throw new IllegalStateException("MCP_NATIVE_POOL_UNAVAILABLE");return pool.asText();
    }
    void reserve(Path directory,String nonce,String pool)throws Exception {
        try{
            var result=command("reserve",directory,nonce,pool);
            if(!result.path("reserved").isBoolean()||!result.path("reserved").asBoolean(false)||!pool.equals(result.path("poolId").asText())||!nonce.equals(result.path("executionNonce").asText()))throw new IllegalStateException("MCP_NATIVE_RESERVATION_FAILED");
        }catch(Exception error){try{command("abandon",directory,nonce,pool);}catch(Exception ignored){/* Keep the MySQL reservation when pre-launch sealing is unverified. */}throw error;}
    }
    List<String> launchArguments(Path directory,String nonce,String pool)throws Exception {
        identity(nonce,pool);return List.of("-I",helper().toString(),"run","--directory",directory.toString(),"--execution",nonce,"--pool",pool);
    }
    Map<String,Object> stop(Path directory,String nonce,String pool){
        try{
            var result=command("stop",directory,nonce,pool);int count=directory.getNameCount();long owner=Long.parseLong(directory.getName(count-5).toString());
            if(!pool.equals(result.path("poolId").asText())||!result.path("owner").isIntegralNumber()||owner!=result.path("owner").asLong(-1)||!directory.getFileName().toString().equals(result.path("installation").asText())||!nonce.equals(result.path("executionNonce").asText())||!result.path("exitVerified").isBoolean()||!result.path("cleanupConfirmed").isBoolean())throw new IllegalStateException("MCP_NATIVE_RECEIPT_INVALID");
            boolean exited=result.path("exitVerified").asBoolean(),cleaned=result.path("cleanupConfirmed").asBoolean();if(cleaned&&!exited)throw new IllegalStateException("MCP_NATIVE_RECEIPT_INVALID");
            return Map.of("executionNonce",nonce,"exitVerified",exited,"cleanupConfirmed",cleaned,"state",cleaned?"REMOVED":exited?"EXITED":"NEEDS_REVIEW","transport","STDIO");
        }catch(Exception error){if(error instanceof InterruptedException)Thread.currentThread().interrupt();return Map.of("executionNonce",nonce,"exitVerified",false,"cleanupConfirmed",false,"state","NEEDS_REVIEW","transport","STDIO");}
    }
    private com.fasterxml.jackson.databind.JsonNode command(String action,Path directory,String nonce,String pool)throws Exception {
        FetchMcpRuntime.secure(directory);var args=new ArrayList<String>(List.of(properties.getPython(),"-I",helper().toString(),action,"--directory",directory.toString()));
        if(nonce!=null){identity(nonce,pool);args.addAll(List.of("--execution",nonce,"--pool",pool));}
        var builder=new ProcessBuilder(args);builder.environment().clear();
        for(String key:List.of("PATH","Path","SYSTEMROOT","SystemRoot","WINDIR","COMSPEC","TEMP","TMP"))if(System.getenv(key)!=null)builder.environment().put(key,System.getenv(key));
        builder.environment().put("PYTHONDONTWRITEBYTECODE","1");builder.redirectError(ProcessBuilder.Redirect.DISCARD);
        var process=builder.start();try{
            if(!process.waitFor(10,TimeUnit.SECONDS)){process.destroyForcibly();process.waitFor(2,TimeUnit.SECONDS);throw new IllegalStateException("MCP_NATIVE_CONTROL_TIMEOUT");}
            byte[] bytes=process.getInputStream().readNBytes(8193);
            if(process.exitValue()!=0||bytes.length>8192)throw new IllegalStateException("MCP_NATIVE_CONTROL_UNAVAILABLE");return json.readTree(bytes);
        }catch(InterruptedException error){process.destroyForcibly();Thread.currentThread().interrupt();throw error;}
        finally{process.getInputStream().close();process.getErrorStream().close();process.getOutputStream().close();}
    }
    private static void identity(String nonce,String pool){if(nonce==null||!UUID.fromString(nonce).toString().equals(nonce)||pool==null||!pool.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("MCP_NATIVE_IDENTITY_INVALID");}
}
