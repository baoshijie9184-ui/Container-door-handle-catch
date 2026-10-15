package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
@RequiredArgsConstructor
public class PersonalMemoryService {
    private final Mem0Client memory;
    private final MemoryPreferenceService preferences;
    public MemoryDtos.Item get(TenantContext owner,String id) {
        if(id==null||!id.matches("[A-Za-z0-9_-]{1,64}"))throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"记忆编号不正确");
        return memory.getOwned(owner,id);
    }
    public MemoryDtos.Page list(TenantContext owner,int limit) {
        return list(owner,limit,0);
    }
    public MemoryDtos.Page list(TenantContext owner,int limit,int offset) {
        if(limit<1||limit>100)throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"读取数量必须在 1 到 100 之间");
        if(offset<0||offset>Integer.MAX_VALUE-101)throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"分页位置不正确");
        return offset==0?memory.listOwned(owner,limit):memory.listOwned(owner,limit,offset);
    }
    public MemoryDtos.Updated update(TenantContext owner,String id,MemoryDtos.Update request) {
        if(id==null||!id.matches("[A-Za-z0-9_-]{1,64}")||request==null||request.requestId()==null||!request.requestId().matches("[A-Za-z0-9_-]{1,64}")
                ||request.expectedDigest()==null||!request.expectedDigest().matches("[a-f0-9]{64}")||!request.confirmed()
                ||request.memory()==null||request.memory().isBlank()||request.memory().length()>4000)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"修改需要核对版本、1 到 4000 字正文并明确确认");
        var normalized=new MemoryDtos.Update(request.requestId(),request.expectedDigest(),request.memory().strip(),true);
        if(preferences.reserveUpdate(owner,id,normalized))return new MemoryDtos.Updated(true,true);
        try {
            memory.updateOwned(owner,id,normalized.expectedDigest(),normalized.memory());
        } catch(ResponseStatusException error) {
            preferences.deletionOutcome(owner,request.requestId(),error.getStatusCode().value()<500?"REJECTED":"UNKNOWN");
            throw error;
        } catch(RuntimeException error) {
            preferences.deletionOutcome(owner,request.requestId(),"UNKNOWN");
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"修改结果待核对，请刷新记忆列表");
        }
        preferences.deletionOutcome(owner,request.requestId(),"SUCCEEDED");
        return new MemoryDtos.Updated(true,false);
    }
    public MemoryDtos.Deleted delete(TenantContext owner,String id,MemoryDtos.Delete request) {
        if(id==null||!id.matches("[A-Za-z0-9_-]{1,64}")||request==null||request.requestId()==null||!request.requestId().matches("[A-Za-z0-9_-]{1,64}")
                ||request.expectedDigest()==null||!request.expectedDigest().matches("[a-f0-9]{64}")||!request.confirmed())
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"删除需要核对记忆版本并明确确认");
        if(preferences.reserveDelete(owner,id,request))return new MemoryDtos.Deleted(true,true);
        try {
            memory.deleteOwned(owner,id,request.expectedDigest());
        } catch(ResponseStatusException error) {
            preferences.deletionOutcome(owner,request.requestId(),error.getStatusCode().value()<500?"REJECTED":"UNKNOWN");
            throw error;
        } catch(RuntimeException error) {
            preferences.deletionOutcome(owner,request.requestId(),"UNKNOWN");
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"删除结果待核对，请刷新记忆列表");
        }
        preferences.deletionOutcome(owner,request.requestId(),"SUCCEEDED");
        return new MemoryDtos.Deleted(true,false);
    }
}
