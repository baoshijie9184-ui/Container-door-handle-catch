package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentscope.core.message.ToolResultBlock;
import io.agentscope.core.tool.*;
import io.agentscope.core.tool.mcp.*;
import reactor.core.publisher.Mono;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** 安装和协议进程都只启动固定程序；不接受用户命令、参数或可执行文件路径。 */
public class FetchMcpRuntime {
    public static final String VERSION="2026.10.10", SHA="d722c48bdc1de3e2a81727853bc490cf55c6c935e2038cdcad3c111b1d85db77", TOOL="mcp__fetch__fetch";
    public interface Session extends AutoCloseable {Mono<ToolResultBlock> call(Map<String,Object> args);void close();}
    private final LocalMcpProperties properties;private final ObjectMapper json;
    public FetchMcpRuntime(LocalMcpProperties properties,ObjectMapper json){this.properties=properties;this.json=json;}
    public Map<String,Object> install(Path directory)throws Exception {
        secure(directory);Files.createDirectories(directory);secure(directory);
        Path temp=directory.resolve("tmp"),home=directory.resolve("home");Files.createDirectories(temp);Files.createDirectories(home);
        var builder=new ProcessBuilder(properties.getPython(),"-I",properties.getInstaller().replace("${user.dir}",System.getProperty("user.dir")),"--directory",directory.toString());
        builder.directory(directory.toFile());builder.environment().clear();builder.environment().putAll(environment(directory));
        builder.redirectErrorStream(true).redirectOutput(directory.resolve("install.log").toFile());
        var process=builder.start();try{if(!process.waitFor(600,TimeUnit.SECONDS)){kill(process);throw new IllegalStateException("INSTALL_TIMEOUT");}if(process.exitValue()!=0)throw new IllegalStateException("INSTALL_FAILED");}
        catch(InterruptedException e){kill(process);Thread.currentThread().interrupt();throw e;}
        var manifest=json.readValue(Files.readString(directory.resolve("manifest.json")),new TypeReference<LinkedHashMap<String,Object>>(){});
        validate(directory,manifest);try(var session=open(directory,manifest)){/* 实际 MCP 握手和 fetch 工具发现已由 open 完成。 */}
        return manifest;
    }
    public Session open(Path directory,Map<String,Object> manifest)throws Exception {
        validate(directory,manifest);var client=McpClientBuilder.create("fetch").stdioTransport(safeFile(directory,(String)manifest.get("python")).toString(),List.of("-I","-m","mcp_server_fetch"),environment(directory))
                .timeout(Duration.ofSeconds(25)).initializationTimeout(Duration.ofSeconds(12)).buildAsync().block(Duration.ofSeconds(15));
        if(client==null)throw new IllegalStateException("MCP_CONNECT_FAILED");
        try{var toolkit=new Toolkit();toolkit.registration().mcpClient(client).mcpToolNamePrefix("mcp__fetch__").enableTools(List.of("fetch")).propagateMeta(false).apply();
            if(!toolkit.getToolNames().equals(Set.of(TOOL)))throw new IllegalStateException("MCP_TOOL_MISMATCH");
            AgentTool nativeTool=toolkit.getTool(TOOL);
            return new Session(){public Mono<ToolResultBlock> call(Map<String,Object> args){return nativeTool.callAsync(ToolCallParam.builder().input(args).build());}public void close(){toolkit.closeMcpClients();}};
        }catch(Exception e){client.close();throw e;}
    }
    public void validate(Path directory,Map<String,Object> manifest)throws Exception {
        secure(directory);
        if(!VERSION.equals(manifest.get("version"))||!SHA.equals(manifest.get("packageSha256"))||!"fetch".equals(manifest.get("serverKey"))||!"STDIO".equals(manifest.get("transport"))||!List.of("-I","-m","mcp_server_fetch").equals(manifest.get("args")))throw new IllegalStateException("MCP_MANIFEST_INVALID");
        if(!(manifest.get("protectedFiles") instanceof List<?> files)||files.isEmpty()||files.size()>500)throw new IllegalStateException("MCP_MANIFEST_INVALID");
        for(Object item:files){var entry=(Map<?,?>)item;var file=safeFile(directory,(String)entry.get("path"));if(!sha(Files.readAllBytes(file)).equals(entry.get("sha256")))throw new IllegalStateException("MCP_FILES_CHANGED");}
    }
    public static Path safeFile(Path directory,String relative)throws Exception {if(relative==null||relative.contains("\\")||relative.contains(":")||relative.startsWith("/")||Arrays.asList(relative.split("/")).contains(".."))throw new IllegalStateException("MCP_PATH_INVALID");var result=directory.resolve(relative).normalize();if(!result.startsWith(directory))throw new IllegalStateException("MCP_PATH_INVALID");secure(result);return result;}
    public static void secure(Path value)throws Exception {var absolute=value.toAbsolutePath().normalize();for(Path path=absolute;path!=null;path=path.getParent())if(Files.exists(path,LinkOption.NOFOLLOW_LINKS)&&(Files.isSymbolicLink(path)||!path.toRealPath().equals(path)))throw new IllegalStateException("MCP_PATH_REDIRECTED");}
    public static String sha(byte[] bytes){try{return HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes));}catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException("SHA-256 unavailable",error);}}
    private Map<String,String> environment(Path directory){
        var env=new HashMap<String,String>();System.getenv().forEach((key,value)->env.put(key,"")); // SDK Stdio transport 默认继承进程环境，显式清掉非白名单值。
        for(String key:List.of("PATH","Path","SYSTEMROOT","SystemRoot","WINDIR","COMSPEC","HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY","SSL_CERT_FILE"))if(System.getenv(key)!=null)env.put(key,System.getenv(key));
        env.put("PYTHONIOENCODING","utf-8");env.put("PYTHONUNBUFFERED","1");env.put("PYTHONNOUSERSITE","1");env.put("TEMP",directory.resolve("tmp").toString());env.put("TMP",directory.resolve("tmp").toString());env.put("TMPDIR",directory.resolve("tmp").toString());env.put("HOME",directory.resolve("home").toString());env.put("USERPROFILE",directory.resolve("home").toString());return env;
    }
    private void kill(Process process){process.descendants().forEach(p->{if(p.isAlive())p.destroyForcibly();});process.destroyForcibly();}
}
