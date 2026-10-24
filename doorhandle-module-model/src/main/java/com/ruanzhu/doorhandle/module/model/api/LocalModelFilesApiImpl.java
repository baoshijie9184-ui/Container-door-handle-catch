package com.ruanzhu.doorhandle.module.model.api;

import com.ruanzhu.doorhandle.common.LocalFileSafety;
import com.ruanzhu.doorhandle.contracts.files.*;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.model.service.ModelMutationIdentity;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.stereotype.Service;
import java.nio.file.*;
import java.io.IOException;

/** Only current supervisors may download a uniquely registered local detection model. */
@Service
public class LocalModelFilesApiImpl implements LocalModelFilesApi {
    private final ModelInfoMapper models;
    private final ModelMutationIdentity identity;
    private final Path root;
    public LocalModelFilesApiImpl(ModelInfoMapper models,ModelMutationIdentity identity,
            @Value("${model.upload-dir:${user.dir}/uploads/models}") String root) {
        this.models=models;this.identity=identity;this.root=Path.of(root).toAbsolutePath().normalize();
    }
    @Override public BusinessFileGrant authorizeFile(Path requested) {
        identity.supervisor();
        try {
            Path path=LocalFileSafety.within(root,requested);
            if(path.equals(root)) throw new AccessDeniedException("模型文件无权访问");
            Integer selected=null;
            for(var model:models.selectAll()) {
                if(model.getModelPath()==null) continue;
                Path candidate;
                try { candidate=Path.of(model.getModelPath()).toAbsolutePath().normalize(); }
                catch(InvalidPathException invalid) { continue; }
                if(!candidate.equals(path)) continue;
                if(selected!=null || model.getModelId()==null) throw new AccessDeniedException("模型文件关联不唯一");
                selected=model.getModelId();
            }
            if(selected==null) throw new AccessDeniedException("模型文件未登记或已移除");
            identity.supervisor();
            String id=selected.toString();
            return new BusinessFileGrant(id,LocalFileSafety.reference(id,"MODEL",root.relativize(path).toString()),null);
        } catch(IOException failure) { throw new AccessDeniedException("模型文件位置不可核对"); }
    }
}
