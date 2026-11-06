package com.ruanzhu.doorhandle.module.system.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.time.LocalDateTime;
import java.util.*;

@Service
@ConditionalOnProperty(prefix="operations.audit",name="file-delivery-enabled",havingValue="true")
public class FileDeliveryAuditService {
    public record Ticket(String deliveryId,boolean redirect,boolean headersOnly) {
        public Ticket(String deliveryId,boolean redirect) {this(deliveryId,redirect,false);}
    }
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final BusinessUserDirectory users;
    private final ObjectProvider<OperationsAuditApi> audit;
    private final ObjectMapper json=new ObjectMapper().enable(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES)
            .enable(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_NULL_FOR_PRIMITIVES);
    private final JdbcWorkflowStore workflows;
    private final OperationsAuditPersistence records;
    public FileDeliveryAuditService(JdbcTemplate jdbc,PlatformTransactionManager manager,BusinessUserDirectory users,ObjectProvider<OperationsAuditApi> audit) {
        this.jdbc=jdbc;tx=new TransactionTemplate(manager);tx.setTimeout(5);this.users=users;this.audit=audit;
        workflows=new JdbcWorkflowStore(jdbc,json,FileDeliveryProtocol.protocols());records=new OperationsAuditPersistence(jdbc);
    }
    @PostConstruct public void schema() {
        if(audit.getIfAvailable()==null)throw new IllegalStateException("文件交付审计需要启用必要业务审计");
        workflows.validateSchema();
        jdbc.queryForList("SELECT operation_scope,operation_domain,operation_result FROM audit_event WHERE 1=0");
    }
    public Ticket authorize(AgentActor actor,FileDelivery metadata,String resource,String file,Long version,String correlation,Long length,boolean redirect,int httpStatus) {
        return authorize(actor,metadata,resource,file,version,correlation,length,redirect,httpStatus,false);
    }
    public Ticket authorize(AgentActor actor,FileDelivery metadata,String resource,String file,Long version,String correlation,Long length,boolean redirect,int httpStatus,boolean headersOnly) {
        var identity=users.current(actor.userId(),actor.username());
        var current=new AgentActor(identity.userId(),identity.username(),identity.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);
        OperationsAuditPersistence.token(resource,160);
        String id=UUID.randomUUID().toString(),state=redirect?"REDIRECT_AUTHORIZED":headersOnly?"HEAD_AUTHORIZED":"AUTHORIZED";
        var payload=new FileDeliveryProtocol.DeliveryV1(metadata.scope(),metadata.domain(),file,correlation,version,length,0,
                redirect?httpStatus:null,redirect?"REDIRECT":headersOnly?"HEAD":"BODY",null,null,null);
        return tx.execute(status->{
            workflows.create(new WorkflowDraft(id,WorkflowKind.FILE_DELIVERY,"FILE_DELIVERY",id,FileDeliveryProtocol.digest(current.userId(),resource,payload),
                    current.userId(),current.userId(),null,"FILE_DELIVERY",resource,null,null,null,state,null,1,payload));
            audit.getObject().append(new OperationsAuditApi.Event(current,metadata.scope(),metadata.domain(),
                    redirect?"FILE_REDIRECT_AUTHORIZED":headersOnly?"FILE_HEAD_AUTHORIZED":"FILE_AUTHORIZED",resource,id,state,version));
            return new Ticket(id,redirect,headersOnly);
        });
    }
    public void started(Ticket ticket) {
        if(ticket.redirect() || ticket.headersOnly())return;
        tx.executeWithoutResult(status->{
            var row=lock(ticket.deliveryId());var payload=workflows.payload(row,FileDeliveryProtocol.DeliveryV1.class);requireMode(ticket,payload);
            if(!Set.of("AUTHORIZED","UNKNOWN").contains(row.status()))throw new IllegalStateException("文件交付状态无法核对");
            workflows.transition(row,"STREAMING",payload,null,null,null);record(row,payload,"FILE_STREAM_STARTED","STREAMING");
        });
    }
    public void finish(Ticket ticket,long lowerBound,int httpStatus,boolean interrupted,boolean unknown) {
        if(ticket.redirect())return;
        if(lowerBound<0 || httpStatus<100 || httpStatus>599)throw new IllegalArgumentException("交付完成证据无效");
        tx.executeWithoutResult(status->{
            var row=lock(ticket.deliveryId());
            if(FileDeliveryProtocol.TERMINAL.contains(row.status()))return;
            var payload=workflows.payload(row,FileDeliveryProtocol.DeliveryV1.class);requireMode(ticket,payload);
            String next=unknown?"UNKNOWN":interrupted || httpStatus<200 || httpStatus>=300?"INTERRUPTED":ticket.headersOnly()?"HEAD_COMPLETED":"SERVER_COMPLETED";
            // Preserve all known lower-bound evidence; neither UNKNOWN nor a smaller observation proves zero accepted bytes.
            var after=payload.observed(lowerBound,httpStatus,payload.deliveryMode());
            workflows.transition(row,next,after,null,null,null);record(row,payload,"FILE_RESPONSE_FINISHED",next);
        });
    }
    /** Marks uncertainty only. It cannot retry a download or assert receipt by a browser. */
    @Scheduled(fixedDelay=60000) public void reconcile() {
        for(String id:jdbc.queryForList("SELECT workflow_id FROM workflow_instance WHERE kind='FILE_DELIVERY' "
                + "AND status IN ('AUTHORIZED','HEAD_AUTHORIZED','STREAMING') AND updated_at<DATE_SUB(UTC_TIMESTAMP(6),INTERVAL 15 MINUTE) ORDER BY id LIMIT 20",String.class)) {
            try {
                tx.executeWithoutResult(status->{
                    var selected=jdbc.queryForList("SELECT workflow_id FROM workflow_instance WHERE kind='FILE_DELIVERY' AND workflow_id=? "
                            + "AND status IN ('AUTHORIZED','HEAD_AUTHORIZED','STREAMING') AND updated_at<DATE_SUB(UTC_TIMESTAMP(6),INTERVAL 15 MINUTE) FOR UPDATE SKIP LOCKED",String.class,id);
                    if(selected.isEmpty())return;
                    var row=lock(id);var payload=workflows.payload(row,FileDeliveryProtocol.DeliveryV1.class);
                    workflows.transition(row,"UNKNOWN",payload,null,null,null);record(row,payload,"FILE_RESPONSE_UNCONFIRMED","UNKNOWN");
                });
            } catch(RuntimeException unavailable) {org.slf4j.LoggerFactory.getLogger(getClass()).warn("File delivery evidence remains unconfirmed");}
        }
    }
    public List<Map<String,Object>> list(AgentActor actor,long before,int size) {
        var user=users.current(actor.userId(),actor.username());
        if(before<1 || size<1 || size>100)throw new IllegalArgumentException("交付分页无效");
        String where=user.supervisor()?"(file_delivery_scope='ENTERPRISE' OR owner_user_id=?)":"owner_user_id=?";
        return jdbc.query("SELECT id,workflow_id,owner_user_id,resource_id,status,revision,payload_json,created_at,updated_at FROM workflow_instance "
                + "WHERE kind='FILE_DELIVERY' AND id<? AND "+where+" ORDER BY id DESC LIMIT ?",(rs,index)->{
            FileDeliveryProtocol.DeliveryV1 payload;
            try {payload=json.readValue(rs.getString("payload_json"),FileDeliveryProtocol.DeliveryV1.class);}
            catch(JsonProcessingException error) {throw new IllegalStateException("Stored delivery evidence is invalid",error);}
            Map<String,Object> row=new LinkedHashMap<>();row.put("id",rs.getLong("id"));row.put("delivery_id",rs.getString("workflow_id"));
            row.put("actor_user_id",rs.getLong("owner_user_id"));row.put("scope",payload.scope());row.put("domain",payload.domain());
            row.put("resource_id",rs.getString("resource_id"));row.put("file_id",payload.fileId());row.put("correlation_id",payload.correlationId());
            row.put("resource_version",payload.resourceVersion());row.put("expected_bytes",payload.expectedBytes());row.put("accepted_bytes_lower_bound",payload.acceptedBytesLowerBound());
            row.put("http_status",payload.httpStatus());row.put("state",rs.getString("status"));row.put("revision",rs.getLong("revision"));
            row.put("created_at",OperationsAuditPersistence.displayTime(rs.getObject("created_at",LocalDateTime.class)));
            row.put("updated_at",OperationsAuditPersistence.displayTime(rs.getObject("updated_at",LocalDateTime.class)));return row;
        },before,user.userId(),size);
    }
    private WorkflowRecord lock(String id) {return workflows.findLocked(WorkflowKind.FILE_DELIVERY,id).orElseThrow(()->new IllegalStateException("文件交付凭据不存在"));}
    private static void requireMode(Ticket ticket,FileDeliveryProtocol.DeliveryV1 payload) {
        String expected=ticket.redirect()?"REDIRECT":ticket.headersOnly()?"HEAD":"BODY";
        if(!payload.deliveryMode().equals("UNKNOWN") && !payload.deliveryMode().equals(expected))throw new IllegalStateException("文件交付方式与授权不一致");
    }
    /** Completion records the authorized actor after logout/revocation; it does not authorize another download. */
    private void record(WorkflowRecord row,FileDeliveryProtocol.DeliveryV1 payload,String action,String result) {
        records.append(row.ownerUserId(),payload.scope(),payload.domain(),action,row.resourceId(),row.workflowId(),result,payload.resourceVersion());
    }
}
