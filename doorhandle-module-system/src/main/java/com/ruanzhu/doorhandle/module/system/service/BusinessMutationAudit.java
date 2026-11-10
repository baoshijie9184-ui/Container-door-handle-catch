package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.annotation.Order;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessMutationParticipant;
import com.ruanzhu.doorhandle.common.BusinessException;
import java.util.List;

@Aspect @Component @Order(0)
@ConditionalOnProperty(prefix="operations.audit",name="enabled",havingValue="true")
public class BusinessMutationAudit {
    private final OperationsAuditApi audit;private final BusinessUserDirectory users;private final TransactionTemplate tx;
    private List<BusinessMutationParticipant> participants=List.of();
    private BusinessCommandStore commands;
    @org.springframework.beans.factory.annotation.Value("${collaboration.mutations.enabled:false}") private boolean mutationProtectionEnabled;
    private final ThreadLocal<String> activeRequest=new ThreadLocal<>();
    public BusinessMutationAudit(OperationsAuditApi audit,BusinessUserDirectory users,PlatformTransactionManager manager){this.audit=audit;this.users=users;tx=new TransactionTemplate(manager);}
    @org.springframework.beans.factory.annotation.Autowired
    public void collaboration(org.springframework.jdbc.core.JdbcTemplate jdbc,List<BusinessMutationParticipant> participants){this.commands=new BusinessCommandStore(jdbc);this.participants=List.copyOf(participants);}
    @Around("@annotation(operation)") public Object invoke(ProceedingJoinPoint call,BusinessMutation operation)throws Throwable{
        var authentication=SecurityContextHolder.getContext().getAuthentication();
        if(authentication==null||!(authentication.getPrincipal() instanceof TenantPrincipal principal))throw new SecurityException("业务变更缺少受信账号");
        var identity=users.current(principal.userId(),principal.username());var actor=new AgentActor(identity.userId(),identity.username(),identity.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);
        if(operation.supervisorOnly()&&!identity.supervisor())throw new SecurityException("主管权限已变化 业务变更未执行");
        Object[] args=call.getArgs();Object selected=AuditMetadata.select(operation.request(),args,null);
        if(mutationProtectionEnabled){if(commands==null)throw new IllegalStateException("业务修改命令存储未就绪");return versioned(call,operation,actor,args,selected);}
        final String correlation=AuditMetadata.request(selected);
        try{return tx.execute(status->{try{Object result=call.proceed();String target=AuditMetadata.resource(operation.resource(),args,result);Long version=AuditMetadata.version(operation.version(),args,result);audit.append(new OperationsAuditApi.Event(actor,operation.scope(),operation.domain(),operation.action(),target,correlation,Boolean.FALSE.equals(result)?"NO_CHANGE":"APPLIED",version));return result;}catch(Throwable failure){status.setRollbackOnly();throw new InvocationFailure(failure);}});}catch(InvocationFailure failure){throw failure.getCause();}
    }
    private Object versioned(ProceedingJoinPoint call,BusinessMutation operation,AgentActor actor,Object[] args,Object selected)throws Throwable {
        // The outer command owns every persisted before/after fact of a compound write.
        // Auditing nested service calls separately would report the same change twice.
        var matching=participants.stream().filter(item->item.supports(operation.domain(),operation.action())).toList();
        if(matching.size()!=1)throw new IllegalStateException("业务修改尚未登记唯一留痕策略: "+operation.domain()+"/"+operation.action());
        if(activeRequest.get()!=null)return call.proceed();
        var participant=matching.get(0);boolean root=true;
        String request=AuditMetadata.requiredRequest(selected);
        Long expected=AuditMetadata.expectedVersion(args,((org.aspectj.lang.reflect.MethodSignature)call.getSignature()).getParameterNames());
        try{return tx.execute(status->{try {
            var method=((org.aspectj.lang.reflect.MethodSignature)call.getSignature()).getMethod();
            String id=participant.resourceId(operation.domain(),operation.action(),args,null);
            participant.prepare(actor,operation.domain(),operation.action(),id,args);
            var lockedIdentity=users.lockCurrent(actor.userId(),actor.username());
            if(operation.supervisorOnly()&&!lockedIdentity.supervisor())throw new SecurityException("主管权限已变化 业务变更未执行");
            var recordedActor=new AgentActor(lockedIdentity.userId(),lockedIdentity.username(),lockedIdentity.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);
            String actorDisplayName=audit instanceof OperationsAuditService service?java.util.Objects.toString(service.actorDisplayName(recordedActor),""):null;
            BusinessCommandStore.Claim claim=null;
            if(root){String digest=commands.digest(method.toGenericString(),operation.domain(),operation.action(),expected,participant.digestInput(operation.action(),args));
                claim=commands.claim(actor.userId(),request,digest,operation.domain(),operation.action());
                if(claim.repeated()){
                    String resource=participant.resourceId(operation.domain(),operation.action(),args,null);
                    if(resource!=null)participant.capture(recordedActor,operation.domain(),operation.action(),resource,true);
                    return commands.replay(claim,method.getGenericReturnType());
                }
                activeRequest.set(request);
            }
            var before=id==null?null:participant.capture(recordedActor,operation.domain(),operation.action(),id,true);
            var relatedBefore=participant.related(recordedActor,operation.domain(),operation.action(),id,args,List.of(),true);
            if(participant.creates(operation.action())&&before!=null)throw new BusinessException(409,"待创建资源已经存在，请使用更新操作");
            if(root&&!participant.creates(operation.action())){
                if(expected==null)throw new BusinessException(409,"修改必须提供 expectedVersion 或 X-Expected-Version，请重新读取资料");
                if(before==null||before.version()==null||!expected.equals(before.version()))throw new BusinessException(409,"资料已被其他用户修改，请重新读取后提交");
            }
            // Legacy DTOs may carry the expected revision exclusively in an HTTP header.
            // Populate the already validated persisted revision for existing ORM CAS methods.
            if(before!=null)for(Object argument:args)updateReturnedRevision(argument,before);
            Object result=call.proceed();
            String finalId=participant.resourceId(operation.domain(),operation.action(),args,result);
            if(finalId==null)finalId=id;
            var after=finalId==null?null:participant.capture(recordedActor,operation.domain(),operation.action(),finalId,false);
            var changes=BusinessFieldChanges.compare(before,after);
            if(!changes.isEmpty()){
                after=participant.advanceVersion(before,after);
                updateReturnedRevision(result,after);
                for(Object argument:args)updateReturnedRevision(argument,after);
                String type=after!=null?after.resourceType():before.resourceType();
                audit.appendChange(new OperationsAuditApi.ChangeEvent(new OperationsAuditApi.Event(recordedActor,operation.scope(),operation.domain(),operation.action(),finalId,
                        request,"APPLIED",after==null?null:after.version()),type,actorDisplayName,before==null?null:before.version(),changes));
            }
            updateReturnedRevision(result,after);
            for(Object argument:args)updateReturnedRevision(argument,after);
            var relatedAfter=participant.related(recordedActor,operation.domain(),operation.action(),finalId,args,relatedBefore,false);
            var all=new java.util.TreeMap<String,BusinessMutationParticipant.Snapshot[]>();
            for(var value:relatedBefore)all.computeIfAbsent(value.resourceType()+":"+value.resourceId(),key->new BusinessMutationParticipant.Snapshot[2])[0]=value;
            for(var value:relatedAfter)all.computeIfAbsent(value.resourceType()+":"+value.resourceId(),key->new BusinessMutationParticipant.Snapshot[2])[1]=value;
            for(var pair:all.values()){
                var diff=BusinessFieldChanges.compare(pair[0],pair[1]);if(diff.isEmpty())continue;
                var current=participant.advanceVersion(pair[0],pair[1]);var reference=current==null?pair[0]:current;
                audit.appendChange(new OperationsAuditApi.ChangeEvent(new OperationsAuditApi.Event(recordedActor,operation.scope(),participant.resourceDomain(reference,operation.domain()),operation.action(),reference.resourceId(),
                        request,"APPLIED",current==null?null:current.version()),reference.resourceType(),actorDisplayName,pair[0]==null?null:pair[0].version(),diff));
            }
            if(root){
                var reference=after==null?before:after;
                var receipt=reference==null?null:commands.receipt(actor.userId(),request,reference.resourceType(),reference.resourceId(),after==null?null:after.version());
                commands.complete(claim,result,receipt);BusinessCommandStore.headers(receipt);
            }
            return result;
        }catch(Throwable failure){status.setRollbackOnly();throw new InvocationFailure(failure);}finally{if(root)activeRequest.remove();}});
        }catch(InvocationFailure failure){throw failure.getCause();}
    }
    private static void updateReturnedRevision(Object result,BusinessMutationParticipant.Snapshot after){
        if(result==null||after==null)return;
        if(result instanceof java.util.Map<?,?> values){
            for(String wrapper:List.of("body","data","resource","record","task"))if(values.containsKey(wrapper))updateReturnedRevision(values.get(wrapper),after);
            Object id=null;for(String key:List.of("id","taskId","modelId","reportId","resourceId"))if(values.get(key)!=null){id=values.get(key);break;}
            if(id!=null&&after.resourceId().equals(id.toString())){
                @SuppressWarnings("unchecked") var mutable=(java.util.Map<Object,Object>)values;
                String key=values.containsKey("rowVersion")?"rowVersion":values.containsKey("mutationVersion")?"mutationVersion":values.containsKey("version")?"version":null;
                if(key!=null&&(!"DETECTION_MODEL".equals(after.resourceType())||!"version".equals(key)))try{mutable.put(key,String.valueOf(after.version()));}catch(UnsupportedOperationException immutable){/* Receipt header carries immutable response revisions. */}
            }
            return;
        }
        boolean hasRowVersion=false;try{result.getClass().getMethod("getRowVersion");hasRowVersion=true;}catch(NoSuchMethodException absent){}
        for(String field:hasRowVersion?List.of("RowVersion"):List.of("MutationVersion","Version"))try{
            var getter=result.getClass().getMethod("get"+field);Class<?> type=getter.getReturnType();
            if(type==Long.class)result.getClass().getMethod("set"+field,Long.class).invoke(result,after.version());
            else if(type==Integer.class)result.getClass().getMethod("set"+field,Integer.class).invoke(result,Math.toIntExact(after.version()));
            else if(type==String.class&&!("DETECTION_MODEL".equals(after.resourceType())&&"Version".equals(field)))result.getClass().getMethod("set"+field,String.class).invoke(result,String.valueOf(after.version()));
        }catch(NoSuchMethodException absent){}catch(ReflectiveOperationException invalid){throw new IllegalStateException("业务版本回执不可写",invalid);}
    }
    private static class InvocationFailure extends RuntimeException{InvocationFailure(Throwable cause){super(cause);}}
}
