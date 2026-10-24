package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.util.*;

@Service
@ConditionalOnProperty(prefix="operations.audit",name="file-delivery-enabled",havingValue="true")
public class FileDeliveryAuditService {
    public record Ticket(String deliveryId,boolean redirect,boolean headersOnly){
        public Ticket(String deliveryId,boolean redirect){this(deliveryId,redirect,false);}
    }
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final BusinessUserDirectory users;private final ObjectProvider<OperationsAuditApi> audit;
    public FileDeliveryAuditService(JdbcTemplate jdbc,PlatformTransactionManager manager,BusinessUserDirectory users,ObjectProvider<OperationsAuditApi> audit){this.jdbc=jdbc;tx=new TransactionTemplate(manager);tx.setTimeout(5);this.users=users;this.audit=audit;}
    @PostConstruct public void schema(){if(audit.getIfAvailable()==null)throw new IllegalStateException("文件交付审计需要启用必要业务审计");jdbc.queryForList("SELECT delivery_id,state,accepted_bytes_lower_bound,revision FROM operations_file_delivery WHERE 1=0");}
    public Ticket authorize(AgentActor actor,FileDelivery metadata,String resource,String file,Long version,String correlation,Long length,boolean redirect,int httpStatus){
        return authorize(actor,metadata,resource,file,version,correlation,length,redirect,httpStatus,false);
    }
    public Ticket authorize(AgentActor actor,FileDelivery metadata,String resource,String file,Long version,String correlation,Long length,boolean redirect,int httpStatus,boolean headersOnly){
        var identity=users.current(actor.userId(),actor.username());var current=new AgentActor(identity.userId(),identity.username(),identity.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);
        token(metadata.domain(),48);token(resource,160);token(correlation,128);if(file!=null)token(file,128);if(!Set.of("PRIVATE","ENTERPRISE").contains(metadata.scope())||length!=null&&length<0)throw new IllegalArgumentException("交付审计范围无效");
        String id=UUID.randomUUID().toString(),state=redirect?"REDIRECT_AUTHORIZED":headersOnly?"HEAD_AUTHORIZED":"AUTHORIZED";
        return tx.execute(status->{
            jdbc.update("INSERT INTO operations_file_delivery(delivery_id,actor_user_id,scope,domain,resource_id,file_id,correlation_id,resource_version,expected_bytes,state,http_status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",id,current.userId(),metadata.scope(),metadata.domain(),resource,file,correlation,version,length,state,redirect?httpStatus:null);
            audit.getObject().append(new OperationsAuditApi.Event(current,metadata.scope(),metadata.domain(),redirect?"FILE_REDIRECT_AUTHORIZED":headersOnly?"FILE_HEAD_AUTHORIZED":"FILE_AUTHORIZED",resource,id,state,version));return new Ticket(id,redirect,headersOnly);
        });
    }
    public void started(Ticket ticket){if(ticket.redirect()||ticket.headersOnly())return;tx.executeWithoutResult(status->{var row=lock(ticket.deliveryId());String state=(String)row.get("state");if(!Set.of("AUTHORIZED","UNKNOWN").contains(state))throw new IllegalStateException("文件交付状态无法核对");jdbc.update("UPDATE operations_file_delivery SET state='STREAMING',revision=revision+1,updated_at=CURRENT_TIMESTAMP(6) WHERE delivery_id=?",ticket.deliveryId());record(row,"FILE_STREAM_STARTED","STREAMING");});}
    public void finish(Ticket ticket,long lowerBound,int httpStatus,boolean interrupted,boolean unknown){
        if(ticket.redirect())return;
        tx.executeWithoutResult(status->{var row=lock(ticket.deliveryId());if(!Set.of("AUTHORIZED","HEAD_AUTHORIZED","STREAMING","UNKNOWN").contains(row.get("state")))return;
            String state=unknown?"UNKNOWN":interrupted||httpStatus<200||httpStatus>=300?"INTERRUPTED":ticket.headersOnly()?"HEAD_COMPLETED":"SERVER_COMPLETED";
            jdbc.update("UPDATE operations_file_delivery SET state=?,accepted_bytes_lower_bound=?,http_status=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP(6) WHERE delivery_id=?",state,lowerBound,httpStatus,ticket.deliveryId());record(row,"FILE_RESPONSE_FINISHED",state);
        });
    }
    /** Only records uncertainty; never repeats a download or claims that a browser received it. */
    @Scheduled(fixedDelay=60000) public void reconcile(){
        for(var item:jdbc.queryForList("SELECT delivery_id FROM operations_file_delivery WHERE state IN ('AUTHORIZED','HEAD_AUTHORIZED','STREAMING') AND updated_at<DATE_SUB(CURRENT_TIMESTAMP(6),INTERVAL 15 MINUTE) ORDER BY id LIMIT 20"))try{
            tx.executeWithoutResult(status->{var rows=jdbc.queryForList("SELECT * FROM operations_file_delivery WHERE delivery_id=? AND state IN ('AUTHORIZED','HEAD_AUTHORIZED','STREAMING') AND updated_at<DATE_SUB(CURRENT_TIMESTAMP(6),INTERVAL 15 MINUTE) FOR UPDATE SKIP LOCKED",item.get("delivery_id"));if(rows.isEmpty())return;var row=rows.get(0);jdbc.update("UPDATE operations_file_delivery SET state='UNKNOWN',revision=revision+1,updated_at=CURRENT_TIMESTAMP(6) WHERE delivery_id=?",item.get("delivery_id"));record(row,"FILE_RESPONSE_UNCONFIRMED","UNKNOWN");});
        }catch(RuntimeException unavailable){org.slf4j.LoggerFactory.getLogger(getClass()).warn("File delivery evidence remains unconfirmed");}
    }
    public List<Map<String,Object>> list(AgentActor actor,long before,int size){var user=users.current(actor.userId(),actor.username());if(before<1||size<1||size>100)throw new IllegalArgumentException("交付分页无效");String where=user.supervisor()?"(scope='ENTERPRISE' OR actor_user_id=?)":"actor_user_id=?";return jdbc.queryForList("SELECT id,delivery_id,actor_user_id,scope,domain,resource_id,file_id,correlation_id,resource_version,expected_bytes,accepted_bytes_lower_bound,http_status,state,revision,created_at,updated_at FROM operations_file_delivery WHERE id<? AND "+where+" ORDER BY id DESC LIMIT ?",before,user.userId(),size);}
    private Map<String,Object> lock(String id){return jdbc.queryForMap("SELECT * FROM operations_file_delivery WHERE delivery_id=? FOR UPDATE",id);}
    /** A completion may arrive after logout/revocation. It records the already-authorized actor, never grants new access. */
    private void record(Map<String,Object> row,String action,String result){
        jdbc.update("INSERT INTO operations_audit(actor_user_id,scope,domain,action,resource_id,request_id,result,resource_version,created_at) VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE id=id",row.get("actor_user_id"),row.get("scope"),row.get("domain"),action,row.get("resource_id"),row.get("delivery_id"),result,row.get("resource_version"));
    }
    private static void token(String value,int max){if(value==null||!value.matches("[A-Za-z0-9_:./-]{1,"+max+"}"))throw new IllegalArgumentException("交付元数据编号无效");}
}
