package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.support.DualSchemaCopyMySqlFixture;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.sql.Connection;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import static org.assertj.core.api.Assertions.*;

/** Actual V65 five-table source, current complete target, and real digest business reader; ECS only. */
@EnabledIfSystemProperty(named="doorhandle.digest.copy.source.config",matches=".+")
class DigestCopyMigrationMySqlTest {
    private static final Set<String> SOURCES=Set.of("quality_digest_control","quality_digest_schedule","quality_digest_run",
            "quality_digest_audit","quality_digest_command");
    private static final String SNAPSHOT="{\"statusGroups\":[],\"reportDate\":\"2026-02-03\",\"basis\":\"测试快照\"}";
    private final ObjectMapper json=new ObjectMapper().findAndRegisterModules().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
    private DualSchemaCopyMySqlFixture fixture;
    private JdbcTemplate source,target;
    private String snapshotSha;

    @BeforeEach void setup() throws Exception {
        var targetTables=new HashSet<String>();
        json.readTree(Path.of("../docs/database/compact-schema-contract.json").toFile()).path("expectedTargetTables")
                .forEach(value->targetTables.add(value.asText()));
        assertThat(targetTables).hasSize(29);
        fixture=new DualSchemaCopyMySqlFixture(System.getProperty("doorhandle.digest.copy.source.config"),
                System.getProperty("doorhandle.digest.copy.mysql.config"),"doorhandle_detection_verify_",SOURCES,targetTables);
        source=fixture.source();target=fixture.target();
        fixture.executeSource(Files.readString(Path.of("../sql/mysql/migration-V65-quality-digests.sql")));
        for(String name:List.of("10-core.sql","20-content.sql","25-agent.sql","30-operations.sql","35-runtime-guards.sql",
                "36-identity-guards.sql","37-audit-guards.sql","38-quota-guards.sql","39-workflow-guards.sql","40-relations.sql")) {
            byte[] sql=Files.readAllBytes(Path.of("../sql/mysql/compact/baseline",name));
            try(var connection=fixture.targetDataSource().getConnection()) {
                ScriptUtils.executeSqlScript(connection,new EncodedResource(new ByteArrayResource(sql),StandardCharsets.UTF_8),
                        false,false,ScriptUtils.DEFAULT_COMMENT_PREFIX,name.endsWith("-guards.sql")?"$$":";",
                        ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
            }
        }
        com.ruanzhu.doorhandle.module.detection.support.FixtureSourceSnapshot.installLegacyClockGuards(target,Path.of("../sql/mysql/compact/baseline"));
        snapshotSha=sha(json.writeValueAsString(json.readValue(SNAPSHOT,Object.class)));
        source.update("INSERT INTO quality_digest_schedule VALUES(41,'Plan-A',3,'主管','质量日报','0 0 8 * * *',FALSE,7,NULL,'2026-02-03 04:05:06.123456','2026-02-04 05:06:07.654321')");
        source.update("INSERT INTO quality_digest_run VALUES(71,'Run-Café','Plan-A',3,'manual-Ä','2026-02-03 04:05:06.123456','2026-02-03','COMPLETED','retained-old-token','2026-02-03 04:10:06.123456',?,?,'retained-old-code','2026-02-03 04:05:06.123456','2026-02-03 04:06:07.654321')",SNAPSHOT,snapshotSha);
        source.update("INSERT INTO quality_digest_run VALUES(72,'active-run','Plan-A',3,'active-slot','2026-02-03 04:05:06.123456','2026-02-03','RUNNING','active-token','2099-02-03 04:10:06.123456',NULL,NULL,NULL,'2026-02-03 04:05:06.123456',NULL)");
        source.update("INSERT INTO quality_digest_audit VALUES(81,'Plan-A',3,'DOWNLOAD',7,?,'2026-02-03 04:07:08.234567')",
                "{\"unknownOriginalField\":\"保留全部原文\",\"format\":\"md\",\"snapshotSha256\":\""+snapshotSha+"\",\"runId\":null}");
        source.update("INSERT INTO quality_digest_command VALUES(3,'Save-Ä',?,'Plan-A','2026-02-03 04:05:06.123456')","e".repeat(64));
        // Deleted historical ids must survive as sequence high-water marks.
        source.execute("ALTER TABLE quality_digest_schedule AUTO_INCREMENT=9001");
        source.execute("ALTER TABLE quality_digest_run AUTO_INCREMENT=9007199254740993");
        source.execute("ALTER TABLE quality_digest_audit AUTO_INCREMENT=9101");
    }
    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}
    private static String sha(String value)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}

    private void copy() throws Exception {
        String sql=Files.readString(Path.of("../sql/mysql/compact/copy/49-digests.sql"))
                .replace("__SOURCE_SCHEMA__",fixture.sourceName()).replace("__SOURCE_DIGEST_OFFSET__","+00:00");
        for(String table:SOURCES) {
            String collation=source.queryForObject("SELECT table_collation FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=?",String.class,table);
            if(collation==null||!collation.matches("utf8mb4_[a-z0-9_]+"))throw new SecurityException("Unreviewed digest source collation");
            sql=sql.replace("__SOURCE_DIGEST_COLLATION_"+table+"__",collation);
        }
        try(Connection frozen=source.getDataSource().getConnection();var lock=frozen.createStatement()) {
            lock.execute("LOCK TABLES "+String.join(",",SOURCES.stream().sorted().map(table->"`"+table+"` READ").toList()));
            try {fixture.executeTarget(sql);}
            catch(Exception error) {
                try {error.addSuppressed(new IllegalStateException("Digest source CHECK metadata: "+source.queryForList(
                        "SELECT t.table_name,t.constraint_name,t.enforced,c.check_clause,HEX(c.check_clause) check_hex FROM information_schema.table_constraints t JOIN information_schema.check_constraints c ON t.constraint_schema=c.constraint_schema AND t.constraint_name=c.constraint_name WHERE t.constraint_schema=DATABASE() AND t.table_name IN ('quality_digest_control','quality_digest_run') AND t.constraint_type='CHECK' ORDER BY t.table_name,t.constraint_name")));}
                catch(Exception metadataError) {error.addSuppressed(metadataError);}
                throw error;
            } finally {lock.execute("UNLOCK TABLES");}
        }
    }

    @Test void preservesRawFieldsNullMicrosecondsClaimAndHighWaterWithTypedPayloads() throws Exception {
        String rawSnapshot=source.queryForObject("SELECT CAST(snapshot_json AS CHAR) FROM quality_digest_run WHERE id=71",String.class);
        String rawAudit=source.queryForObject("SELECT CAST(detail_json AS CHAR) FROM quality_digest_audit",String.class);
        copy();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",Integer.class)).isEqualTo(29);
        assertThat(target.queryForObject("SELECT result_json FROM workflow_instance WHERE workflow_id='Run-Café'",String.class)).isEqualTo(rawSnapshot);
        assertThat(target.queryForObject("SELECT result_sha256 FROM workflow_instance WHERE workflow_id='Run-Café'",String.class)).isEqualTo(snapshotSha);
        assertThat(target.queryForObject("SELECT JSON_LENGTH(digest_legacy_row_json) FROM workflow_instance WHERE workflow_id='Run-Café'",Integer.class)).isEqualTo(15);
        assertThat(target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(digest_legacy_row_json,'$.claim_token')) FROM workflow_instance WHERE workflow_id='Run-Café'",String.class)).isEqualTo("retained-old-token");
        assertThat(target.queryForObject("SELECT claim_token FROM workflow_instance WHERE workflow_id='Run-Café'",String.class)).isNull();
        assertThat(target.queryForObject("SELECT claim_token FROM workflow_instance WHERE workflow_id='active-run'",String.class)).isEqualTo("active-token");
        assertThat(target.queryForObject("SELECT CAST(scheduled_for AS CHAR) FROM workflow_instance WHERE workflow_id='Run-Café'",String.class)).isEqualTo("2026-02-03 04:05:06.123456");
        assertThat(target.queryForObject("SELECT updated_at FROM workflow_instance WHERE workflow_id='Run-Café'",String.class)).isNull();
        assertThat(target.queryForObject("SELECT finished_at FROM workflow_instance WHERE kind='DIGEST_COMMAND'",String.class)).isNull();
        assertThat(target.queryForObject("SELECT digest_legacy_detail_json FROM audit_event WHERE kind='DIGEST'",String.class)).isEqualTo(rawAudit);
        assertThat(target.queryForObject("SELECT run_id FROM audit_event WHERE kind='DIGEST'",String.class)).isNull();
        assertThat(target.queryForObject("SELECT request_sha256 FROM workflow_instance WHERE kind='DIGEST_COMMAND'",String.class)).isEqualTo("e".repeat(64));
        assertThat(target.queryForObject("SELECT request_sha256 FROM workflow_instance WHERE workflow_id='Run-Café'",String.class)).isEqualTo(sha(json.writeValueAsString(List.of("Plan-A","manual-Ä","2026-02-03"))));
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='DIGEST_COMMAND' AND digest_scope='owner:3' AND digest_request_id='save-a'",Integer.class)).isEqualTo(1);
        assertThat(target.queryForObject("SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='scheduled_plan'",Long.class)).isEqualTo(9001L);
        assertThat(target.queryForObject("SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='workflow_instance'",Long.class)).isGreaterThan(9007199254740993L);
        assertThat(source.queryForObject("SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='quality_digest_run'",Long.class)).isEqualTo(9007199254740993L);
    }

    @Test void importedCompletedSnapshotDownloadsThroughRealCaseInsensitiveBusinessReader() throws Exception {
        copy();
        BusinessUserDirectory users=new BusinessUserDirectory(){
            public Identity authenticated(){return new Identity(3,"主管",true);}
            public Identity current(long id,String username){return new Identity(id,username,true);}
            public Identity lockCurrent(long id,String username){return current(id,username);}
        };
        var service=new QualityDigestService(target,users,json,new DataSourceTransactionManager(fixture.targetDataSource()),new ReportDocumentRenderer(),"UTC");
        assertThat(service.runs("plan-a")).hasSize(2);
        assertThat(new String(service.download("RUN-cafe","md").bytes(),StandardCharsets.UTF_8)).contains("2026-02-03","测试快照",snapshotSha);
        assertThat(source.queryForObject("SELECT COUNT(*) FROM quality_digest_audit",Integer.class)).isEqualTo(1);
    }

    @Test void importedCommandIdsFitTheWorkflowContractAndReplayFullCompositeKeys() throws Exception {
        String first="r".repeat(63)+"A",second="r".repeat(63)+"B";
        var firstRequest=new QualityDigestService.Save("质量日报","0 0 8 * * *",false,0,first);
        var secondRequest=new QualityDigestService.Save("质量日报","0 0 8 * * *",false,0,second);
        String firstDigest=sha("\n"+json.writeValueAsString(firstRequest));
        source.update("INSERT INTO quality_digest_schedule VALUES(42,'Plan-B',4,'主管2','质量日报','0 0 8 * * *',FALSE,7,NULL,'2026-02-03 04:05:06.123456','2026-02-04 05:06:07.654321')");
        source.update("INSERT INTO quality_digest_command VALUES(3,?,?,'Plan-A','2026-02-03 04:05:06.123456')",first,firstDigest);
        source.update("INSERT INTO quality_digest_command VALUES(4,?,?,'Plan-B','2026-02-03 04:05:06.123456')",first,firstDigest);
        source.update("INSERT INTO quality_digest_command VALUES(3,?,?,'Plan-A','2026-02-03 04:05:06.123456')",second,sha("\n"+json.writeValueAsString(secondRequest)));
        source.update("INSERT INTO quality_digest_command VALUES(3,?,?,'Plan-A','2026-02-03 04:05:06.123456')","项".repeat(64),"f".repeat(64));
        String sourceRows="SELECT actor_user_id,request_id,request_sha256,schedule_id,CAST(created_at AS CHAR) created_text,CAST(JSON_ARRAY(actor_user_id,request_id) AS CHAR CHARACTER SET utf8mb4) source_key FROM quality_digest_command ORDER BY actor_user_id,request_id";
        var before=source.queryForList(sourceRows);
        copy();
        var identifiers=new HashSet<String>();
        for(var original:before) {
            var command=target.queryForMap("SELECT workflow_id,request_id,request_sha256,legacy_key,digest_legacy_row_json,CAST(created_at AS CHAR) created_text,updated_at,finished_at FROM workflow_instance WHERE kind='DIGEST_COMMAND' AND BINARY legacy_key=BINARY ?",original.get("source_key"));
            String id=command.get("workflow_id").toString();
            assertThat(id).matches("[a-f0-9]{64}").isEqualTo(sha("DIGEST_COMMAND:"+original.get("source_key")));
            assertThat(identifiers.add(id)).isTrue();
            assertThat(command.get("request_id")).isEqualTo(original.get("request_id"));
            assertThat(command.get("request_sha256")).isEqualTo(original.get("request_sha256"));
            assertThat(command.get("created_text")).isEqualTo(original.get("created_text"));
            assertThat(command.get("updated_at")).isNull();assertThat(command.get("finished_at")).isNull();
            var raw=json.readTree(command.get("digest_legacy_row_json").toString());
            assertThat(raw.path("actor_user_id").asLong()).isEqualTo(((Number)original.get("actor_user_id")).longValue());
            assertThat(raw.path("request_id").asText()).isEqualTo(original.get("request_id"));
        }
        assertThat(identifiers).hasSize(5);
        var actor=new java.util.concurrent.atomic.AtomicLong(3);
        BusinessUserDirectory users=new BusinessUserDirectory(){
            public Identity authenticated(){return current(actor.get(),"主管");}
            public Identity current(long id,String username){return new Identity(id,id==3?"主管":"主管2",true);}
            public Identity lockCurrent(long id,String username){return current(id,username);}
        };
        var service=new QualityDigestService(target,users,json,new DataSourceTransactionManager(fixture.targetDataSource()),new ReportDocumentRenderer(),"UTC");
        assertThat(service.save(null,firstRequest).get("schedule_id")).isEqualTo("Plan-A");
        actor.set(4);assertThat(service.save(null,firstRequest).get("schedule_id")).isEqualTo("Plan-B");
        actor.set(3);assertThat(service.save(null,secondRequest).get("schedule_id")).isEqualTo("Plan-A");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='DIGEST_COMMAND'",Integer.class)).isEqualTo(5);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM scheduled_plan WHERE kind='DIGEST_SCHEDULE'",Integer.class)).isEqualTo(2);
        assertThat(source.queryForList(sourceRows)).isEqualTo(before);
    }

    @ParameterizedTest
    @CsvSource({"RESTRICT,RESTRICT", "RESTRICT,NO ACTION", "NO ACTION,RESTRICT", "NO ACTION,NO ACTION"})
    void equivalentInnoDbRestrictActionsPreserveTheSourceAndAllowCopy(String deleteRule,String updateRule) throws Exception {
        replaceSourceForeignKey(deleteRule,updateRule);
        assertThat(source.queryForObject("SELECT CONCAT(delete_rule,',',update_rule) FROM information_schema.referential_constraints WHERE constraint_schema=DATABASE() AND constraint_name='fk_digest_run_schedule'",String.class))
                .isEqualTo(deleteRule+","+updateRule);
        copy();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='DIGEST_RUN'",Integer.class)).isEqualTo(2);
        assertThat(source.queryForObject("SELECT COUNT(*) FROM quality_digest_run",Integer.class)).isEqualTo(2);
    }

    @ParameterizedTest
    @CsvSource({"CASCADE,RESTRICT", "RESTRICT,CASCADE", "SET NULL,RESTRICT", "RESTRICT,SET NULL"})
    void rewritingSourceForeignKeyActionsAreRejectedBeforeAnyCopy(String deleteRule,String updateRule) {
        replaceSourceForeignKey(deleteRule,updateRule);
        assertThat(source.queryForObject("SELECT CONCAT(delete_rule,',',update_rule) FROM information_schema.referential_constraints WHERE constraint_schema=DATABASE() AND constraint_name='fk_digest_run_schedule'",String.class))
                .isEqualTo(deleteRule+","+updateRule);
        assertThatThrownBy(this::copy).isInstanceOf(Exception.class);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM scheduled_plan",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance",Integer.class)).isZero();
        assertThat(source.queryForObject("SELECT COUNT(*) FROM quality_digest_run",Integer.class)).isEqualTo(2);
    }

    private void replaceSourceForeignKey(String deleteRule,String updateRule) {
        String nullable="SET NULL".equals(deleteRule)||"SET NULL".equals(updateRule)?"MODIFY schedule_id VARCHAR(64) NULL, ":"";
        source.execute("ALTER TABLE quality_digest_run DROP FOREIGN KEY fk_digest_run_schedule");
        source.execute("ALTER TABLE quality_digest_run "+nullable+"ADD CONSTRAINT fk_digest_run_schedule FOREIGN KEY(schedule_id) REFERENCES quality_digest_schedule(schedule_id) ON DELETE "+deleteRule+" ON UPDATE "+updateRule);
    }

    @ParameterizedTest
    @CsvSource({"plain,true", "escaped,true", "backslash-in-value,false", "extended,false", "or-expression,false"})
    void statusCheckMetadataAllowsOnlyTheTwoExactReviewedSpellings(String representation,boolean accepted) throws Exception {
        String clause="(`status` in (_utf8mb4'PENDING',_utf8mb4'RUNNING',_utf8mb4'COMPLETED',_utf8mb4'FAILED',_utf8mb4'BLOCKED'))";
        clause=switch(representation) {
            case "plain" -> clause;
            case "escaped" -> clause.replace("'","\\'");
            case "backslash-in-value" -> clause.replace("PENDING","PEND\\ING");
            case "extended" -> clause.replace("'BLOCKED'","'BLOCKED',_utf8mb4'UNKNOWN'");
            case "or-expression" -> clause+" OR 1=1";
            default -> throw new IllegalArgumentException("Unreviewed CHECK metadata fixture");
        };
        String guard=Files.readAllLines(Path.of("../sql/mysql/compact/copy/49-digests.sql")).stream()
                .filter(line->line.contains("BINARY t.table_name=BINARY 'quality_digest_run'")&&line.contains("c.check_clause"))
                .findFirst().orElseThrow();
        String predicate=guard.substring(guard.indexOf("BINARY LOWER("),guard.length()-1).replace("c.check_clause","?");
        assertThat(target.queryForObject("SELECT "+predicate,Boolean.class,clause)).isEqualTo(accepted);
    }

    @Test void expandedSourceStatusCheckIsRejectedBeforeAnyCopy() {
        source.execute("ALTER TABLE quality_digest_run DROP CHECK `"+sourceStatusCheck()+"`");
        source.execute("ALTER TABLE quality_digest_run ADD CONSTRAINT fixture_status_domain CHECK(status IN ('PENDING','RUNNING','COMPLETED','FAILED','BLOCKED','UNKNOWN'))");
        assertThatThrownBy(this::copy).isInstanceOf(Exception.class);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM scheduled_plan",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance",Integer.class)).isZero();
        assertThat(source.queryForObject("SELECT COUNT(*) FROM quality_digest_run",Integer.class)).isEqualTo(2);
    }

    @Test void notEnforcedSourceStatusCheckIsRejectedBeforeAnyCopy() {
        source.execute("ALTER TABLE quality_digest_run ALTER CHECK `"+sourceStatusCheck()+"` NOT ENFORCED");
        assertThatThrownBy(this::copy).isInstanceOf(Exception.class);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM scheduled_plan",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance",Integer.class)).isZero();
        assertThat(source.queryForObject("SELECT COUNT(*) FROM quality_digest_run",Integer.class)).isEqualTo(2);
    }

    private String sourceStatusCheck() {
        String name=source.queryForObject("SELECT constraint_name FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name='quality_digest_run' AND constraint_type='CHECK'",String.class);
        assertThat(name).matches("[A-Za-z0-9_]{1,64}");
        return name;
    }

    @Test void unknownSourceColumnStopsBeforeCopyingAnyDigestRows() {
        source.execute("ALTER TABLE quality_digest_run ADD COLUMN unknown_payload TEXT NULL");
        assertThatThrownBy(this::copy).isInstanceOf(Exception.class);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM scheduled_plan WHERE kind='DIGEST_SCHEDULE'",Integer.class)).isZero();
        assertThat(source.queryForObject("SELECT COUNT(*) FROM quality_digest_run",Integer.class)).isEqualTo(2);
    }

    @Test void committedReplayIsRejected() throws Exception {
        copy();
        assertThatThrownBy(this::copy).isInstanceOf(Exception.class);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind IN ('DIGEST_RUN','DIGEST_COMMAND')",Integer.class)).isEqualTo(3);
        assertThat(source.queryForObject("SELECT COUNT(*) FROM quality_digest_run",Integer.class)).isEqualTo(2);
    }

    @Test void additionalSourceConstraintIsRejectedBeforeAnyCopy() {
        source.execute("ALTER TABLE quality_digest_run ADD CONSTRAINT fixture_unreviewed CHECK(owner_user_id>0)");
        assertThatThrownBy(this::copy).isInstanceOf(Exception.class);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM scheduled_plan",Integer.class)).isZero();
        assertThat(source.queryForObject("SELECT COUNT(*) FROM quality_digest_run",Integer.class)).isEqualTo(2);
    }
}
