package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi;
import com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory.Change;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.util.*;

/** Domain-owned public facts only; callers never supply request beans or decrypted snapshots. */
@Component
public class AiCollaborationHistory {
    private final OperationsAuditApi audit;
    @org.springframework.beans.factory.annotation.Autowired(required=false)
    private com.ruanzhu.doorhandle.contracts.security.BusinessAccountLookupApi accounts;
    @Value("${collaboration.change-history.enabled:false}") private boolean history;
    @Value("${collaboration.mutations.enabled:false}") private boolean mutations;
    public AiCollaborationHistory(OperationsAuditApi audit){this.audit=audit;}
    boolean enabled(){return history||mutations;}
    boolean protectsCommands(){return mutations;}
    String username(long id){return accounts==null?null:accounts.username(id);}
    void replayReceipt(AgentActor actor,String domain,String type,String id,String request){
        if(!protectsCommands())return;
        // The owning service has already verified its immutable request digest and business result.
        var receipt=audit.findChangeReceipt(actor,domain,type,id,request);
        if(receipt==null)throw new com.ruanzhu.doorhandle.common.BusinessException(409,"旧命令原始修改回执未确认，请保留编号核对");
        headers(receipt);
    }
    private static final Map<String,String> LABELS=Map.ofEntries(
            Map.entry("status","状态"),Map.entry("modelId","模型编号"),Map.entry("modelCatalog","已登记模型及启用状态"),
            Map.entry("defaultModel","默认模型"),Map.entry("fallbackModels","备用模型顺序"),Map.entry("fallbackEnabled","备用模型开关"),
            Map.entry("timeoutMs","请求超时毫秒"),Map.entry("firstTokenTimeoutMs","首个响应超时毫秒"),Map.entry("maxOutputTokens","最大输出Tokens"),
            Map.entry("memoryModel","记忆提炼模型"),Map.entry("activeRevision","生效配置编号"),Map.entry("probeStatus","JSON格式检查状态"),
            Map.entry("dashscopeCredential","DashScope连接凭据"),Map.entry("deepseekCredential","DeepSeek连接凭据"),Map.entry("openaiCredential","OpenAI连接凭据"),
            Map.entry("totalTokens","登记总额度"),Map.entry("warningPercent","提醒阈值百分比"),Map.entry("expiresAt","免费额度到期时间"),Map.entry("freeOnly","仅使用免费额度"),
            Map.entry("ownerUserId","申请账号ID"),Map.entry("ownerUsername","申请时账号"),Map.entry("requestedTokens","申请额度"),
            Map.entry("reasonDigest","申请说明摘要"),Map.entry("decisionReasonDigest","审批说明摘要"),Map.entry("deciderUserId","处理账号ID"),
            Map.entry("deciderUsername","处理时账号"),Map.entry("remainingTokens","实际核对剩余额度"),Map.entry("observedAt","核对时间"),Map.entry("sourceNoteDigest","核对来源说明摘要"));
    OperationsAuditApi.ChangeReceipt record(AgentActor actor,String domain,String type,String id,String action,String request,String result,
                Long beforeVersion,Long afterVersion,Map<String,Object> before,Map<String,Object> after,Set<String> secrets){
        if(!enabled())return null;
        var fields=new TreeSet<String>();fields.addAll(before.keySet());fields.addAll(after.keySet());
        var changes=new ArrayList<Change>();
        for(String field:fields){
            if(!LABELS.containsKey(field))throw new IllegalArgumentException("Unregistered AI history field");
            Object left=before.get(field),right=after.get(field);
            if(before.containsKey(field)==after.containsKey(field)&&Objects.equals(left,right))continue;
            boolean secret=secrets.contains(field);
            changes.add(new Change(field,LABELS.get(field),secret?"CHANGED":!before.containsKey(field)?"ADD":!after.containsKey(field)?"REMOVE":"REPLACE",
                    secret?null:left,secret?null:right,secret?"SECRET":left instanceof Number||right instanceof Number?"NUMBER":"SCALAR",secret));
        }
        if(changes.isEmpty())return null;
        var receipt=audit.appendChangeWithReceipt(new OperationsAuditApi.ChangeEvent(new OperationsAuditApi.Event(actor,"ENTERPRISE",domain,action,id,request,result,afterVersion),
                type,null,beforeVersion,changes));
        if(receipt==null||receipt.auditId()==null||receipt.eventId()==null||!Objects.equals(receipt.resourceVersion(),afterVersion==null?null:afterVersion.toString()))
            throw new IllegalStateException("Required AI change audit receipt unavailable");
        headers(receipt);return receipt;
    }
    static void headers(OperationsAuditApi.ChangeReceipt receipt){
        if(receipt==null)return;var attributes=org.springframework.web.context.request.RequestContextHolder.getRequestAttributes();
        if(attributes instanceof org.springframework.web.context.request.ServletRequestAttributes servlet&&servlet.getResponse()!=null){
            if(receipt.auditId()!=null)servlet.getResponse().setHeader("X-Audit-ID",receipt.auditId());
            if(receipt.eventId()!=null)servlet.getResponse().setHeader("X-Change-Event-ID",receipt.eventId());
            if(receipt.resourceVersion()!=null)servlet.getResponse().setHeader("X-Resource-Version",receipt.resourceVersion());
        }
    }
}
