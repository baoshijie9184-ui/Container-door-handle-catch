package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.*;

/** Global technical image management is supervisor-only. No private account installation DTO is returned. */
@Service
@ConditionalOnProperty(prefix="agentscope.mcp",name={"enabled","shared-image-cleanup-enabled"},havingValue="true")
public class FetchSharedImageService implements com.ruanzhu.doorhandle.contracts.agent.AgentMcpImagesApi {
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final ObjectMapper json;
    private final BusinessUserDirectory users;private final LocalMcpProperties properties;private final FetchMcpRuntime runtime;
    private final FetchImageRegistry registry;private final McpGatewayClient gateway;private final Path workspace;
    public FetchSharedImageService(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,BusinessUserDirectory users,LocalMcpProperties properties,FetchMcpRuntime runtime,AgentScopeProperties agent){
        this.jdbc=jdbc;this.json=json;this.users=users;this.properties=properties;this.runtime=runtime;this.registry=runtime.imageRegistry();this.gateway=new McpGatewayClient(properties,json);
        this.workspace=Path.of(agent.getWorkspace().replace("${user.dir}",System.getProperty("user.dir"))).toAbsolutePath().normalize();
        this.tx=new TransactionTemplate(manager);tx.setTimeout(15);tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        if(!properties.isGateway()||registry==null)throw new IllegalStateException("MCP_IMAGE_GATEWAY_REQUIRED");
    }
    @PostConstruct public void schema(){registry.schema();jdbc.queryForList("SELECT connector_cleanup_owner_user_id AS cleanup_owner_user_id FROM content_asset WHERE asset_kind='CONNECTOR_IMAGE' AND (1=0) ");jdbc.queryForList("SELECT mcp_action AS action_name,request_sha256,mcp_retention_protocol AS retention_protocol FROM workflow_instance WHERE kind='MCP_IMAGE_COMMAND' AND (1=0) ");jdbc.queryForList("SELECT subject_id AS reference_id,subject_type AS reference_kind,state FROM content_link WHERE link_kind='CONNECTOR_RETENTION' AND (1=0) ");jdbc.queryForList("SELECT state_code AS state,revision FROM runtime_state WHERE namespace='MCP_RETENTION_CONTROL' AND owner_id=0 AND (CAST(scope_key AS SIGNED)=1) ");}
    private AgentActor supervisor(AgentActor actor){
        var current=users.current(actor.userId(),actor.username());if(current.userId()<1||!current.supervisor())throw fail(403,"仅主管可以管理共享运行镜像");
        return new AgentActor(current.userId(),current.username(),AgentActor.Role.SUPERVISOR);
    }
    private Path identity(long owner){return workspace.resolve("users").resolve(Long.toString(owner)).resolve("mcp/fetch/installs").resolve("00000000-0000-0000-0000-000000000001");}
    private Set<String> approved(){var result=new LinkedHashSet<String>();result.add(properties.getGatewayImage());result.addAll(properties.getApprovedGatewayImages());return result;}
    public Map<String,Object> view(AgentActor actor){
        var current=supervisor(actor);Map<String,Object> inventory;
        try{inventory=gateway.imageInventory(identity(current.userId()));}catch(Exception error){if(error instanceof InterruptedException)Thread.currentThread().interrupt();inventory=Map.of("items",List.of());}
        Long legalBytes=inventory.get("legalArchiveBytes") instanceof Number amount&&amount.longValue()>=0?amount.longValue():null;
        boolean cleanupAllowed=Boolean.TRUE.equals(inventory.get("cleanupAllowed"));
        var observed=new HashMap<String,Map<String,Object>>();
        if(inventory.get("items") instanceof List<?> items)for(Object item:items)if(item instanceof Map<?,?> raw&&raw.get("image") instanceof String image&&approved().contains(image)){
            var value=new LinkedHashMap<String,Object>();value.put("present",raw.get("present") instanceof Boolean?raw.get("present"):null);value.put("imageBytes",raw.get("imageBytes") instanceof Number size&&size.longValue()>=0?size.longValue():null);value.put("runnerState",raw.get("state"));observed.put(image,value);
        }
        supervisor(current);return tx.execute(status->{
            var images=new LinkedHashSet<>(approved());images.addAll(jdbc.queryForList("SELECT identity_key AS image_id FROM content_asset WHERE asset_kind='CONNECTOR_IMAGE' AND (lifecycle<>'ACTIVE') ORDER BY updated_at DESC LIMIT 40",String.class));
            var items=new ArrayList<Map<String,Object>>();for(String image:images){var row=jdbc.queryForList("SELECT identity_key AS image_id,lifecycle AS state,revision AS revision,connector_cleanup_request AS cleanup_request,connector_cleanup_owner_user_id AS cleanup_owner_user_id,connector_runner_pool_id AS runner_pool_id,connector_archive_sha256 AS archive_sha256,connector_image_absent AS image_absent,updated_at AS updated_at,legacy_clock_json FROM content_asset WHERE asset_kind='CONNECTOR_IMAGE' AND (identity_key=?) ",image);var item=dto(image,row.isEmpty()?null:row.get(0));var counts=references(image);item.put("references",counts);
                var runtimeState=observed.get(image);item.put("present",runtimeState==null?null:runtimeState.get("present"));item.put("imageBytes",runtimeState==null?null:runtimeState.get("imageBytes"));
                item.put("canRequestCleanup",cleanupAllowed&&runtime.writesAllowed()&&approved().contains(image)&&!properties.getGatewayImage().equals(image)&&"ACTIVE".equals(item.get("state"))&&Boolean.TRUE.equals(item.get("present"))&&runtimeState!=null&&"ACTIVE".equals(runtimeState.get("runnerState"))&&clear(counts));items.add(item);
            }
            var result=new LinkedHashMap<String,Object>();result.put("supported",true);result.put("observationOnly",true);result.put("items",items);result.put("reclaimedBytesKnown",false);result.put("legalArchiveBytes",legalBytes);result.put("writesEnabled",runtime.writesAllowed());result.put("cleanupAllowed",cleanupAllowed);return result;
        });
    }
    public Map<String,Object> cleanup(AgentActor actor,String image,int expected,String request,boolean confirmed){
        var current=supervisor(actor);validate(image,request,expected,confirmed);String fingerprint=hash("CLEANUP:"+image+":"+expected);
        if(duplicate(current,request,fingerprint))return detail(current,image);
        runtime.requireWritesAllowed();
        if(!approved().contains(image)||properties.getGatewayImage().equals(image))throw fail(409,"仅可回收已登记且非当前的固定 Fetch 镜像");
        Map<String,Object> inventory;try{inventory=gateway.imageInventory(identity(current.userId()));}catch(Exception error){if(error instanceof InterruptedException)Thread.currentThread().interrupt();throw fail(503,"运行器协议与镜像尚无法核对 没有开始回收");}
        String pool=(String)inventory.get("poolId");
        if(!Boolean.TRUE.equals(inventory.get("cleanupAllowed")))throw fail(409,"当前环境不能删除共享宿主镜像 仅允许查询");
        if(!(inventory.get("items") instanceof List<?> images)||images.stream().noneMatch(item->item instanceof Map<?,?> value&&image.equals(value.get("image"))&&Boolean.TRUE.equals(value.get("present"))&&"ACTIVE".equals(value.get("state"))))throw fail(409,"运行器未确认此镜像可进入新的回收流程");
        boolean claimed=Boolean.TRUE.equals(tx.execute(status->{
            supervisor(current);var row=registry.lock(image);if(duplicate(current,request,fingerprint))return false;
            if(number(row,"revision")!=expected||!"ACTIVE".equals(row.get("state")))throw fail(409,"镜像状态已变化 请刷新");
            if(!clear(references(image)))throw fail(409,"仍有账号引用、安装或执行尚未核实 不能回收共享镜像");
            jdbc.update("UPDATE content_asset SET lifecycle='RETIRING',connector_cleanup_request=?,connector_cleanup_owner_user_id=?,connector_runner_pool_id=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE asset_kind='CONNECTOR_IMAGE' AND (identity_key=?) ",request,current.userId(),pool,image);
            command(current,request,image,fingerprint,"CLEANUP","PREPARING");audit(current,image,request,"IMAGE_RETIRE","STARTED");return true;
        }));
        if(!claimed)return detail(current,image);
        try{
            var prepared=gateway.imageControl(identity(current.userId()),image,"prepare",request,pool);
            if(!"PREPARED".equals(prepared.get("state")))throw new IllegalStateException("MCP_IMAGE_NOT_PREPARED");
            tx.executeWithoutResult(status->{supervisor(current);var row=registry.lock(image);if(!request.equals(row.get("cleanup_request"))||!clear(references(image)))throw fail(409,"镜像引用发生变化 保留封存与文件");
                jdbc.update("UPDATE content_asset SET lifecycle='DELETING',revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE asset_kind='CONNECTOR_IMAGE' AND (identity_key=?) ",image);
                jdbc.update("UPDATE workflow_instance SET status='DELETING',updated_at=UTC_TIMESTAMP(6) WHERE kind='MCP_IMAGE_COMMAND' AND (owner_user_id=? AND request_id=?) ",current.userId(),request);audit(current,image,request,"IMAGE_DELETE_APPROVAL","APPROVED");});
            var receipt=gateway.imageControl(identity(current.userId()),image,"delete",request,pool);finish(current,image,request,request,receipt);
        }catch(Exception error){if(error instanceof InterruptedException)Thread.currentThread().interrupt();unknown(current,image,request);}
        return detail(current,image);
    }
    public Map<String,Object> reconcile(AgentActor actor,String image,int expected,String request,boolean confirmed){
        var current=supervisor(actor);validate(image,request,expected,confirmed);String fingerprint=hash("RECONCILE:"+image+":"+expected);
        var claim=tx.execute(status->{
            supervisor(current);var row=registry.lock(image);if(duplicate(current,request,fingerprint))return null;
            if(number(row,"revision")!=expected||Set.of("ACTIVE","REMOVED").contains(row.get("state")))throw fail(409,"此镜像不需要或已经完成回收核对");
            if(!(row.get("cleanup_owner_user_id") instanceof Number)||row.get("cleanup_request")==null||row.get("runner_pool_id")==null)throw fail(409,"原回收身份不完整 保留待核对");
            command(current,request,image,fingerprint,"RECONCILE","OBSERVING");jdbc.update("UPDATE content_asset SET revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE asset_kind='CONNECTOR_IMAGE' AND (identity_key=?) ",image);audit(current,image,request,"IMAGE_RECONCILE","STARTED");return row;
        });
        if(claim==null)return detail(current,image);
        try{
            var receipt=gateway.imageControl(identity(((Number)claim.get("cleanup_owner_user_id")).longValue()),image,"receipt",(String)claim.get("cleanup_request"),(String)claim.get("runner_pool_id"));
            finish(current,image,(String)claim.get("cleanup_request"),request,receipt);
        }catch(Exception error){if(error instanceof InterruptedException)Thread.currentThread().interrupt();unknown(current,image,request);}
        return detail(current,image);
    }
    private void finish(AgentActor actor,String image,String original,String request,Map<String,Object> receipt){tx.executeWithoutResult(status->{
        supervisor(actor);var row=registry.lock(image);if(!original.equals(row.get("cleanup_request")))throw fail(409,"原镜像回收身份已变化");
        boolean removed="REMOVED".equals(receipt.get("state"))&&Boolean.TRUE.equals(receipt.get("imageAbsent"))&&receipt.get("archiveSha256") instanceof String digest&&digest.matches("[a-f0-9]{64}")&&clear(references(image));
        boolean alreadyRemoved="REMOVED".equals(row.get("state"));if(alreadyRemoved)removed=true;
        if(!alreadyRemoved)jdbc.update("UPDATE content_asset SET lifecycle=?,connector_archive_sha256=COALESCE(?,connector_archive_sha256),connector_image_absent=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE asset_kind='CONNECTOR_IMAGE' AND (identity_key=?) ",removed?"REMOVED":"NEEDS_REVIEW",receipt.get("archiveSha256"),removed,image);
        jdbc.update("UPDATE workflow_instance SET status=?,updated_at=UTC_TIMESTAMP(6) WHERE kind='MCP_IMAGE_COMMAND' AND (owner_user_id=? AND request_id=? AND mcp_action='CLEANUP') ",removed?"COMPLETED":"NEEDS_REVIEW",row.get("cleanup_owner_user_id"),original);
        jdbc.update("UPDATE workflow_instance SET status=?,updated_at=UTC_TIMESTAMP(6) WHERE kind='MCP_IMAGE_COMMAND' AND (owner_user_id=? AND request_id=?) ",removed?"COMPLETED":"NEEDS_REVIEW",actor.userId(),request);audit(actor,image,request,"IMAGE_RETIRE_RESULT",removed?"VERIFIED":"NEEDS_REVIEW");
    });}
    private void unknown(AgentActor actor,String image,String request){tx.executeWithoutResult(status->{
        var row=registry.lock(image);if(!"REMOVED".equals(row.get("state")))jdbc.update("UPDATE content_asset SET lifecycle='NEEDS_REVIEW',revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE asset_kind='CONNECTOR_IMAGE' AND (identity_key=?) ",image);
        boolean known="REMOVED".equals(row.get("state"));jdbc.update("UPDATE workflow_instance SET status=?,updated_at=UTC_TIMESTAMP(6) WHERE kind='MCP_IMAGE_COMMAND' AND (owner_user_id=? AND request_id=?) ",known?"COMPLETED":"NEEDS_REVIEW",actor.userId(),request);audit(actor,image,request,known?"IMAGE_RESULT_RECHECK":"IMAGE_RESULT_UNKNOWN",known?"VERIFIED":"NEEDS_REVIEW");
    });}
    private Map<String,Long> references(String image){
        var counts=new LinkedHashMap<String,Long>();
        for(var row:jdbc.queryForList("SELECT scope_key,legacy_clock_json FROM runtime_state WHERE namespace='MCP_RETENTION_CONTROL' AND owner_id=0 AND scope_key='1'"))
            if(row.get("legacy_clock_json")!=null)com.ruanzhu.doorhandle.common.time.LegacyClockEvidence.parse(row.get("legacy_clock_json").toString(),"agent_fetch_image_retention_control",Map.of("control_id",1));
        counts.put("unresolvedLegacyClocks",count("SELECT (SELECT COUNT(*) FROM runtime_state WHERE namespace='MCP_RETENTION_CONTROL' AND legacy_clock_json IS NOT NULL)+(SELECT COUNT(*) FROM content_link WHERE link_kind='CONNECTOR_RETENTION' AND target_id=? AND legacy_clock_json IS NOT NULL)+(SELECT COUNT(*) FROM content_asset WHERE asset_kind='CONNECTOR_IMAGE' AND identity_key=? AND legacy_clock_json IS NOT NULL)",image,image));
        counts.put("deploymentBaselineUnverified",count("SELECT CASE WHEN COUNT(*)=1 AND MAX(state_code)='ACTIVE' THEN 0 ELSE 1 END FROM runtime_state WHERE namespace='MCP_RETENTION_CONTROL' AND owner_id=0 AND (CAST(scope_key AS SIGNED)=1) "));
        counts.put("deploymentRetained",count("SELECT COUNT(*) FROM content_link WHERE link_kind='CONNECTOR_RETENTION' AND (target_id=? AND state='HELD') ",image));
        counts.put("registrations",count("SELECT COUNT(*) FROM agent_connector WHERE server_key='fetch' AND status IN ('INSTALLED','INSTALLING') AND JSON_UNQUOTE(JSON_EXTRACT(manifest_json,'$.image'))=?",image));
        counts.put("unknownRegistrations",count("SELECT COUNT(*) FROM agent_connector WHERE server_key='fetch' AND status IN ('INSTALLED','INSTALLING') AND (manifest_json IS NULL OR COALESCE(JSON_UNQUOTE(JSON_EXTRACT(manifest_json,'$.transport')),'') NOT IN ('STDIO','STREAMABLE_HTTP') OR (JSON_UNQUOTE(JSON_EXTRACT(manifest_json,'$.transport'))='STREAMABLE_HTTP' AND NOT COALESCE(REGEXP_LIKE(JSON_UNQUOTE(JSON_EXTRACT(manifest_json,'$.image')),'^sha256:[a-f0-9]{64}$','c'),FALSE)))"));
        counts.put("retainedOrUnverified",count("SELECT COUNT(*) FROM workflow_instance WHERE kind='MCP_INSTALLATION' AND (mcp_image_id=? AND status<>'REMOVED' AND (mcp_retained_for_rollback=TRUE OR mcp_writer_exit_verified=FALSE OR status='INSTALLING')) ",image));
        counts.put("unknownSnapshots",count("SELECT COUNT(*) FROM workflow_instance WHERE kind='MCP_INSTALLATION' AND (mcp_transport='STREAMABLE_HTTP' AND mcp_image_id IS NULL AND status<>'REMOVED' AND (mcp_retained_for_rollback=TRUE OR mcp_writer_exit_verified=FALSE OR status='INSTALLING')) "));
        counts.put("pendingExecutions",count("SELECT COUNT(*) FROM workflow_instance WHERE kind='MCP_EXECUTION' AND (status<>'REMOVED' AND (mcp_image_id=? OR (mcp_image_id IS NULL AND mcp_transport='STREAMABLE_HTTP'))) ",image));
        counts.put("pendingInstallations",count("SELECT COUNT(*) FROM workflow_instance WHERE kind='MCP_INSTALL_JOB' AND (status IN ('QUEUED','RUNNING')) "));return counts;
    }
    private long count(String sql,Object...args){Long value=jdbc.queryForObject(sql,Long.class,args);if(value==null||value<0)throw fail(503,"共享镜像引用无法核对");return value;}
    private static boolean clear(Map<String,Long> counts){return counts.values().stream().allMatch(value->value==0);}
    private Map<String,Object> detail(AgentActor actor,String image){supervisor(actor);var row=jdbc.queryForList("SELECT identity_key AS image_id,lifecycle AS state,revision AS revision,connector_cleanup_request AS cleanup_request,connector_cleanup_owner_user_id AS cleanup_owner_user_id,connector_runner_pool_id AS runner_pool_id,connector_archive_sha256 AS archive_sha256,connector_image_absent AS image_absent,updated_at AS updated_at,legacy_clock_json FROM content_asset WHERE asset_kind='CONNECTOR_IMAGE' AND (identity_key=?) ",image);return dto(image,row.isEmpty()?null:row.get(0));}
    private Map<String,Object> dto(String image,Map<String,Object> row){
        var result=new LinkedHashMap<String,Object>();if(row!=null&&row.get("legacy_clock_json")!=null){var clock=com.ruanzhu.doorhandle.common.time.LegacyClockEvidence.parse(row.get("legacy_clock_json").toString(),"agent_fetch_image",Map.of("image_id",image));result.put("clockStatus",clock.clockStatus());result.put("sourceWallTimes",clock.sourceWallTimes());}result.put("image",image);result.put("current",properties.getGatewayImage().equals(image));result.put("state",row==null?"ACTIVE":row.get("state"));result.put("revision",row==null?0:row.get("revision"));result.put("archiveSha256",row==null?null:row.get("archive_sha256"));result.put("imageAbsent",row!=null&&flag(row.get("image_absent")));result.put("updatedAt",row==null?null:row.get("updated_at"));result.put("reclaimedBytes",null);return result;
    }
    private boolean duplicate(AgentActor actor,String request,String fingerprint){var rows=jdbc.queryForList("SELECT request_sha256 FROM workflow_instance WHERE kind='MCP_IMAGE_COMMAND' AND (owner_user_id=? AND request_id=?) ",actor.userId(),request);if(rows.isEmpty())return false;if(!fingerprint.equals(rows.get(0).get("request_sha256")))throw fail(409,"请求编号已用于其他镜像操作");return true;}
    private void command(AgentActor actor,String request,String image,String fingerprint,String action,String state){jdbc.update("INSERT INTO workflow_instance(owner_user_id,request_id,resource_id,request_sha256,mcp_action,status,mcp_retention_protocol,workflow_id,kind,idempotency_scope,resource_type,payload_version,payload_json,revision,created_at,updated_at) SELECT v.owner_user_id,v.request_id,v.image_id,v.request_sha256,v.action_name,v.state,v.retention_protocol,UUID(),'MCP_IMAGE_COMMAND',CONCAT('MCP_IMAGE_COMMAND',':OWNER:',v.owner_user_id),'MCP_IMAGE_COMMAND',1,JSON_OBJECT('schemaVersion',1),0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6) FROM (SELECT ? AS owner_user_id,? AS request_id,? AS image_id,? AS request_sha256,? AS action_name,? AS state,4 AS retention_protocol) v",actor.userId(),request,image,fingerprint,action,state);}
    private void audit(AgentActor actor,String image,String request,String action,String outcome){
        String detail;try{detail=json.writeValueAsString(Map.of("image",image,"requestId",request,"reclaimedBytesKnown",false));}catch(Exception error){throw new IllegalStateException("MCP_IMAGE_AUDIT_ENCODING");}
        jdbc.update("INSERT INTO audit_event(event_id,owner_user_id,resource_id,action,outcome,revision,occurred_at,kind,resource_type,payload_version,payload_json) SELECT UUID(),v.owner_user_id,v.server_key,v.action_name,v.outcome,v.revision,v.created_at,'MCP','MCP_CONNECTOR',1,JSON_OBJECT('schemaVersion',1,'detailJson',CAST(v.detail_json AS CHAR)) FROM (SELECT ? AS owner_user_id,'fetch' AS server_key,? AS action_name,? AS outcome,0 AS revision,? AS detail_json,UTC_TIMESTAMP(6) AS created_at) v",actor.userId(),action,outcome,detail);
    }
    private static void validate(String image,String request,int revision,boolean confirmed){try{if(!confirmed||revision<0||image==null||!image.matches("sha256:[a-f0-9]{64}")||!UUID.fromString(request).toString().equals(request))throw new IllegalArgumentException();}catch(Exception error){throw fail(400,"请核对镜像摘要、版本、请求编号及确认项");}}
    private static String hash(String value){return FetchMcpRuntime.sha(value.getBytes(StandardCharsets.UTF_8));}
    private static int number(Map<String,Object> row,String key){return ((Number)row.get(key)).intValue();}
    private static boolean flag(Object value){return Boolean.TRUE.equals(value)||value instanceof Number n&&n.intValue()!=0;}
    private static ResponseStatusException fail(int status,String message){return new ResponseStatusException(HttpStatus.valueOf(status),message);}
}
