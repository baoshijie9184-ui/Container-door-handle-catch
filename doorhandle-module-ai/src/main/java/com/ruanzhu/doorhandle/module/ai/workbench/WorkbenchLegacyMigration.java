package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.*;
import com.ruanzhu.doorhandle.common.LocalDateTimeRow;
import com.ruanzhu.doorhandle.common.time.LegacyClockEvidence;
import com.ruanzhu.doorhandle.contracts.agent.AgentWorkbenchApi;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.math.BigDecimal;
import java.net.*;
import java.net.http.*;
import java.nio.file.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Explicit ECS-only, same-server copy of the three V37 workbench relations.
 * No bean, startup migration, source DML, compatibility view or automatic retry.
 */
public final class WorkbenchLegacyMigration {
    private static final List<String> TABLES=List.of("agent_workbench_audit","agent_workbench_item","agent_workbench_request");
    private static final Map<String,List<String>> FIELDS=Map.of(
        "agent_workbench_item",List.of("id","item_id","user_id","session_id","kind","status","revision","payload","created_at","updated_at"),
        "agent_workbench_request",List.of("id","user_id","request_id","request_sha256","result_json"),
        "agent_workbench_audit",List.of("id","user_id","session_id","item_id","action","revision","payload_sha256","created_at"));
    private static final DateTimeFormatter MICROS=DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS");
    public record Admission(String instanceId,String machineId,String sourceSchema,String targetSchema,
                            String serverUuid,ZoneOffset sourceOffset,Map<String,String> sourceCollations,
                            String sourceSnapshotSha256,Set<String> unresolvedDomains) {
        public Admission {sourceCollations=Map.copyOf(sourceCollations);unresolvedDomains=unresolvedDomains==null?Set.of():Set.copyOf(unresolvedDomains);}
        public Admission(String instanceId,String machineId,String sourceSchema,String targetSchema,String serverUuid,
                         ZoneOffset sourceOffset,Map<String,String> sourceCollations){
            this(instanceId,machineId,sourceSchema,targetSchema,serverUuid,sourceOffset,sourceCollations,null,Set.of());
        }
    }
    public record TableEvidence(int rowCount,String autoIncrement,String rowSha256,String columnsSha256,
                                String indexesSha256,String ddlSha256) {}
    public record Receipt(String status,String copyId,String sourceSchema,String targetSchema,String serverUuid,
                          String instanceId,String machineId,String sourceUtcOffset,Map<String,TableEvidence> sources,
                          String completeTargetSha256,int itemRows,int commandRows,int auditRows,int logicalTaskRows) {}
    public record OutcomeVerification(boolean matches,String copyId,String status) {}
    public static final class CommitOutcomeUnknown extends IllegalStateException {
        private final Receipt candidate;
        CommitOutcomeUnknown(Receipt candidate,RuntimeException cause){super("Workbench copy commit outcome is UNKNOWN; retain the candidate and verify existing target rows before any retry",cause);this.candidate=candidate;}
        public Receipt candidate(){return candidate;}
    }
    private record SourceShape(List<Map<String,Object>> columns,List<Map<String,Object>> indexes,String autoIncrement,String ddlSha256) {}
    private record ItemPlan(Map<String,Object> original,String workflowId,String type,long owner,String item,String session,String status,long revision,String body) {}
    private record CommandPlan(Map<String,Object> original,String workflowId,long owner,String request,String requestSha,String responseType,String body) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ObjectMapper json;
    private final WorkbenchProtocol protocol;
    private final Map<String,String> legacyClocks=new HashMap<>();
    public WorkbenchLegacyMigration(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper mapper){
        this.jdbc=jdbc;this.json=mapper.copy().findAndRegisterModules().enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
            .enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).disable(SerializationFeature.INDENT_OUTPUT);
        protocol=new WorkbenchProtocol(mapper);tx=new TransactionTemplate(manager);tx.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);tx.setTimeout(120);
    }
    /** The caller supplies reviewed identities, source collations and offset; nothing is inferred from a result row. */
    public Receipt copy(Admission admission){
        admit(admission);if(TransactionSynchronizationManager.isActualTransactionActive())throw new IllegalStateException("Workbench copy must own its explicit transaction");
        AtomicBoolean verified=new AtomicBoolean();var candidate=new java.util.concurrent.atomic.AtomicReference<Receipt>();
        try{return tx.execute(status->{Receipt result=copyLocked(admission);candidate.set(result);verified.set(true);return result;});}
        catch(RuntimeException error){if(verified.get())throw new CommitOutcomeUnknown(candidate.get(),error);throw error;}
    }
    /** Read-only post-commit/UNKNOWN check. A mismatch never triggers cleanup, copy, or a retry. */
    public OutcomeVerification verifyCommitted(Admission a,Receipt candidate){
        admit(a);check(candidate!=null&&a.sourceSchema().equals(candidate.sourceSchema())&&a.targetSchema().equals(candidate.targetSchema())&&a.serverUuid().equals(candidate.serverUuid())&&a.instanceId().equals(candidate.instanceId())&&a.machineId().equals(candidate.machineId())&&Objects.equals(offset(a),candidate.sourceUtcOffset()),"Outcome receipt belongs to another admission");
        if(TransactionSynchronizationManager.isActualTransactionActive())throw new IllegalStateException("Outcome verification owns its read-only transaction");
        var read=new TransactionTemplate(Objects.requireNonNull(tx.getTransactionManager()));read.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);read.setReadOnly(true);read.setTimeout(120);
        return read.execute(status->{
            var identity=jdbc.queryForMap("SELECT DATABASE() db,@@server_uuid uuid");check(a.targetSchema().equals(identity.get("db"))&&a.serverUuid().equals(identity.get("uuid")),"Outcome MySQL identity differs");
            for(String table:TABLES){var actual=shape(a,table);var rows=sourceRows(a,table,false);var expected=candidate.sources().get(table);
                if(expected==null||rows.size()!=expected.rowCount()||!Objects.equals(actual.autoIncrement(),expected.autoIncrement())||!WorkbenchStore.hash(encode(normalize(rows))).equals(expected.rowSha256())||!WorkbenchStore.hash(encode(normalize(actual.columns()))).equals(expected.columnsSha256())||!WorkbenchStore.hash(encode(normalize(actual.indexes()))).equals(expected.indexesSha256())||!actual.ddlSha256().equals(expected.ddlSha256()))return new OutcomeVerification(false,candidate.copyId(),"SOURCE_CHANGED_REVIEW_REQUIRED");
            }
            var target=new LinkedHashMap<String,Map<String,Map<String,Object>>>();for(String table:List.of("workflow_instance","audit_event"))target.put(table,targetRows(table,false));
            boolean matches=WorkbenchStore.hash(encode(normalize(target))).equals(candidate.completeTargetSha256());return new OutcomeVerification(matches,candidate.copyId(),matches?"COMMIT_VERIFIED":"TARGET_DIFFERS_REVIEW_REQUIRED");
        });
    }
    private Receipt copyLocked(Admission a){
        var identity=jdbc.queryForMap("SELECT DATABASE() db,@@server_uuid uuid,@@transaction_isolation isolation_level");
        check(a.targetSchema().equals(identity.get("db"))&&a.serverUuid().equals(identity.get("uuid")),"The explicit MySQL target identity differs");
        check("REPEATABLE-READ".equalsIgnoreCase(Objects.toString(identity.get("isolation_level"))),"Copy requires repeatable-read range locks");
        var grants=jdbc.queryForList("SELECT privilege_type FROM information_schema.schema_privileges WHERE table_schema=? AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))",String.class,a.sourceSchema());
        check(grants.containsAll(Set.of("SELECT","TRIGGER")),"Reviewed source SELECT and TRIGGER-metadata visibility grants are required");
        check(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type<>'BASE TABLE'",Integer.class)==0,"Compatibility views are not a compact target");
        int tables=jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",Integer.class);
        check(tables>0&&tables<=30,"Compact target exceeds the business table limit");
        check(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE LEFT(kind,10)='WORKBENCH_'",Long.class)==0&&jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='WORKBENCH'",Long.class)==0,"Workbench target is not empty; do not retry an UNKNOWN copy");
        var shapes=new LinkedHashMap<String,SourceShape>();var source=new LinkedHashMap<String,List<Map<String,Object>>>();
        // Full primary-key range locking reads include gaps at REPEATABLE READ. Source DDL is metadata-locked too.
        for(String table:TABLES){
            shapes.put(table,shape(a,table));String text=table.equals("agent_workbench_item")?"payload":table.equals("agent_workbench_request")?"result_json":null;
            var size=jdbc.queryForMap("SELECT COUNT(*) rows_count,"+(text==null?"0":"COALESCE(SUM(OCTET_LENGTH("+text+")),0)")+" text_bytes FROM "+qualified(a.sourceSchema(),table));
            check(((Number)size.get("rows_count")).longValue()<=50000&&((Number)size.get("text_bytes")).longValue()<=67108864,"Source exceeds this bounded migration batch; use an explicit streaming copy plan");
            var rows=sourceRows(a,table,true);
            check(rows.size()<=50000,"Source grew beyond the bounded migration batch");source.put(table,rows);
        }
        var items=source.get("agent_workbench_item").stream().map(row->item(row,a)).toList();
        var commands=source.get("agent_workbench_request").stream().map(this::command).toList();
        for(var row:source.get("agent_workbench_audit")){positive(row.get("user_id"));nonnegative(row.get("revision"));digest(row.get("payload_sha256"));utc(row.get("created_at"),a.sourceOffset());}
        var expected=new LinkedHashMap<String,Map<String,Map<String,Object>>>();
        for(String table:List.of("workflow_instance","audit_event"))expected.put(table,targetRows(table,true));
        Map<String,List<String>> columns=Map.of("workflow_instance",ordinary("workflow_instance"),"audit_event",ordinary("audit_event"));
        int logical=0;
        for(ItemPlan item:items){
            var values=empty(columns.get("workflow_instance"));values.putAll(map("workflow_id",item.workflowId(),"kind",WorkbenchProtocol.kind(item.type()).name(),"idempotency_scope","WORKBENCH_ITEM","request_id",item.item(),
                "request_sha256",WorkbenchStore.hash(encode(List.of(item.owner(),item.session(),item.item(),item.type()))),"owner_user_id",item.owner(),"resource_type","WORKBENCH_ITEM","resource_id",item.item(),"session_id",item.session(),
                "run_id",decode(item.original().get("payload")).get("runId"),"status",item.status(),"revision",item.revision(),"payload_version",1,"payload_json",item.body(),
                "created_at",utc(item.original().get("created_at"),a.sourceOffset()),"updated_at",utc(item.original().get("updated_at"),a.sourceOffset()),"legacy_source","agent_workbench_item","legacy_key",number(item.original().get("id")),"legacy_clock_json",clock(a,"agent_workbench_item",item.original())));
            String targetId=insert("workflow_instance",values);expected.get("workflow_instance").put(targetId,values);
            if(WorkbenchProtocol.execution(item.type())){
                var clock=clock(a,"agent_workbench_item",item.original());
                var evidence=clock==null?null:LegacyClockEvidence.parse(clock,"agent_workbench_item",Map.of("id",new java.math.BigInteger(number(item.original().get("id")))));
                var data=protocol.data(protocol.read(item.type(),1,item.body(),evidence));String task=Objects.toString(data.get("logicalTaskId"),null);
                check(task!=null&&!task.isBlank()&&task.codePointCount(0,task.length())<=128,"Source execution has no representable current logical task");
                Object version=data.get("modelConfigVersion");String logicalBody=protocol.write(new WorkbenchProtocol.LogicalTaskV1(item.item(),null,Objects.toString(data.get("role"),null),Objects.toString(data.get("modelId"),null),version instanceof Number n?n.longValue():null,Objects.toString(data.get("modelDefault"),null),true));
                var logicalValues=empty(columns.get("workflow_instance"));logicalValues.putAll(map("workflow_id",UUID.randomUUID().toString(),"kind","WORKBENCH_LOGICAL_TASK","idempotency_scope",WorkbenchStore.hash(encode(List.of(item.owner(),item.session(),item.item()))),
                    "request_id",task,"request_sha256",WorkbenchStore.hash(encode(List.of(item.owner(),item.session(),item.item(),task))),"owner_user_id",item.owner(),"parent_workflow_id",new BigDecimal(targetId),"resource_type","WORKBENCH_TASK","resource_id",task,"session_id",item.session(),
                    "run_id",data.get("runId"),"status",item.status(),"payload_version",1,"payload_json",logicalBody,"legacy_source","agent_workbench_logical_task","legacy_key",number(item.original().get("id")),"legacy_clock_json",clock));
                String logicalId=insert("workflow_instance",logicalValues);expected.get("workflow_instance").put(logicalId,logicalValues);logical++;
            }
        }
        for(CommandPlan command:commands){var values=empty(columns.get("workflow_instance"));values.putAll(map("workflow_id",command.workflowId(),"kind","WORKBENCH_COMMAND","idempotency_scope","OWNER:"+command.owner(),"request_id",command.request(),"request_sha256",command.requestSha(),"owner_user_id",command.owner(),
            "resource_type","WORKBENCH_COMMAND","resource_id",command.request(),"status","COMPLETED","payload_version",1,"payload_json",protocol.write(new WorkbenchProtocol.CommandV1(command.responseType())),"result_version",1,"result_json",command.body(),"result_sha256",WorkbenchStore.hash(command.body()),"legacy_source","agent_workbench_request","legacy_key",number(command.original().get("id"))));
            String id=insert("workflow_instance",values);expected.get("workflow_instance").put(id,values);}
        for(var row:source.get("agent_workbench_audit")){var values=empty(columns.get("audit_event"));String legacy=number(row.get("id"));values.putAll(map("event_id","wb-audit:"+legacy,"kind","WORKBENCH","owner_user_id",positive(row.get("user_id")),"resource_type","WORKBENCH_ITEM","resource_id",row.get("item_id"),"session_id",row.get("session_id"),"action",row.get("action"),"revision",nonnegative(row.get("revision")),
            "content_sha256",row.get("payload_sha256"),"occurred_at",utc(row.get("created_at"),a.sourceOffset()),"payload_version",1,"payload_json",protocol.write(new WorkbenchProtocol.AuditV1(null,null,legacy,originalTime(row.get("created_at")),offset(a))),"legacy_source","agent_workbench_audit","legacy_key",legacy,"legacy_clock_json",clock(a,"agent_workbench_audit",row)));
            String id=insert("audit_event",values);expected.get("audit_event").put(id,values);}
        for(String table:List.of("workflow_instance","audit_event"))check(equalRows(expected.get(table),targetRows(table,false)),"Final complete target-column verification failed: "+table);
        var evidence=new LinkedHashMap<String,TableEvidence>();
        for(String table:TABLES){var afterShape=shape(a,table);check(shapes.get(table).equals(afterShape),"Source metadata or AUTO_INCREMENT changed: "+table);
            var after=sourceRows(a,table,true);
            check(encode(normalize(source.get(table))).equals(encode(normalize(after))),"A source row changed during copy: "+table);
            var before=shapes.get(table);evidence.put(table,new TableEvidence(after.size(),before.autoIncrement(),WorkbenchStore.hash(encode(normalize(after))),WorkbenchStore.hash(encode(normalize(before.columns()))),WorkbenchStore.hash(encode(normalize(before.indexes()))),before.ddlSha256()));
        }
        return new Receipt("COPIED_VERIFIED_NOT_PRODUCTION_CUTOVER",UUID.randomUUID().toString(),a.sourceSchema(),a.targetSchema(),a.serverUuid(),a.instanceId(),a.machineId(),offset(a),Map.copyOf(evidence),WorkbenchStore.hash(encode(normalize(expected))),items.size(),commands.size(),source.get("agent_workbench_audit").size(),logical);
    }
    private ItemPlan item(Map<String,Object> row,Admission admission){
        long owner=positive(row.get("user_id")),revision=nonnegative(row.get("revision"));String type=(String)row.get("kind"),state=(String)row.get("status");protocol.state(type,state);
        var clock=clock(admission,"agent_workbench_item",row);
        var provenance=clock==null?null:LegacyClockEvidence.parse(clock,"agent_workbench_item",Map.of("id",new java.math.BigInteger(number(row.get("id")))));
        String raw=(String)row.get("payload");var data=decode(raw);var evidence=new WorkbenchProtocol.LegacyItemV1(raw,provenance==null?originalTime(row.get("created_at")):provenance.sourceWallTimes().get("created_at"),provenance==null?originalTime(row.get("updated_at")):provenance.sourceWallTimes().get("updated_at"),offset(admission));
        utc(row.get("created_at"),admission.sourceOffset());utc(row.get("updated_at"),admission.sourceOffset());
        return new ItemPlan(row,"wb-item:"+number(row.get("id")),type,owner,(String)row.get("item_id"),(String)row.get("session_id"),state,revision,protocol.write(protocol.payload(type,data,evidence,clock!=null)));
    }
    private CommandPlan command(Map<String,Object> row){
        long owner=positive(row.get("user_id"));String raw=(String)row.get("result_json"),type;
        try{var tree=json.readTree(raw);check(tree!=null&&tree.isObject(),"Command result must be a known object");var names=new HashSet<String>();tree.fieldNames().forEachRemaining(names::add);
            if(names.equals(Set.of("modelId","revision"))){check(tree.get("modelId").isTextual()&&tree.get("revision").isIntegralNumber(),"Invalid model selection result");type="MODEL_SELECTION";}
            else {check(Set.of("id","kind","status","revision","data","updatedAt").containsAll(names)&&names.containsAll(Set.of("id","kind","status","revision","data")),"Unsupported command result shape");
                check(tree.get("id").isTextual()&&tree.get("kind").isTextual()&&tree.get("status").isTextual()&&tree.get("revision").isIntegralNumber()&&tree.get("data").isObject(),"Invalid item command result");
                String kind=tree.get("kind").textValue();protocol.state(kind,tree.get("status").textValue());protocol.payload(kind,decode(tree.get("data").toString()),null);type="ITEM";}
        }catch(java.io.IOException error){throw new IllegalArgumentException("Legacy command result is not readable",error);}
        return new CommandPlan(row,"wb-command:"+number(row.get("id")),owner,(String)row.get("request_id"),digest(row.get("request_sha256")),type,protocol.write(new WorkbenchProtocol.CommandResultV1(type,raw)));
    }
    static <T> T withFreshStatistics(JdbcTemplate source, java.util.function.Function<JdbcTemplate,T> observer){
        return source.execute((ConnectionCallback<T>)connection->{
            try(var statement=connection.createStatement()){
                statement.execute("SET SESSION information_schema_stats_expiry=0");
                try(var rows=statement.executeQuery("SELECT @@SESSION.information_schema_stats_expiry")){
                    check(rows.next(),"The metadata session freshness readback is missing");
                    long expiry=rows.getLong(1);boolean missing=rows.wasNull();
                    check(!missing&&expiry==0&&!rows.next(),"Metadata must read uncached engine statistics in the same session");
                }
            }
            // Keep both transactional and standalone metadata observations on
            // the exact connection whose session setting was just verified.
            var scoped=new JdbcTemplate(new SingleConnectionDataSource(connection,true));
            scoped.setQueryTimeout(source.getQueryTimeout());
            return observer.apply(scoped);
        });
    }
    private SourceShape shape(Admission a,String table){
        return withFreshStatistics(jdbc,scoped->shape(scoped,a,table));
    }
    private SourceShape shape(JdbcTemplate jdbc,Admission a,String table){
        var tableInfo=jdbc.queryForMap("SELECT table_type,engine,table_collation,auto_increment FROM information_schema.tables WHERE table_schema=? AND table_name=?",a.sourceSchema(),table);
        check("BASE TABLE".equals(tableInfo.get("table_type"))&&"InnoDB".equals(tableInfo.get("engine"))&&a.sourceCollations().get(table).equals(tableInfo.get("table_collation")),"Unreviewed source table engine or collation: "+table);
        var columns=jdbc.queryForList("SELECT column_name,column_type,is_nullable,column_default,extra,character_set_name,collation_name,datetime_precision FROM information_schema.columns WHERE table_schema=? AND table_name=? ORDER BY ordinal_position",a.sourceSchema(),table);
        check(columns.stream().map(c->(String)c.get("column_name")).toList().equals(FIELDS.get(table)),"The complete original source column list differs: "+table);
        for(var column:columns){String name=(String)column.get("column_name"),type=(String)column.get("column_type");check("NO".equals(column.get("is_nullable")),"Unexpected nullable source column");
            String expected=switch(name){case "id"->"bigint unsigned";case "user_id","revision"->"bigint";case "item_id"->"varchar(64)";case "session_id","request_id"->"varchar(128)";case "kind"->"varchar(32)";case "status"->"varchar(40)";case "payload","result_json"->"longtext";case "created_at","updated_at"->"datetime(6)";case "action"->"varchar(48)";case "request_sha256","payload_sha256"->"char(64)";default->throw new IllegalArgumentException("Unexpected column");};
            check(expected.equalsIgnoreCase(type),"Source column type differs: "+table+"."+name);
            Object defaultValue=column.get("column_default");
            if(name.equals("revision")&&table.equals("agent_workbench_item"))check("0".equals(Objects.toString(defaultValue)),"Source revision default differs");
            else if(Set.of("created_at","updated_at").contains(name))check("current_timestamp(6)".equalsIgnoreCase(Objects.toString(defaultValue)),"Source time default differs");
            else check(defaultValue==null,"Source column gained an unreviewed default");
            if(Set.of("item_id","session_id","request_id").contains(name))check("utf8mb4_bin".equals(column.get("collation_name")),"Source identity collation differs");
            if(type.toLowerCase(Locale.ROOT).startsWith("varchar")||type.toLowerCase(Locale.ROOT).startsWith("char")||type.equalsIgnoreCase("longtext"))check("utf8mb4".equals(column.get("character_set_name")),"Source text charset differs");
            check(name.equals("id")?"auto_increment".equalsIgnoreCase(Objects.toString(column.get("extra"))):Objects.toString(column.get("extra"),"").isBlank()||Objects.toString(column.get("extra")).equalsIgnoreCase("DEFAULT_GENERATED"),"Unexpected generated source column");
        }
        var indexes=jdbc.queryForList("SELECT index_name,non_unique,seq_in_index,column_name,sub_part FROM information_schema.statistics WHERE table_schema=? AND table_name=? ORDER BY index_name,seq_in_index",a.sourceSchema(),table);
        var unique=new TreeMap<String,List<String>>();for(var key:indexes)if(((Number)key.get("non_unique")).intValue()==0){check(key.get("sub_part")==null,"Prefix unique source keys are unsupported");unique.computeIfAbsent((String)key.get("index_name"),ignored->new ArrayList<>()).add((String)key.get("column_name"));}
        var expectedKeys=new ArrayList<List<String>>();expectedKeys.add(List.of("id"));if(table.equals("agent_workbench_item"))expectedKeys.add(List.of("item_id"));if(table.equals("agent_workbench_request"))expectedKeys.add(List.of("user_id","request_id"));
        check(unique.size()==expectedKeys.size()&&new HashSet<>(unique.values()).equals(new HashSet<>(expectedKeys)),"Source unique-key semantics differ");
        check(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema=? AND table_name=? AND constraint_type IN ('FOREIGN KEY','CHECK')",Integer.class,a.sourceSchema(),table)==0,"Unreviewed source foreign/check constraints");
        check(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=? AND event_object_table=?",Integer.class,a.sourceSchema(),table)==0,"Unreviewed source trigger");
        var create=jdbc.queryForMap("SHOW CREATE TABLE "+qualified(a.sourceSchema(),table));String ddl=Objects.toString(create.get("Create Table"),null);check(ddl!=null,"SHOW CREATE TABLE was not visible");
        return new SourceShape(columns,indexes,tableInfo.get("auto_increment")==null?null:number(tableInfo.get("auto_increment")),WorkbenchStore.hash(ddl));
    }
    private List<String> ordinary(String table){return jdbc.queryForList("SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=? AND generation_expression='' ORDER BY ordinal_position",String.class,table);}
    private List<Map<String,Object>> sourceRows(Admission a,String table,boolean lock){
        var columns=FIELDS.get(table);boolean unresolved=a.sourceOffset()==null&&!table.equals("agent_workbench_request");
        var times=columns.stream().filter(name->name.endsWith("_at")).toList();
        String extras="";
        if(unresolved){
            var pairs=new ArrayList<String>();for(String name:columns){pairs.add("'"+name+"'");pairs.add(times.contains(name)?"CAST(`"+name+"` AS CHAR CHARACTER SET utf8mb4)":"`"+name+"`");}
            extras=",SHA2(CAST(JSON_OBJECT("+String.join(",",pairs)+") AS CHAR CHARACTER SET utf8mb4),256) AS __clock_row_sha";
            for(String name:times)extras+=",CAST(`"+name+"` AS CHAR CHARACTER SET utf8mb4) AS __clock_"+name;
        }
        return jdbc.query("SELECT "+String.join(",",columns)+extras+" FROM "+qualified(a.sourceSchema(),table)+(lock?" FORCE INDEX(PRIMARY)":"")+" ORDER BY id"+(lock?" FOR SHARE":""),(rs,n)->{
            Map<String,Object> row=new LinkedHashMap<>(LocalDateTimeRow.read(rs,n));
            if(unresolved){
                var wall=new LinkedHashMap<String,Object>();for(String name:times)wall.put(name,row.remove("__clock_"+name));
                String body=encode(map("protocol",LegacyClockEvidence.PROTOCOL,"status",LegacyClockEvidence.UNRESOLVED,
                    "sourceTable",table,"sourceKey",Map.of("id",new java.math.BigInteger(number(row.get("id")))),
                    "sourceSnapshotSha256",a.sourceSnapshotSha256(),"sourceRowSha256",row.remove("__clock_row_sha"),"sourceWallTimes",wall));
                LegacyClockEvidence.parse(body,table,Map.of("id",new java.math.BigInteger(number(row.get("id")))));
                legacyClocks.put(table+":"+number(row.get("id")),body);
            }
            return row;
        });
    }
    private String clock(Admission a,String table,Map<String,Object> row){
        if(a.sourceOffset()!=null||table.equals("agent_workbench_request"))return null;
        String value=legacyClocks.get(table+":"+number(row.get("id")));check(value!=null,"Original SQL wall-clock evidence is missing");return value;
    }
    private Map<String,Object> empty(List<String> columns){var result=new LinkedHashMap<String,Object>();for(String column:columns)result.put(column,null);if(columns.contains("fence"))result.put("fence",0);if(columns.contains("attempts"))result.put("attempts",0);if(columns.contains("revision"))result.put("revision",0);return result;}
    private Map<String,Map<String,Object>> targetRows(String table,boolean lock){var result=new LinkedHashMap<String,Map<String,Object>>();String columns=String.join(",",ordinary(table));for(var row:jdbc.query("SELECT "+columns+" FROM `"+table+"` ORDER BY id"+(lock?" FOR UPDATE":""),LocalDateTimeRow::read))result.put(number(row.get("id")),row);return result;}
    private String insert(String table,Map<String,Object> expected){var names=expected.keySet().stream().filter(n->!n.equals("id")).toList();String sql="INSERT INTO `"+table+"`("+String.join(",",names)+") VALUES("+String.join(",",Collections.nCopies(names.size(),"?"))+")";jdbc.update(sql,names.stream().map(expected::get).toArray());
        String key=table.equals("workflow_instance")?"workflow_id":"event_id";String id=number(jdbc.queryForObject("SELECT id FROM `"+table+"` WHERE "+key+"=?",Object.class,expected.get(key)));expected.put("id",new BigDecimal(id));return id;}
    private boolean equalRows(Object expected,Object actual){return encode(normalize(expected)).equals(encode(normalize(actual)));}
    private Object normalize(Object value){if(value instanceof Number n)return new BigDecimal(n.toString()).stripTrailingZeros().toPlainString();if(value instanceof LocalDateTime date)return MICROS.format(date);if(value instanceof Map<?,?> map){var result=new TreeMap<String,Object>();map.forEach((k,v)->result.put(k.toString(),normalize("legacy_clock_json".equals(k)&&v instanceof String text?decode(text):v)));return result;}if(value instanceof Collection<?> list)return list.stream().map(this::normalize).toList();return value;}
    private String encode(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalArgumentException("Migration evidence cannot be encoded",error);}}
    private Map<String,Object> decode(Object raw){try{return json.readValue((String)raw,new TypeReference<LinkedHashMap<String,Object>>(){});}catch(Exception error){throw new IllegalArgumentException("Legacy payload is not a supported JSON object",error);}}
    private static Map<String,Object> map(Object... pairs){var result=new LinkedHashMap<String,Object>();for(int n=0;n<pairs.length;n+=2)result.put((String)pairs[n],pairs[n+1]);return result;}
    private static String number(Object value){return new BigDecimal(value.toString()).toBigIntegerExact().toString();}
    private static long positive(Object value){long result=new BigDecimal(value.toString()).longValueExact();check(result>0,"Source owner cannot be represented without inventing an identity");return result;}
    private static long nonnegative(Object value){long result=new BigDecimal(value.toString()).longValueExact();check(result>=0,"Negative source revision is unsupported");return result;}
    private static String digest(Object value){String result=(String)value;check(result!=null&&result.matches("[a-f0-9]{64}"),"Source digest cannot be represented unchanged");return result;}
    private static String originalTime(Object value){check(value instanceof LocalDateTime,"Source wall-clock time is not representable");return MICROS.format((LocalDateTime)value);}
    private static LocalDateTime utc(Object value,ZoneOffset offset){originalTime(value);LocalDateTime original=(LocalDateTime)value;check(original.getNano()%1000==0,"Source microsecond precision differs");if(offset==null)return null;var result=original.minusSeconds(offset.getTotalSeconds());check(result.getYear()>=1000&&result.getYear()<=9999,"Source offset conversion is outside MySQL DATETIME");return result;}
    private static String offset(Admission a){return a.sourceOffset()==null?null:a.sourceOffset().getId();}
    private static String qualified(String schema,String table){check(schema!=null&&schema.matches("[A-Za-z0-9_]{1,64}")&&TABLES.contains(table),"Explicit source identifiers required");return "`"+schema+"`.`"+table+"`";}
    private static void check(boolean value,String message){if(!value)throw new IllegalStateException(message);}
    private static void admit(Admission a){
        check(a!=null&&"Linux".equals(System.getProperty("os.name")),"Workbench migration executes only on ECS");
        check(a.instanceId()!=null&&a.instanceId().matches("i-[a-z0-9]+")&&a.machineId()!=null&&a.machineId().matches("[a-f0-9]{32}"),"Explicit ECS identities are required");
        check(a.sourceOffset()!=null?a.unresolvedDomains().isEmpty()&&a.sourceSnapshotSha256()==null:a.unresolvedDomains().contains("workbench")&&a.sourceSnapshotSha256()!=null&&a.sourceSnapshotSha256().matches("[a-f0-9]{64}"),"Reviewed offset or explicit unresolved clock policy and snapshot required");
        check(a.sourceSchema()!=null&&a.sourceSchema().matches("[A-Za-z0-9_]{1,64}")&&a.targetSchema()!=null&&a.targetSchema().matches("[A-Za-z0-9_]{1,64}")&&!a.sourceSchema().equalsIgnoreCase(a.targetSchema()),"Distinct explicit source and target schemas required");
        check(a.serverUuid()!=null&&a.serverUuid().matches("[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")&&a.sourceCollations().keySet().equals(Set.copyOf(TABLES))&&a.sourceCollations().values().stream().allMatch(v->v.matches("utf8mb4_[a-z0-9_]+")),"Reviewed server UUID and all three source collations are required");
        check(a.instanceId().equals(System.getenv("DOORHANDLE_ECS_INSTANCE_ID"))&&a.machineId().equals(System.getenv("DOORHANDLE_ECS_MACHINE_ID")),"Migration admission differs from the ECS execution contract");
        try{
            check(a.machineId().equals(Files.readString(Path.of("/etc/machine-id")).strip()),"Actual machine identity differs");
            ProxySelector direct=new ProxySelector(){public List<Proxy> select(URI uri){return List.of(Proxy.NO_PROXY);}public void connectFailed(URI uri,SocketAddress address,java.io.IOException error){}};
            var client=HttpClient.newBuilder().proxy(direct).followRedirects(HttpClient.Redirect.NEVER).connectTimeout(Duration.ofSeconds(4)).build();
            var token=client.send(HttpRequest.newBuilder(URI.create("http://100.100.100.200/latest/api/token")).timeout(Duration.ofSeconds(4)).header("X-aliyun-ecs-metadata-token-ttl-seconds","60").PUT(HttpRequest.BodyPublishers.noBody()).build(),HttpResponse.BodyHandlers.ofString());
            check(token.statusCode()==200&&!token.body().isBlank()&&token.body().length()<=4096,"ECS IMDSv2 token was not available");
            var instance=client.send(HttpRequest.newBuilder(URI.create("http://100.100.100.200/latest/meta-data/instance-id")).timeout(Duration.ofSeconds(4)).header("X-aliyun-ecs-metadata-token",token.body()).GET().build(),HttpResponse.BodyHandlers.ofString());
            check(instance.statusCode()==200&&a.instanceId().equals(instance.body().strip()),"Actual ECS instance differs");
        }catch(InterruptedException error){Thread.currentThread().interrupt();throw new IllegalStateException("ECS admission interrupted",error);}catch(java.io.IOException error){throw new IllegalStateException("ECS admission could not be verified",error);}
    }
}
