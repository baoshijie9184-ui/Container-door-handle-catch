package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.*;

/** Runs after resource authorization and before Spring writes the returned entity body. */
@Aspect @Component
@ConditionalOnProperty(prefix="operations.audit",name="file-delivery-enabled",havingValue="true")
public class FileDeliveryAuditAspect {
    static final String TICKET=FileDeliveryAuditAspect.class.getName()+".ticket";
    private final FileDeliveryAuditService deliveries;
    public FileDeliveryAuditAspect(FileDeliveryAuditService deliveries){this.deliveries=deliveries;}
    @Around("@annotation(metadata)") public Object invoke(ProceedingJoinPoint call,FileDelivery metadata)throws Throwable{
        Object value=call.proceed();if(!(value instanceof ResponseEntity<?> response))throw new IllegalStateException("文件交付必须返回明确的 HTTP 响应");
        int code=response.getStatusCode().value();if(code<200||code>=400||code==304)return value;
        if(!(RequestContextHolder.getRequestAttributes() instanceof ServletRequestAttributes servlet)||servlet.getRequest().isAsyncStarted())throw new IllegalStateException("文件交付需要同步 HTTP 请求上下文");
        if(servlet.getRequest().getAttribute(TICKET)!=null)throw new IllegalStateException("同一响应不能登记多个文件交付");
        var auth=SecurityContextHolder.getContext().getAuthentication();if(auth==null||!(auth.getPrincipal() instanceof TenantPrincipal user))throw new SecurityException("文件交付缺少受信账号");
        String correlation=AuditMetadata.request(null);
        var args=call.getArgs();String resource=AuditMetadata.resource(metadata.resource(),args,value);Object file=AuditMetadata.select(metadata.file(),args,value);
        boolean redirect=code>=300;Object body=response.getBody();Long length=null;
        if(!redirect){
            if(body instanceof byte[] bytes)length=(long)bytes.length;
            else if(body instanceof FileSystemResource disk)length=disk.contentLength();
            else if(!(body instanceof String||body instanceof Resource))throw new IllegalStateException("文件交付响应类型尚不支持审计");
        }
        if(redirect&&response.getHeaders().getLocation()==null)throw new IllegalStateException("重定向交付缺少读取目标");
        boolean headersOnly="HEAD".equals(servlet.getRequest().getMethod());
        if(headersOnly)length=0L;
        var ticket=deliveries.authorize(new AgentActor(user.userId(),user.username(),AgentActor.Role.INSPECTOR),metadata,resource,file==null?null:file.toString(),AuditMetadata.version(metadata.version(),args,value),correlation,length,redirect,code,headersOnly);
        servlet.getRequest().setAttribute(TICKET,ticket);
        servlet.getRequest().setAttribute(TICKET+".length",length);
        if(servlet.getResponse()!=null){servlet.getResponse().setHeader("X-File-Delivery-ID",ticket.deliveryId());servlet.getResponse().setHeader("X-Request-ID",correlation);}
        return value;
    }
}
