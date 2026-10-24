package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** Fixed installer supervision only. Control commands return private metadata, never pip output. */
final class NativeFetchInstallClient {
    private final LocalMcpProperties properties;private final ObjectMapper json;
    NativeFetchInstallClient(LocalMcpProperties properties,ObjectMapper json){this.properties=properties;this.json=json;}
    Path helper()throws Exception {
        var value=Path.of(properties.getNativeInstallHelper().replace("${user.dir}",System.getProperty("user.dir"))).toAbsolutePath().normalize();
        FetchMcpRuntime.secure(value);if(!Files.isRegularFile(value)||Files.size(value)>65536)throw new IllegalStateException("MCP_INSTALL_HELPER_INVALID");return value;
    }
    String reserve(Path directory)throws Exception {
        var value=control("reserve",directory,null);String pool=value.path("poolId").asText();
        if(!pool.matches("[a-f0-9]{32}"))throw new IllegalStateException("MCP_INSTALL_POOL_UNAVAILABLE");validate(directory,pool,value);return pool;
    }
    boolean stopAndObserve(Path directory,String pool){
        boolean interrupted=Thread.interrupted();
        try{return control("stop",directory,pool).path("writerStopped").asBoolean(false);}
        catch(Exception error){if(error instanceof InterruptedException)interrupted=true;return false;}
        finally{if(interrupted)Thread.currentThread().interrupt();}
    }
    void install(Path directory,Map<String,String> environment)throws Exception {
        // Reservation is created before the MySQL worker claim, never implicitly replayed here.
        var initial=control("status",directory,null);String pool=initial.path("poolId").asText();validate(directory,pool,initial);
        if(!"RESERVED".equals(initial.path("state").asText()))throw new IllegalStateException("MCP_INSTALL_RESERVATION_INVALID");
        var args=arguments("run",directory,pool);var builder=new ProcessBuilder(args).directory(directory.toFile());
        builder.environment().clear();builder.environment().putAll(environment);
        builder.redirectOutput(ProcessBuilder.Redirect.DISCARD).redirectError(ProcessBuilder.Redirect.DISCARD);
        Process supervisor=null;
        try{
            if(Thread.currentThread().isInterrupted())throw new InterruptedException();
            supervisor=builder.start();
            if(!supervisor.waitFor(605,TimeUnit.SECONDS))throw new IllegalStateException("INSTALL_TIMEOUT");
            var receipt=control("status",directory,pool);
            if(supervisor.exitValue()!=0||!receipt.path("writerStopped").asBoolean(false)||!"SUCCEEDED".equals(receipt.path("state").asText())||!receipt.path("exitCode").isIntegralNumber()||receipt.path("exitCode").asInt(-1)!=0)throw new IllegalStateException("INSTALL_FAILED");
        }catch(Exception error){
            // Do not kill the subreaper: descendants must retain their observable parent.
            stopAndObserve(directory,pool);if(error instanceof InterruptedException)Thread.currentThread().interrupt();throw error;
        }finally{if(supervisor!=null){supervisor.getInputStream().close();supervisor.getErrorStream().close();supervisor.getOutputStream().close();}}
    }
    private List<String> arguments(String action,Path directory,String pool)throws Exception {
        FetchMcpRuntime.secure(directory);var args=new ArrayList<String>(List.of(properties.getPython(),"-I","-B",helper().toString(),action,"--directory",directory.toString()));
        if(pool!=null){if(!pool.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("MCP_INSTALL_POOL_INVALID");args.addAll(List.of("--pool",pool));}return args;
    }
    private JsonNode control(String action,Path directory,String pool)throws Exception {
        var builder=new ProcessBuilder(arguments(action,directory,pool));builder.environment().clear();
        for(String key:List.of("PATH","Path","SYSTEMROOT","SystemRoot","WINDIR","COMSPEC"))if(System.getenv(key)!=null)builder.environment().put(key,System.getenv(key));
        builder.redirectError(ProcessBuilder.Redirect.DISCARD);var process=builder.start();
        try{
            if(!process.waitFor(10,TimeUnit.SECONDS)){process.destroyForcibly();throw new IllegalStateException("MCP_INSTALL_CONTROL_TIMEOUT");}
            byte[] bytes=process.getInputStream().readNBytes(8193);
            if(process.exitValue()!=0||bytes.length>8192)throw new IllegalStateException("MCP_INSTALL_CONTROL_UNAVAILABLE");
            var result=json.readTree(bytes);validate(directory,pool,result);return result;
        }catch(InterruptedException error){process.destroyForcibly();Thread.currentThread().interrupt();throw error;}
        finally{process.getInputStream().close();process.getErrorStream().close();process.getOutputStream().close();}
    }
    private static void validate(Path directory,String pool,JsonNode result){
        int count=directory.getNameCount();long owner=Long.parseLong(directory.getName(count-5).toString());
        if(result==null||!result.path("poolId").asText().matches("[a-f0-9]{32}")||pool!=null&&!pool.equals(result.path("poolId").asText())||!result.path("owner").isIntegralNumber()||owner!=result.path("owner").asLong(-1)||!directory.getFileName().toString().equals(result.path("installation").asText())||!result.path("writerStopped").isBoolean())throw new IllegalStateException("MCP_INSTALL_RECEIPT_INVALID");
        if(result.path("writerStopped").asBoolean()&&!Set.of("SUCCEEDED","FAILED","CANCELLED","SEALED").contains(result.path("state").asText()))throw new IllegalStateException("MCP_INSTALL_RECEIPT_INVALID");
    }
}
