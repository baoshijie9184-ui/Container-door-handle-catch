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

@Aspect @Component @Order(0)
@ConditionalOnProperty(prefix="operations.audit",name="enabled",havingValue="true")
public class BusinessMutationAudit {
    private final OperationsAuditApi audit;private final BusinessUserDirectory users;private final TransactionTemplate tx;
    public BusinessMutationAudit(OperationsAuditApi audit,BusinessUserDirectory users,PlatformTransactionManager manager){this.audit=audit;this.users=users;tx=new TransactionTemplate(manager);}
    @Around("@annotation(operation)") public Object invoke(ProceedingJoinPoint call,BusinessMutation operation)throws Throwable{
        var authentication=SecurityContextHolder.getContext().getAuthentication();
        if(authentication==null||!(authentication.getPrincipal() instanceof TenantPrincipal principal))throw new SecurityException("业务变更缺少受信账号");
        var identity=users.current(principal.userId(),principal.username());var actor=new AgentActor(identity.userId(),identity.username(),identity.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);
        if(operation.supervisorOnly()&&!identity.supervisor())throw new SecurityException("主管权限已变化 业务变更未执行");
        Object[] args=call.getArgs();Object selected=AuditMetadata.select(operation.request(),args,null);
        final String correlation=AuditMetadata.request(selected);
        try{return tx.execute(status->{try{Object result=call.proceed();String target=AuditMetadata.resource(operation.resource(),args,result);Long version=AuditMetadata.version(operation.version(),args,result);audit.append(new OperationsAuditApi.Event(actor,operation.scope(),operation.domain(),operation.action(),target,correlation,Boolean.FALSE.equals(result)?"NO_CHANGE":"APPLIED",version));return result;}catch(Throwable failure){status.setRollbackOnly();throw new InvocationFailure(failure);}});}catch(InvocationFailure failure){throw failure.getCause();}
    }
    private static class InvocationFailure extends RuntimeException{InvocationFailure(Throwable cause){super(cause);}}
}
