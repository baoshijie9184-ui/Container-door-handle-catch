package com.ruanzhu.doorhandle.module.detection.api;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import org.springframework.stereotype.Service;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;

@Service
public class AgentBusinessFilesApiImpl implements AgentBusinessFilesApi {
    private final DetectionTaskMapper tasks;private final DetectionTaskAccessPolicy access;private final QualityReportAgentApi reports;private final OssStorageService oss;
    public AgentBusinessFilesApiImpl(DetectionTaskMapper tasks,DetectionTaskAccessPolicy access,QualityReportAgentApi reports,OssStorageService oss){this.tasks=tasks;this.access=access;this.reports=reports;this.oss=oss;}
    private DetectionTask task(AgentActor actor,String id){var query=new QueryWrapper<DetectionTask>();access.applyScope(query,actor);var value=tasks.selectOne(query.eq("task_id",id));if(value==null)throw new SecurityException("任务不可访问");return value;}
    private String path(String kind,String resource,String file){return "/api/agent/business-files/"+kind+"/"+resource+"/"+file;}
    private static String id(String key){return UUID.nameUUIDFromBytes(key.getBytes(StandardCharsets.UTF_8)).toString();}
    private List<String> originals(DetectionTask task){try{List<String> keys=new ObjectMapper().readValue(Objects.toString(task.getOriginalImageKeysJson(),"[]"),new TypeReference<List<String>>(){});if(keys==null||keys.size()>5000||keys.stream().anyMatch(key->key==null||key.isBlank()||key.length()>1024||key.chars().anyMatch(Character::isISOControl)))throw new IllegalArgumentException();return keys;}catch(Exception invalid){throw new IllegalStateException("任务原图目录不可读取");}}
    private String originalKey(DetectionTask task,String file){if(file==null||!file.matches("[a-f0-9-]{36}"))throw new IllegalArgumentException("原图编号无效");return originals(task).stream().filter(key->id(key).equals(file)).findFirst().orElseThrow(()->new SecurityException("原图不存在或无权访问"));}
    private String originalVersion(DetectionTask task){try{String value=task.getTaskId()+"\n"+oss.getBucketName()+"\n"+new ObjectMapper().writeValueAsString(originals(task));return HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException|com.fasterxml.jackson.core.JsonProcessingException error){throw new IllegalStateException("原图目录摘要不可读取");}}
    @Override public OriginalImage readOriginal(AgentActor actor,String resource,String file,long maxBytes){
        validate("DETECTION",resource);var source=task(actor,resource);String key=originalKey(source,file),version=originalVersion(source),name=key.substring(key.lastIndexOf('/')+1),lower=name.toLowerCase(Locale.ROOT);
        if(!(lower.endsWith(".jpg")||lower.endsWith(".jpeg")||lower.endsWith(".png"))||name.length()>200)throw new IllegalArgumentException("仅支持 JPEG/PNG 业务原图");
        byte[] bytes=oss.readObject(key,maxBytes);var current=task(actor,resource);
        if(!version.equals(originalVersion(current))||!key.equals(originalKey(current,file)))throw new DetectionExecutionApi.ResourceChanged();
        return new OriginalImage(source.getTaskId(),name,lower.endsWith(".png")?"image/png":"image/jpeg",bytes,version);
    }
    @Override public void assertOriginal(AgentActor actor,String resource,String file,String expectedVersion){validate("DETECTION",resource);var source=task(actor,resource);originalKey(source,file);if(expectedVersion==null||!expectedVersion.equals(originalVersion(source)))throw new DetectionExecutionApi.ResourceChanged();}
    private Map<String,String> imageKeys(DetectionTask task){var result=new LinkedHashMap<String,String>();for(String json:List.of(Objects.toString(task.getOriginalImageKeysJson(),"[]"),Objects.toString(task.getPreviewImageKeysJson(),"[]")))try{List<String> keys=new ObjectMapper().readValue(json,new TypeReference<List<String>>(){});for(String key:keys.stream().limit(20).toList())if(key!=null&&!key.isBlank())result.put(id(key),key);}catch(Exception error){throw new IllegalStateException("任务图片目录不可读取");}return result;}
    private void validate(String kind,String resource){if(!Set.of("DETECTION","REPORT").contains(kind)||resource==null||!resource.matches("[A-Za-z0-9_-]{1,128}"))throw new IllegalArgumentException("业务文件引用无效");}
    @Override public List<Resource> originalImages(AgentActor actor,String resource){
        validate("DETECTION",resource);var task=task(actor,resource);
        try{
            List<String> keys=new ObjectMapper().readValue(Objects.toString(task.getOriginalImageKeysJson(),"[]"),new TypeReference<List<String>>(){});
            return keys.stream().filter(Objects::nonNull).filter(key->!key.isBlank()).limit(20).map(key->{String name=key.substring(key.lastIndexOf('/')+1);return new Resource("DETECTION",resource,id(key),name,name.toLowerCase(Locale.ROOT).endsWith(".png")?"image/png":"image/jpeg",path("DETECTION",resource,id(key)));}).toList();
        }catch(Exception invalid){throw new IllegalStateException("任务原图目录不可读取");}
    }
    @Override public List<Resource> list(AgentActor actor,String kind,String resource){validate(kind,resource);if(kind.equals("REPORT")){var report=reports.get(actor,resource);return List.of(new Resource(kind,resource,"report",report.report().title()+".md","text/plain; charset=utf-8",path(kind,resource,"report")));}
        return imageKeys(task(actor,resource)).entrySet().stream().map(entry->{String key=entry.getValue(),name=key.substring(key.lastIndexOf('/')+1);String mime=name.toLowerCase(Locale.ROOT).endsWith(".png")?"image/png":name.toLowerCase(Locale.ROOT).endsWith(".webp")?"image/webp":"image/jpeg";return new Resource(kind,resource,entry.getKey(),name,mime,path(kind,resource,entry.getKey()));}).toList();
    }
    @Override public Delivery read(AgentActor actor,String kind,String resource,String file){validate(kind,resource);if(kind.equals("REPORT")){if(!file.equals("report"))throw new SecurityException("报告文件不可访问");var report=reports.get(actor,resource);return new Delivery(null,"# "+report.report().title()+"\n\n"+Objects.toString(report.narrative(),""),"text/plain; charset=utf-8");}
        var source=task(actor,resource);String key=imageKeys(source).get(file);if(key==null)key=originalKey(source,file);return new Delivery(oss.generateGetUrl(key,Duration.ofMinutes(2)).toString(),null,"image/jpeg");
    }
}
