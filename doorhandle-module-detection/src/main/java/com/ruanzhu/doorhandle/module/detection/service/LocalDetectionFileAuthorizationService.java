package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.infra.security.LocalDetectionFileAuthorization;
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
public class LocalDetectionFileAuthorizationService implements LocalDetectionFileAuthorization {
    private final DetectionTaskMapper mapper;
    private final DetectionTaskAccessPolicy policy;
    @Value("${detection.upload-dir:${user.dir}/uploads/images}") private String images;
    @Value("${detection.annotated-dir:${user.dir}/uploads/annotated}") private String annotated;
    @Value("${detection.result-dir:${user.dir}/uploads/results}") private String results;

    @Override public void authorize(Kind kind, Path path) {
        var authentication=SecurityContextHolder.getContext().getAuthentication();
        var query=new LambdaQueryWrapper<DetectionTask>();
        policy.applyScope(query,authentication);
        query.isNotNull(DetectionTask::getSourceOssPrefix);
        for(var task:mapper.selectList(query)) {
            if(!policy.canAccess(task,authentication.getName(),policy.isAdmin(authentication))) continue;
            Path root=allowedRoot(task,kind);
            if(root!=null && contains(root,path)) return;
        }
        throw new AccessDeniedException("无权访问该资源");
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

    private boolean contains(Path root,Path requested) {
        try {
            Path resolvedRoot=Files.exists(root)?root.toRealPath():root;
            Path resolvedRequested=Files.exists(requested)?requested.toRealPath():requested.toAbsolutePath().normalize();
            return resolvedRequested.startsWith(resolvedRoot);
        } catch(IOException ignored) { return false; }
    }
}
