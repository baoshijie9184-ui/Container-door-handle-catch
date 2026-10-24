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
    public interface Session extends AutoCloseable {
        Mono<ToolResultBlock> call(Map<String,Object> args);void close();
        default Map<String,Object> exitEvidence(){return Map.of("state","UNAVAILABLE","exitVerified",false,"cleanupConfirmed",false);}
        default boolean requiresExitEvidence(){return false;}
    }
    public static final class ExitUnverified extends IllegalStateException{ExitUnverified(){super("MCP_EXIT_UNVERIFIED");}}
    private final LocalMcpProperties properties;private final ObjectMapper json;
    private final FetchImageRegistry imageRegistry;
    private final java.util.concurrent.ConcurrentHashMap<String,McpClientWrapper> deferredNativeCloses=new java.util.concurrent.ConcurrentHashMap<>();
    public FetchMcpRuntime(LocalMcpProperties properties,ObjectMapper json){this(properties,json,null);}
    public FetchMcpRuntime(LocalMcpProperties properties,ObjectMapper json,FetchImageRegistry imageRegistry){if(!Set.of("STDIO","GATEWAY").contains(properties.getTransport()))throw new IllegalArgumentException("MCP_TRANSPORT_INVALID");this.properties=properties;this.json=json;this.imageRegistry=imageRegistry;}
    public FetchImageRegistry imageRegistry(){return imageRegistry;}
    public String targetImage(){return properties.isGateway()?properties.getGatewayImage():null;}
    public void requireImageUsable(String image){if(imageRegistry!=null)imageRegistry.usable(image);}
    public Map<String,Object> install(Path directory)throws Exception {
        requireWritesAllowed();
        requireImageUsable(targetImage());
        if(Thread.currentThread().isInterrupted())throw new InterruptedException("INSTALL_INTERRUPTED");
        if(properties.isGateway()){var manifest=new McpGatewayClient(properties,json).install(directory);validate(directory,manifest);try(var session=open(directory,manifest)){}return manifest;}
        secure(directory);Files.createDirectories(directory);secure(directory);
        Path temp=directory.resolve("tmp"),home=directory.resolve("home");Files.createDirectories(temp);Files.createDirectories(home);
        secure(temp);secure(home);
        if(nativeInstallSupervised()){
            new NativeFetchInstallClient(properties,json).install(directory,environment(directory));
            var manifest=json.readValue(Files.readString(directory.resolve("manifest.json")),new TypeReference<LinkedHashMap<String,Object>>(){});
            validate(directory,manifest);return manifest; // The service records the SDK handshake in the execution ledger.
        }
        var builder=new ProcessBuilder(properties.getPython(),"-I",properties.getInstaller().replace("${user.dir}",System.getProperty("user.dir")),"--directory",directory.toString());
        builder.directory(directory.toFile());builder.environment().clear();builder.environment().putAll(environment(directory));
        builder.redirectErrorStream(true).redirectOutput(directory.resolve("install.log").toFile());
        if(Thread.currentThread().isInterrupted())throw new InterruptedException("INSTALL_INTERRUPTED");
        var process=builder.start();try{if(!process.waitFor(600,TimeUnit.SECONDS)){kill(process);throw new IllegalStateException("INSTALL_TIMEOUT");}if(process.exitValue()!=0)throw new IllegalStateException("INSTALL_FAILED");}
        catch(InterruptedException e){kill(process);Thread.currentThread().interrupt();throw e;}
        var manifest=json.readValue(Files.readString(directory.resolve("manifest.json")),new TypeReference<LinkedHashMap<String,Object>>(){});
        validate(directory,manifest);try(var session=open(directory,manifest)){/* 实际 MCP 握手和 fetch 工具发现已由 open 完成。 */}
        return manifest;
    }
    public Session open(Path directory,Map<String,Object> manifest)throws Exception {
        return openTracked(directory,manifest,UUID.randomUUID().toString(),null);
    }
    public String executionPool(Path directory)throws Exception {
        if(!properties.isGateway()){
            if(!properties.isNativeProcessEnabled())throw new IllegalStateException("MCP_DURABLE_STDIO_UNAVAILABLE");
            return new NativeFetchProcessClient(properties,json).pool(directory);
        }
        return new McpGatewayClient(properties,json).executionPool(directory);
    }
    public Map<String,Object> stopExecution(Path directory,String nonce,String pool){
        if(!properties.isGateway()){
            var evidence=properties.isNativeProcessEnabled()?new NativeFetchProcessClient(properties,json).stop(directory,nonce,pool):Map.<String,Object>of("state","UNAVAILABLE","exitVerified",false,"cleanupConfirmed",false);
            if(Boolean.TRUE.equals(evidence.get("exitVerified"))){var client=deferredNativeCloses.get(nonce);if(client!=null)try{client.close();deferredNativeCloses.remove(nonce,client);}catch(RuntimeException error){throw new ExitUnverified();}}
            return evidence;
        }
        return new McpGatewayClient(properties,json).cancel(directory,nonce,pool).evidence();
    }
    public Map<String,Object> installationController(Path directory){
        if(nativeInstallSupervised())try{return Map.of("nativePool",new NativeFetchInstallClient(properties,json).reserve(directory));}
        catch(Exception error){if(error instanceof InterruptedException)Thread.currentThread().interrupt();throw new IllegalStateException("MCP_INSTALL_RESERVATION_UNAVAILABLE");}
        if(!properties.isGateway())return Map.of();
        try{return new McpGatewayClient(properties,json).installationController(directory,System.getenv("HOSTNAME"),null,null);}
        catch(Exception error){if(error instanceof InterruptedException)Thread.currentThread().interrupt();return Map.of();}
    }
    public boolean installationControllerStopped(Path directory,String id,String started,String pool){
        if(!properties.isGateway())return false;
        try{return Boolean.TRUE.equals(new McpGatewayClient(properties,json).installationController(directory,id,started,pool).get("stopped"));}
        catch(Exception error){if(error instanceof InterruptedException)Thread.currentThread().interrupt();return false;}
    }
    public Session openTracked(Path directory,Map<String,Object> manifest,String nonce,String pool)throws Exception {
        requireWritesAllowed();
        validate(directory,manifest);var gateway=properties.isGateway()?new McpGatewayClient(properties,json):null;
        var nativeProcess=!properties.isGateway()&&properties.isNativeProcessEnabled()?new NativeFetchProcessClient(properties,json):null;
        final String processPool=nativeProcess==null?pool:pool==null?nativeProcess.pool(directory):pool;
        if(nativeProcess!=null)nativeProcess.reserve(directory,nonce,processPool);
        var connection=gateway==null?null:gateway.open(directory,nonce,pool,(String)manifest.get("image"));
        var client=connection!=null?connection.client():McpClientBuilder.create("fetch").stdioTransport(safeFile(directory,(String)manifest.get("python")).toString(),nativeProcess==null?List.of("-I","-m","mcp_server_fetch"):nativeProcess.launchArguments(directory,nonce,processPool),environment(directory))
                .timeout(Duration.ofSeconds(25)).initializationTimeout(Duration.ofSeconds(12)).buildAsync().block(Duration.ofSeconds(15));
        if(client==null)throw new IllegalStateException("MCP_CONNECT_FAILED");
        try{var toolkit=new Toolkit();toolkit.registration().mcpClient(client).mcpToolNamePrefix("mcp__fetch__").enableTools(List.of("fetch")).propagateMeta(false).apply();
            if(!toolkit.getToolNames().equals(Set.of(TOOL)))throw new IllegalStateException("MCP_TOOL_MISMATCH");
            AgentTool nativeTool=toolkit.getTool(TOOL);
            return new Session(){
                private boolean clientClosed;private volatile McpGatewayClient.StopReceipt receipt;private volatile Map<String,Object> nativeReceipt;
                public Mono<ToolResultBlock> call(Map<String,Object> args){return nativeTool.callAsync(ToolCallParam.builder().input(args).build());}
                public boolean requiresExitEvidence(){return gateway!=null||nativeProcess!=null;}
                public Map<String,Object> exitEvidence(){return nativeReceipt!=null?nativeReceipt:receipt==null?Map.of("state",clientClosed?"UNAVAILABLE":"RUNNING","exitVerified",false,"cleanupConfirmed",false):receipt.evidence();}
                public synchronized void close(){
                    if(nativeProcess!=null){
                        nativeReceipt=nativeProcess.stop(directory,nonce,processPool);
                        if(!Boolean.TRUE.equals(nativeReceipt.get("exitVerified")))throw new ExitUnverified();
                        try{if(!clientClosed){toolkit.closeMcpClients();clientClosed=true;}}finally{nativeReceipt=nativeProcess.stop(directory,nonce,processPool);}
                    }else{
                        try{if(!clientClosed){clientClosed=true;toolkit.closeMcpClients();}}
                        finally{if(gateway!=null&&(receipt==null||!receipt.cleanupConfirmed()))receipt=gateway.cancel(connection.credential());}
                    }
                    if(requiresExitEvidence()&&!Boolean.TRUE.equals(exitEvidence().get("exitVerified")))throw new ExitUnverified();
                }
            };
        }catch(Exception e){
            if(nativeProcess!=null){var evidence=nativeProcess.stop(directory,nonce,processPool);if(Boolean.TRUE.equals(evidence.get("exitVerified")))client.close();else deferredNativeCloses.put(nonce,client);}
            else try{client.close();}finally{if(gateway!=null)gateway.cancel(connection.credential());}
            throw e;
        }
    }
    public void validate(Path directory,Map<String,Object> manifest)throws Exception {
        if(properties.isGateway()){requireImageUsable((String)manifest.get("image"));new McpGatewayClient(properties,json).validate(directory,manifest);return;}
        secure(directory);
        if(!VERSION.equals(manifest.get("version"))||!SHA.equals(manifest.get("packageSha256"))||!"fetch".equals(manifest.get("serverKey"))||!"STDIO".equals(manifest.get("transport"))||!List.of("-I","-m","mcp_server_fetch").equals(manifest.get("args")))throw new IllegalStateException("MCP_MANIFEST_INVALID");
        if(!(manifest.get("protectedFiles") instanceof List<?> files)||files.isEmpty()||files.size()>500)throw new IllegalStateException("MCP_MANIFEST_INVALID");
        for(Object item:files){var entry=(Map<?,?>)item;var file=safeFile(directory,(String)entry.get("path"));if(!sha(Files.readAllBytes(file)).equals(entry.get("sha256")))throw new IllegalStateException("MCP_FILES_CHANGED");}
    }
    public String transport(){return properties.isGateway()?"STREAMABLE_HTTP":"STDIO";}
    public boolean writesAllowed(){return properties.isWritesEnabled();}
    public boolean sharedImageManagementEnabled(){return properties.isSharedImageCleanupEnabled();}
    public void requireWritesAllowed(){if(!writesAllowed())throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE,"MCP 新安装和新执行已暂停 仍可查询和核对原执行退出");}
    public boolean nativeInstallSupervised(){return !properties.isGateway()&&properties.isNativeInstallEnabled();}
    public long installationReservationBytes(){return nativeInstallSupervised()?512L*1024*1024:2L*1024*1024;}
    public boolean nativeInstallerStopped(Path directory,String pool){return nativeInstallSupervised()&&new NativeFetchInstallClient(properties,json).stopAndObserve(directory,pool);}
    public String installationIdentity(){
        var identity=new TreeMap<String,String>();identity.put("version",VERSION);identity.put("packageSha256",SHA);identity.put("transport",transport());
        if(properties.isGateway()){identity.put("gatewayUrl",properties.getGatewayUrl());identity.put("image",properties.getGatewayImage());}
        else{identity.put("python",properties.getPython());identity.put("installer",properties.getInstaller().replace("${user.dir}",System.getProperty("user.dir")));identity.put("processReceipts",Boolean.toString(properties.isNativeProcessEnabled()));if(properties.isNativeProcessEnabled())try{var helper=new NativeFetchProcessClient(properties,json).helper();identity.put("processHelper",helper.toString());identity.put("processHelperSha256",sha(Files.readAllBytes(helper)));}catch(Exception error){throw new IllegalStateException("INSTALL_RUNTIME_IDENTITY_INVALID");}}
        if(nativeInstallSupervised())try{
            var helper=new NativeFetchInstallClient(properties,json).helper();var installer=helper.resolveSibling("install-local-fetch-mcp.py");secure(installer);
            if(!installer.equals(Path.of(properties.getInstaller().replace("${user.dir}",System.getProperty("user.dir"))).toAbsolutePath().normalize())||!Files.isRegularFile(installer)||Files.size(installer)>65536)throw new IllegalStateException();
            identity.put("installerSupervisor",helper.toString());identity.put("installerSupervisorSha256",sha(Files.readAllBytes(helper)));identity.put("fixedInstallerSha256",sha(Files.readAllBytes(installer)));
        }catch(Exception error){throw new IllegalStateException("INSTALL_RUNTIME_IDENTITY_INVALID");}
        try{return sha(json.writeValueAsBytes(identity));}catch(Exception error){throw new IllegalStateException("INSTALL_RUNTIME_IDENTITY_INVALID");}
    }
    public boolean compatible(Map<String,Object> manifest){return new FetchReleasePolicy(properties).approved(manifest);}
    public boolean upgradeAvailable(Map<String,Object> manifest){return !new FetchReleasePolicy(properties).target(manifest);}
    public Map<String,Object> releaseCatalog(){return new FetchReleasePolicy(properties).view();}
    public boolean requiresMigration(Map<String,Object> manifest){return !compatible(manifest);}
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
