package com.ruanzhu.doorhandle.module.ai.evolution;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Downloads remain outside SDK workspace skills discovery. All runtime reads recheck provenance and files. */
@Component
@ConditionalOnProperty(prefix="agentscope.evolution.links",name="enabled",havingValue="true")
public class SkillLinkStorage {
    private final JdbcTemplate jdbc; private final ObjectMapper json; private final Path root;
    public SkillLinkStorage(JdbcTemplate jdbc,ObjectMapper json,
            @Value("${agentscope.ai.workspace:${user.dir}/.agentscope/workspace}") String workspace){
        this.jdbc=jdbc;this.json=json;this.root=Path.of(workspace).toAbsolutePath().normalize();
    }
    public Path directory(long owner,String id){
        if(owner<1||id==null||!id.matches("download-[a-f0-9-]{36}"))throw fail("下载身份不合法");
        Path path=root.resolve("users").resolve(Long.toString(owner)).resolve("skill-downloads").resolve(id);
        checkParents(path);return path;
    }
    private void checkParents(Path path){
        try{
            Path boundary=Files.exists(root)?root.toRealPath():root;
            for(Path parent=path;parent!=null&&parent.startsWith(root);parent=parent.getParent()){
                if(Files.isSymbolicLink(parent)||Files.exists(parent)&&!parent.toRealPath().equals(boundary.resolve(root.relativize(parent)).normalize()))throw fail("技能存储路径不合法");
            }
        }catch(java.io.IOException error){throw fail("技能存储路径无法核对");}
    }
    public record Usage(long bytes,int files) {}
    public Usage usage(long owner){
        if(owner<1)throw fail("存储身份不合法");Path directory=root.resolve("users").resolve(Long.toString(owner)).resolve("skill-downloads");
        checkParents(directory);return scan(directory).usage();
    }
    private record Scan(List<Path> paths,Usage usage) {}
    private Scan scan(Path directory){
        if(!Files.exists(directory,LinkOption.NOFOLLOW_LINKS))return new Scan(List.of(),new Usage(0,0));
        checkParents(directory);
        try(var stream=Files.walk(directory)){
            var paths=stream.limit(20001).toList();if(paths.size()>20000)throw fail("文件数量过多 请由运维核对存储");
            long bytes=0;int files=0;Path boundary=directory.toRealPath();
            for(Path path:paths){if(Files.isSymbolicLink(path)||!path.toRealPath().equals(boundary.resolve(directory.relativize(path)).normalize()))throw fail("存储内存在不合法链接");
                if(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)){bytes=Math.addExact(bytes,Files.size(path));files++;}}
            return new Scan(paths,new Usage(bytes,files));
        }catch(ResponseStatusException error){throw error;}catch(Exception error){throw fail("存储文件暂不能核对");}
    }
    /** Caller must first lock the download, reject all version references and record cleanup intent. */
    public Usage purge(long owner,String id){
        Path directory=directory(owner,id);var scan=scan(directory);
        // Verify the resolved absolute target and every entry before starting irreversible deletes.
        if(!directory.toAbsolutePath().normalize().startsWith(root.resolve("users").resolve(Long.toString(owner)).resolve("skill-downloads")))throw fail("清理目标不合法");
        try{for(Path path:scan.paths().stream().sorted(Comparator.reverseOrder()).toList()){checkParents(path);Files.deleteIfExists(path);}return scan.usage();}
        catch(Exception error){throw fail("文件清理尚未全部完成 请重新核对存储");}
    }
    public Map<String,Object> inspect(long owner,String id){
        try{
            Path path=directory(owner,id), manifest=path.resolve("manifest.json");
            if(!Files.isRegularFile(manifest,LinkOption.NOFOLLOW_LINKS)||Files.size(manifest)>512000)throw fail("下载清单不合法");
            Map<String,Object> result=json.readValue(Files.readString(manifest),new TypeReference<LinkedHashMap<String,Object>>(){});
            validate(path,result);return result;
        }catch(ResponseStatusException error){throw error;}catch(Exception error){throw fail("技能包文件完整性校验失败");}
    }
    @SuppressWarnings("unchecked")
    private void validate(Path directory,Map<String,Object> manifest)throws Exception{
        if(!"LINK".equals(manifest.get("sourceType"))||!Objects.toString(manifest.get("commit"),"").matches("[a-f0-9]{40}")
                ||!Boolean.TRUE.equals(manifest.get("provenanceVerified"))||!Boolean.FALSE.equals(manifest.get("scriptsExecutable"))
                ||!Boolean.FALSE.equals(manifest.get("resourcesReadable"))||!(manifest.get("licenses") instanceof Map<?,?> licenses)||licenses.isEmpty()
                ||!Set.of("Apache-2.0","MIT","BSD").contains(manifest.get("license")))throw fail("技能来源或许可不合法");
        Object value=manifest.get("files");if(!(value instanceof List<?> files)||files.isEmpty()||files.size()>96)throw fail("技能文件清单不合法");
        long total=0;var names=new HashSet<String>();
        for(Object item:files){
            if(!(item instanceof Map<?,?> file))throw fail("技能文件清单不合法");
            String relative=Objects.toString(file.get("path"),"");
            if(!relative.matches("[A-Za-z0-9_./-]{1,220}")||Arrays.stream(relative.split("/",-1)).anyMatch(p->p.isEmpty()||p.equals(".")||p.equals(".."))||!names.add(relative.toLowerCase(Locale.ROOT)))throw fail("技能文件路径不合法");
            Path path=directory.resolve(relative).normalize();checkParents(path);
            if(!path.startsWith(directory)||!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||Files.size(path)>1048576)throw fail("技能文件不合法");
            byte[] bytes=Files.readAllBytes(path);total+=bytes.length;
            if(total>4194304||!(file.get("bytes") instanceof Number size)||size.longValue()!=bytes.length||!bytesSha(bytes).equals(file.get("sha256")))throw fail("技能文件摘要校验失败");
        }
        if(!names.contains("skill.md"))throw fail("缺少技能正文");
        String raw=Files.readString(directory.resolve("SKILL.md")).replace("\r\n","\n");int end=raw.indexOf("\n---",4);
        if(end<0||!raw.substring(end+4).stripLeading().equals(manifest.get("instructions")))throw fail("技能正文与清单不一致");
    }
    public Map<String,Object> verified(long owner,String id){
        var rows=jdbc.queryForList("SELECT status,manifest_json,manifest_sha256 FROM agent_skill_download WHERE download_id=? AND owner_user_id=?",id,owner);
        if(rows.isEmpty()||!Set.of("DOWNLOADED","DRAFT_CREATED").contains(rows.get(0).get("status")))throw fail("技能下载尚未完成或无权限");
        var manifest=inspect(owner,id);
        if(!digest(manifest).equals(rows.get(0).get("manifest_sha256")))throw fail("技能下载清单已变化");
        return manifest;
    }
    public Map<String,Object> evidence(Map<String,Object> manifest){
        var evidence=new LinkedHashMap<>(manifest);evidence.remove("instructions");evidence.remove("description");
        evidence.put("manifestSha256",digest(manifest));evidence.put("tools",List.of());return evidence;
    }
    public String digest(Object value){try{return bytesSha(json.copy().enable(com.fasterxml.jackson.databind.SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).writeValueAsBytes(value));}catch(Exception error){throw fail("技能清单摘要失败");}}
    private static String bytesSha(byte[] value)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value));}
    private static ResponseStatusException fail(String message){return new ResponseStatusException(HttpStatus.CONFLICT,message);}
}
