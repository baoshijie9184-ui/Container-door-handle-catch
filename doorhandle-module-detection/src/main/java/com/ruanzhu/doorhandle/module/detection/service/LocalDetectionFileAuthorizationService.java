package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.contracts.files.LocalDetectionFilesApi;
import com.ruanzhu.doorhandle.contracts.files.BusinessFileGrant;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.common.LocalFileSafety;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import java.nio.file.*;
import java.io.IOException;

/** 本地历史检测文件必须关联可访问的任务，目录存在本身不能授予权限。 */
@Service
@RequiredArgsConstructor
public class LocalDetectionFileAuthorizationService implements LocalDetectionFilesApi {
    private final DetectionTaskMapper mapper;
    private final DetectionTaskAccessPolicy policy;
    private final BusinessUserDirectory users;
    @Value("${detection.upload-dir:${user.dir}/uploads/images}") private String images;
    @Value("${detection.annotated-dir:${user.dir}/uploads/annotated}") private String annotated;
    @Value("${detection.result-dir:${user.dir}/uploads/results}") private String results;

    @Override public BusinessFileGrant authorizeFile(Kind kind, Path path) {
        var actor=users.authenticated();
        var authentication=SecurityContextHolder.getContext().getAuthentication();
        var query=new LambdaQueryWrapper<DetectionTask>();
        policy.applyScope(query,authentication);
        query.isNotNull(DetectionTask::getSourceOssPrefix);
        BusinessFileGrant selected=null;
        for(var task:mapper.selectList(query)) {
            if(!policy.canAccess(task,authentication)) continue;
            Path root=allowedRoot(task,kind);
            if(root!=null && contains(kind,root,path)) {
                if(selected!=null) throw new AccessDeniedException("文件所属任务不唯一");
                String id=task.getTaskId();
                String relative=base(kind).relativize(path.toAbsolutePath().normalize()).toString();
                selected=new BusinessFileGrant(id,LocalFileSafety.reference(id,kind.name(),relative),null);
            }
        }
        if(selected==null) throw new AccessDeniedException("无权访问该资源");
        var current=users.authenticated();
        if(current.userId()!=actor.userId() || current.supervisor()!=actor.supervisor()) throw new AccessDeniedException("文件访问身份已变化");
        return selected;
    }

    private Path allowedRoot(DetectionTask task,Kind kind) {
        try {
            Path imageBase=Path.of(images).toAbsolutePath().normalize();
            Path source=Path.of(task.getSourceOssPrefix()).toAbsolutePath().normalize();
            if(!source.startsWith(imageBase) || source.equals(imageBase)) return null;
            if(kind==Kind.IMAGE) return source;
            if(kind==Kind.ANNOTATED) return Path.of(annotated).toAbsolutePath().normalize().resolve(imageBase.relativize(source));
            if(task.getResultOssPrefix()==null) return null;
            Path resultBase=Path.of(results).toAbsolutePath().normalize();
            Path result=Path.of(task.getResultOssPrefix()).toAbsolutePath().normalize();
            return result.startsWith(resultBase) && !result.equals(resultBase) ? result : null;
        } catch(InvalidPathException ignored) { return null; }
    }

    private Path base(Kind kind) {
        return Path.of(kind==Kind.IMAGE?images:kind==Kind.ANNOTATED?annotated:results).toAbsolutePath().normalize();
    }
    private boolean contains(Kind kind,Path root,Path requested) {
        try {
            Path normalized=requested.toAbsolutePath().normalize();
            if(!normalized.startsWith(root) || !root.startsWith(base(kind))) return false;
            LocalFileSafety.within(base(kind),root);
            LocalFileSafety.within(base(kind),normalized);
            return true;
        } catch(IOException ignored) { return false; }
    }
}
