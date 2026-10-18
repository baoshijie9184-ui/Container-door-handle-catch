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
    public java.util.List<MemoryDtos.ReviewHistory> reviewHistory(TenantContext owner){return memory.reviewHistory(owner);}
    public MemoryDtos.Review getReview(TenantContext owner,String id){validateId(id);var result=memory.getReview(owner,id);preferences.reconcileReviewDecisions(owner,result);return result;}
    public MemoryDtos.Review startReview(TenantContext owner,String source,MemoryDtos.StartReview request){
        validateId(source);
        if(request==null||request.requestId()==null||!request.requestId().matches("[A-Za-z0-9_-]{1,64}")||request.expectedDigest()==null||!request.expectedDigest().matches("[a-f0-9]{64}")||request.expectedRevision()==null||request.expectedRevision()<0)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"请重新读取记忆及控制版本");
        if(!preferences.get(owner).readEnabled())throw new ResponseStatusException(HttpStatus.FORBIDDEN,"已关闭助手读取长期记忆 如需 AI 对比请先开启读取设置");
        return memory.startReview(owner,source,request);
    }
    public MemoryDtos.Review resolveReview(TenantContext owner,String id,MemoryDtos.ResolveReview request){
        validateId(id);
        if(request==null||!request.confirmed()||request.requestId()==null||!request.requestId().matches("[A-Za-z0-9_-]{1,64}")||request.candidateId()==null||!request.candidateId().matches("[A-Za-z0-9_-]{1,64}")||request.expectedRevision()==null||request.expectedRevision()<1||!java.util.Set.of("KEEP_SOURCE","KEEP_CANDIDATE","KEEP_BOTH").contains(request.choice()==null?"":request.choice()))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"请核对两条记忆及审阅版本并明确确认");
        var current=memory.getReview(owner,id);
        if(preferences.reserveReviewDecision(owner,current.sourceId(),id,request))return getReview(owner,id);
        MemoryDtos.Review saved;MemoryDtos.ReviewDecision proof;
        try{
            saved=memory.resolveReview(owner,id,request);
            proof=saved.decisions().stream().filter(row->request.requestId().equals(row.requestId())&&request.candidateId().equals(row.candidateId())&&request.choice().equals(row.choice())&&request.expectedRevision()==row.expectedRevision()).findFirst().orElseThrow();
            if(!saved.sourceId().equals(current.sourceId()))throw new IllegalStateException();
        }catch(ResponseStatusException error){preferences.deletionOutcome(owner,request.requestId(),error.getStatusCode().value()<500?"REJECTED":"UNKNOWN");throw error;}
        catch(RuntimeException error){preferences.deletionOutcome(owner,request.requestId(),"UNKNOWN");throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"审阅处理结果待核对 请读取原分析 不会重新执行");}
        preferences.reconcileReviewDecisions(owner,saved);preferences.requireReviewDecision(owner,saved,proof);return saved;
    }
    public java.util.List<MemoryDtos.Lifecycle> lifecycleHistory(TenantContext owner){return memory.lifecycleHistory(owner);}
    public MemoryDtos.Lifecycle verifyCleanup(TenantContext owner,String id){validateId(id);return memory.verifyCleanup(owner,id);}
    private void validateId(String id){if(id==null||!id.matches("[A-Za-z0-9_-]{1,64}"))throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"记忆编号不正确");}
    public MemoryDtos.Lifecycle changeLifecycle(TenantContext owner,String id,MemoryDtos.ChangeLifecycle request){
        validateId(id);
        if(request==null||request.requestId()==null||!request.requestId().matches("[A-Za-z0-9_-]{1,64}")||!request.confirmed()
            ||request.expectedDigest()==null||!request.expectedDigest().matches("[a-f0-9]{64}")||request.expectedRevision()==null||request.expectedRevision()<0
            ||!java.util.Set.of("ACTIVE","EXCLUDED").contains(request.state()==null?"":request.state())||request.expiresAt()!=null&&request.expiresAt().length()>50)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"请核对记忆及设置版本并明确确认");
        if(request.autoDelete()&&request.expiresAt()==null)throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"自动清理需要设置有效期并确认");
        if(request.expiresAt()!=null){
            try{var date=java.time.OffsetDateTime.parse(request.expiresAt());var now=java.time.OffsetDateTime.now();if(!date.isAfter(now)||date.isAfter(now.plusDays(3650)))throw new IllegalArgumentException();}
            catch(RuntimeException error){throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"有效期须为未来十年内带时区的时间");}
        }
        if(preferences.reserveLifecycle(owner,id,request)){
            var current=memory.getOwned(owner,id).lifecycle();
            if(current==null)throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"记忆治理回执缺失，请刷新核对");
            return current;
        }
        MemoryDtos.Lifecycle saved;
        try{saved=memory.changeLifecycle(owner,id,request);}
        catch(ResponseStatusException error){preferences.deletionOutcome(owner,request.requestId(),error.getStatusCode().value()<500?"REJECTED":"UNKNOWN");throw error;}
        catch(RuntimeException error){preferences.deletionOutcome(owner,request.requestId(),"UNKNOWN");throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"记忆治理结果待核对，请刷新");}
        preferences.deletionOutcome(owner,request.requestId(),"SUCCEEDED");return saved;
    }
    public MemoryDtos.Extraction verifyExtraction(TenantContext owner,String requestId) {
        if(requestId==null||!requestId.matches("[a-f0-9]{64}"))throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"提炼请求编号无效");
        preferences.automaticOutcome(owner,requestId);
        var receipt=memory.extractionReceipt(owner,requestId);
        preferences.reconcileAutomatic(owner,requestId,receipt.status());
        return receipt;
    }
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
