package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.contracts.agent.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import java.util.*;

@Service
@ConditionalOnProperty(prefix="agentscope.workbench",name="enabled",havingValue="true")
public class WorkspaceDetectionImagesBridge implements WorkspaceDetectionImagesApi {
    private final AgentWorkspaceService workspace;
    @org.springframework.beans.factory.annotation.Autowired private org.springframework.beans.factory.ObjectProvider<AgentBusinessFilesApi> business;
    @org.springframework.beans.factory.annotation.Value("${detection.creation.business-images-enabled:false}") private boolean businessEnabled;
    @org.springframework.beans.factory.annotation.Value("${detection.max-image-bytes:10485760}") private long maxImageBytes=10485760;
    public WorkspaceDetectionImagesBridge(AgentWorkspaceService workspace){this.workspace=workspace;}
    @Override public List<Image> describe(AgentActor actor,String session,List<String> ids){
        workspace.assertOwned(actor,session);
        if(ids==null||ids.isEmpty()||ids.size()>200||new HashSet<>(ids).size()!=ids.size())throw new IllegalArgumentException("请提供不重复的会话图片编号，最多 200 张");
        var result=new ArrayList<Image>();
        for(String id:ids){
            var file=privateFile(actor,session,id);
            // Detection currently supports JPEG/PNG/BMP; the workspace additionally accepts WebP, which is not silently converted.
            if(!Set.of("image/jpeg","image/png").contains(file.contentType()))throw new IllegalArgumentException("检测仅接受当前工作区的 JPEG/PNG 图片，WebP 或文档不能直接提交检测");
            byte[] data=workspace.bytes(actor,session,id);
            WorkspaceFileContent.validate(file.name(),file.contentType(),data);
            result.add(new Image(file.id(),file.name(),file.contentType(),file.bytes(),file.sha256(),
                    "/api/agent/conversations/"+session+"/files/"+file.id()+"/image"));
        }
        return List.copyOf(result);
    }
    @Override public byte[] read(AgentActor actor,String session,Image expected){
        if(expected.origin()!=null){assertUnchanged(actor,session,List.of(expected));var source=business.getObject().readOriginal(actor,expected.origin().taskId(),expected.origin().fileId(),maxImageBytes);byte[] bytes=source.content();WorkspaceFileContent.validate(source.name(),source.contentType(),bytes);if(!digest(bytes).equals(expected.sha256())||bytes.length!=expected.bytes()||!source.name().equals(expected.name())||!source.contentType().equals(expected.contentType())||!source.resourceVersion().equals(expected.origin().resourceVersion()))throw new IllegalStateException("业务原图内容已变化");return bytes;}
        var actual=describe(actor,session,List.of(expected.fileId())).get(0);
        if(!actual.equals(expected))throw new IllegalStateException("会话图片或授权已变化");
        return workspace.bytes(actor,session,expected.fileId());
    }
    @Override public List<Image> describeBusiness(AgentActor actor,String session,List<BusinessReference> references){
        if(!businessEnabled||business==null||business.getIfAvailable()==null)throw new IllegalStateException("业务原图创建尚未启用");workspace.assertOwned(actor,session);
        if(references==null||references.size()>200||new HashSet<>(references).size()!=references.size())throw new IllegalArgumentException("业务原图编号不能重复且最多 200 张");
        var result=new ArrayList<Image>();for(var reference:references){
            if(reference==null||reference.fileId()==null||!reference.fileId().matches("[a-f0-9-]{36}"))throw new IllegalArgumentException("业务原图编号无效");
            workspace.requireBusinessReference(actor,session,"DETECTION",reference.taskId());var file=business.getObject().readOriginal(actor,reference.taskId(),reference.fileId(),maxImageBytes);
            WorkspaceFileContent.validate(file.name(),file.contentType(),file.content());
            String identity=UUID.nameUUIDFromBytes(("DETECTION:"+file.taskId()+":"+reference.fileId()).getBytes(java.nio.charset.StandardCharsets.UTF_8)).toString();
            result.add(new Image(identity,file.name(),file.contentType(),file.content().length,digest(file.content()),"/api/agent/business-files/DETECTION/"+file.taskId()+"/"+reference.fileId(),new Origin(file.taskId(),reference.fileId(),file.resourceVersion())));
        }return List.copyOf(result);
    }
    @Override public void assertUnchanged(AgentActor actor,String session,List<Image> expected){
        workspace.assertOwned(actor,session);if(expected==null||expected.isEmpty()||expected.size()>200)throw new IllegalArgumentException("图片快照无效");
        for(var image:expected){if(image.origin()==null){var file=privateFile(actor,session,image.fileId());if(!file.name().equals(image.name())||!file.contentType().equals(image.contentType())||file.bytes()!=image.bytes()||!file.sha256().equals(image.sha256()))throw new DetectionExecutionApi.ResourceChanged();}
            else{if(!businessEnabled||business==null||business.getIfAvailable()==null)throw new IllegalStateException("业务原图创建尚未启用");workspace.requireBusinessReference(actor,session,"DETECTION",image.origin().taskId());business.getObject().assertOriginal(actor,image.origin().taskId(),image.origin().fileId(),image.origin().resourceVersion());}
        }
    }
    private WorkbenchSessionApi.File privateFile(AgentActor actor,String session,String id){try{return workspace.requireFile(actor,session,id);}catch(org.springframework.web.server.ResponseStatusException error){if(error.getStatusCode().value()==404||error.getStatusCode().value()==403)throw new SecurityException("会话图片已移除或无权限");throw error;}}
    private static String digest(byte[] bytes){try{return HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes));}catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}}
}
