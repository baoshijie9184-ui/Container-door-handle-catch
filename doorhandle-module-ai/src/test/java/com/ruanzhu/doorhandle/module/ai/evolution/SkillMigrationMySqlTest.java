package com.ruanzhu.doorhandle.module.ai.evolution;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.ai.EcsIsolatedMysql;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactContentFixture;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactWorkflowFixture;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ScriptStatementFailedException;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import static org.assertj.core.api.Assertions.*;

/** Real legacy DDL and copy scripts, enabled only on an admitted disposable ECS MySQL fixture. */
@EnabledIfSystemProperty(named="agent.skill.mysql-file",matches=".+")
class SkillMigrationMySqlTest {
    private static final String SKILL="skill-11111111-1111-4111-8111-111111111111";
    private static final String DOWNLOAD="download-22222222-2222-4222-8222-222222222222";
    private static final String RUNNING="download-33333333-3333-4333-8333-333333333333";
    private static final String BODY="# 检查步骤\r\n逐项检查  \r\n保留原始换行与尾部空格\n";
    private static final String MANIFEST="{\"name\":\"检查技能\",\"instructions\":\"保留中文\",\"files\":[\"SKILL.md\"]}";
    private static final String EVIDENCE="{\"sourceType\":\"LINK\",\"downloadId\":\""+DOWNLOAD+"\",\"note\":\"原始依据\"}";
    private static final LocalDateTime BEIJING=LocalDateTime.of(2026,11,5,10,30,0);
    private static final LocalDateTime UTC=BEIJING.minusHours(8);
    private DriverManagerDataSource source;
    private JdbcTemplate jdbc;
    private Path sqlRoot;
    private String schema;

    @BeforeEach void setup() throws Exception {
        source=EcsIsolatedMysql.open(System.getProperty("agent.skill.mysql-file"),"doorhandle_skill_verify_");
        jdbc=new JdbcTemplate(source);
        schema=jdbc.queryForObject("SELECT DATABASE()",String.class);
        if(schema==null||!schema.matches("doorhandle_skill_verify_[a-f0-9]{10}"))
            throw new SecurityException("Skill migration fixture must use the admitted disposable schema");
        sqlRoot=sourceRoot().resolve("sql/mysql");
        resetFixture();
        CompactContentFixture.install(jdbc);
        CompactWorkflowFixture.install(jdbc);
        for(String migration:List.of("migration-V23-agent-skill-evolution.sql","migration-V24-external-skill-import.sql",
                "migration-V27-linked-skill-download.sql","migration-V28-linked-skill-upgrade.sql",
                "migration-V29-skill-storage-cleanup.sql","migration-V46-skill-download-leases.sql"))
            execute(Files.readString(sqlRoot.resolve(migration)));
        seedLinkedSkill();
    }

    private static Path sourceRoot() {
        for(Path path=Path.of("").toAbsolutePath();path!=null;path=path.getParent())
            if(Files.isRegularFile(path.resolve("sql/mysql/compact/copy/22-skills.sql")))return path;
        throw new IllegalStateException("The admitted ECS checkout must contain the original skill migrations");
    }

    private void resetFixture() {
        // Remove only known fixture tables, after EcsIsolatedMysql has verified the schema/account/server.
        // Unhook the two cyclic publication pointers without disabling foreign-key checks.
        for(String constraint:List.of("fk_content_current_revision","fk_content_published_revision"))
            if(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='content_asset' AND CONSTRAINT_NAME=? AND CONSTRAINT_TYPE='FOREIGN KEY'",Long.class,constraint)>0)
                jdbc.execute("ALTER TABLE content_asset DROP FOREIGN KEY "+constraint);
        for(String table:List.of("content_link","content_chunk","content_revision","content_asset","audit_event",
                "workflow_instance","scheduled_plan","runtime_state","agent_skill_download_event","agent_skill_download_lease",
                "agent_skill_download_owner","agent_skill_storage_command","agent_skill_download","agent_skill_audit",
                "agent_skill_eval","agent_skill_import","agent_skill_version","agent_learned_skill","agent_skill_source"))
            jdbc.execute("DROP TABLE IF EXISTS "+table);
    }

    private void execute(String sql) throws Exception {
        try(var connection=source.getConnection()) {
            connection.setAutoCommit(false);
            try {
                ScriptUtils.executeSqlScript(connection,new EncodedResource(
                        new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8));
                connection.commit();
            } catch(Exception failure) {connection.rollback();throw failure;}
        }
    }

    private void migrate(String script) throws Exception {
        // Old names are source fixture tables, never compatibility tables for the new runtime.
        // A single disposable schema exercises the real qualified SQL without extra schema grants.
        execute(Files.readString(sqlRoot.resolve("compact/copy").resolve(script))
                .replace("__SOURCE_SCHEMA__",schema).replace("__SOURCE_SKILL_OFFSET__","+08:00"));
    }

    private void seedLinkedSkill() throws Exception {
        jdbc.update("""
                INSERT INTO agent_learned_skill(skill_id,owner_user_id,name,target_role,latest_version,active_version,
                    revision,lifecycle,use_count,last_used_at,activated_at,created_at,updated_at)
                VALUES(?,1,'检查技能','INSPECTOR',1,1,4,'ACTIVE',7,?,?,?,?)
                """,SKILL,BEIJING.plusHours(1),BEIJING.plusMinutes(20),BEIJING,BEIJING.plusMinutes(20));
        jdbc.update("""
                INSERT INTO agent_skill_version(skill_id,version_no,owner_user_id,request_id,request_sha256,
                    description_text,instructions_text,tool_names_json,source_run_id,source_type,source_import_id,
                    evidence_json,content_sha256,status,reviewer_user_id,review_reason,created_at,submitted_at,reviewed_at)
                VALUES(?,1,1,'Draft_Case_Sensitive',?,'保留描述',?,'[]',NULL,'LINK',?,?,?,'APPROVED',2,'审核原文',?,?,?)
                """,SKILL,sha("draft-request"),BODY,DOWNLOAD,EVIDENCE,sha("canonical-skill-document"),
                BEIJING,BEIJING.plusMinutes(10),BEIJING.plusMinutes(20));
        jdbc.update("""
                INSERT INTO agent_skill_download(download_id,owner_user_id,request_id,request_sha256,source_url,
                    target_role,status,manifest_json,manifest_sha256,skill_id,created_at,updated_at)
                VALUES(?,1,'Download_Case_Sensitive',?,'https://github.com/fixtures/skills/tree/main/reader',
                    'INSPECTOR','DRAFT_CREATED',?,?,?, ?,?)
                """,DOWNLOAD,sha("download-request"),MANIFEST,sha(MANIFEST),SKILL,BEIJING,BEIJING.plusMinutes(20));
        jdbc.update("""
                INSERT INTO agent_skill_download_lease(download_id,owner_user_id,status,reserved_bytes,worker_instance,
                    process_pid,process_started_at,exit_verified,lease_expires_at,created_at,updated_at)
                VALUES(?,1,'SEALED',0,'original-worker',4321,'2026-11-05T02:30:00Z',TRUE,?,?,?)
                """,DOWNLOAD,BEIJING.plusMinutes(5),BEIJING.plusNanos(123456000),BEIJING.plusMinutes(1));
    }

    private void corruptSource(String corruption) {
        switch(corruption) {
            case "missing-download" -> jdbc.update("DELETE FROM agent_skill_download WHERE download_id=?",DOWNLOAD);
            case "foreign-owner" -> jdbc.update("UPDATE agent_skill_download SET owner_user_id=2 WHERE download_id=?",DOWNLOAD);
            case "missing-package" -> jdbc.update("UPDATE agent_skill_download SET manifest_json=NULL,manifest_sha256=NULL WHERE download_id=?",DOWNLOAD);
            case "unusable-status" -> jdbc.update("UPDATE agent_skill_download SET status='PURGED' WHERE download_id=?",DOWNLOAD);
            default -> throw new IllegalArgumentException(corruption);
        }
    }

    private void assertSourceVersionPreserved() {
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_skill_version",Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT instructions_text FROM agent_skill_version WHERE skill_id=?",String.class,SKILL)).isEqualTo(BODY);
        assertThat(jdbc.queryForObject("SELECT owner_user_id FROM agent_skill_version WHERE skill_id=?",Long.class,SKILL)).isEqualTo(1);
    }

    private void assertNoDownloadsCopied() {
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind IN ('SKILL_DOWNLOAD','SKILL_STORAGE_COMMAND')",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_asset WHERE legacy_source='agent_skill_download'",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_revision WHERE legacy_source='agent_skill_download'",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='SKILL_DOWNLOAD_EVENT'",Long.class)).isZero();
    }

    @ParameterizedTest @ValueSource(strings={"missing-download","foreign-owner","missing-package","unusable-status"})
    void skillCopyRejectsUnownedOrUnusableLinkedPackageBeforeWriting(String corruption) {
        corruptSource(corruption);
        assertThatThrownBy(()->migrate("22-skills.sql")).isInstanceOf(ScriptStatementFailedException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_asset",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_revision",Long.class)).isZero();
        assertSourceVersionPreserved();
    }

    @ParameterizedTest @ValueSource(strings={"missing-download","foreign-owner","missing-package","unusable-status"})
    void downloadCopyRechecksSourceAfterTheSkillCopyCommitted(String corruption) throws Exception {
        migrate("22-skills.sql");
        corruptSource(corruption);
        assertThatThrownBy(()->migrate("23-skill-downloads.sql")).isInstanceOf(ScriptStatementFailedException.class);
        assertNoDownloadsCopied();
        assertThat(jdbc.queryForObject("SELECT content_text FROM content_revision WHERE asset_id=? AND version=1",String.class,SKILL)).isEqualTo(BODY);
        assertSourceVersionPreserved();
    }

    @Test void downloadCopyAlsoRejectsAnAlreadyCopiedSkillWithDifferentOwnership() throws Exception {
        migrate("22-skills.sql");
        // The original owner is still correct, so only the copied-reference preflight can catch this.
        jdbc.update("UPDATE content_revision SET owner_user_id=2 WHERE asset_kind='SKILL' AND asset_id=?",SKILL);
        assertThatThrownBy(()->migrate("23-skill-downloads.sql")).isInstanceOf(ScriptStatementFailedException.class);
        assertNoDownloadsCopied();
        assertSourceVersionPreserved();
    }

    @Test void postCopyGateRejectsAnEqualCountPackageWithWrongSourceType() throws Exception {
        migrate("22-skills.sql");
        // UPLOAD is valid package DDL but invalid for this LINK relationship. The final join must reject it.
        jdbc.execute("CREATE TRIGGER corrupt_skill_package BEFORE INSERT ON content_revision FOR EACH ROW SET NEW.source_type=IF(NEW.asset_kind='SKILL_IMPORT','UPLOAD',NEW.source_type)");
        assertThatThrownBy(()->migrate("23-skill-downloads.sql")).isInstanceOf(ScriptStatementFailedException.class);
        assertNoDownloadsCopied();
        assertSourceVersionPreserved();
    }

    @Test void validCopiesPreserveOwnersBytesHashesPointersTimeAndUnknownExitFacts() throws Exception {
        jdbc.update("""
                INSERT INTO agent_skill_download(download_id,owner_user_id,request_id,request_sha256,source_url,
                    target_role,status,created_at,updated_at)
                VALUES(?,1,'Running_Original',?,'https://github.com/fixtures/skills/tree/main/pending',
                    'INSPECTOR','DOWNLOADING',?,?)
                """,RUNNING,sha("running-request"),BEIJING,BEIJING);
        jdbc.update("""
                INSERT INTO agent_skill_download_lease(download_id,owner_user_id,status,reserved_bytes,worker_instance,
                    process_pid,process_started_at,exit_verified,lease_expires_at,created_at,updated_at)
                VALUES(?,1,'RUNNING',4194304,'lost-worker',9876,'2026-11-05T02:30:00Z',FALSE,?,?,?)
                """,RUNNING,BEIJING.plusMinutes(5),BEIJING,BEIJING);
        migrate("22-skills.sql");
        migrate("23-skill-downloads.sql");
        var skill=jdbc.queryForMap("SELECT * FROM content_revision WHERE asset_kind='SKILL' AND asset_id=? AND version=1",SKILL);
        assertThat(skill).containsEntry("owner_user_id",1L).containsEntry("source_import_id",DOWNLOAD)
                .containsEntry("content_text",BODY).containsEntry("request_id","Draft_Case_Sensitive")
                .containsEntry("content_sha256",sha("canonical-skill-document")).containsEntry("stored_content_sha256",sha(BODY))
                .containsEntry("approval_status","APPROVED").containsEntry("reviewer_user_id",2L);
        assertThat(((Number)skill.get("byte_length")).longValue()).isEqualTo(BODY.getBytes(StandardCharsets.UTF_8).length);
        assertThat(jdbc.queryForObject("SELECT manifest_json FROM content_revision WHERE asset_id=?",String.class,SKILL))
                .isEqualTo(jdbc.queryForObject("SELECT CAST(evidence_json AS CHAR CHARACTER SET utf8mb4) FROM agent_skill_version WHERE skill_id=?",String.class,SKILL));
        var header=jdbc.queryForMap("SELECT current_version,published_version,revision,use_count FROM content_asset WHERE asset_id=?",SKILL);
        assertThat(header).containsEntry("current_version",1).containsEntry("published_version",1).containsEntry("revision",4L).containsEntry("use_count",7L);
        String originalManifest=jdbc.queryForObject("SELECT CAST(manifest_json AS CHAR CHARACTER SET utf8mb4) FROM agent_skill_download WHERE download_id=?",String.class,DOWNLOAD);
        var pack=jdbc.queryForMap("SELECT owner_user_id,source_type,manifest_json,manifest_sha256,stored_content_sha256 FROM content_revision WHERE asset_kind='SKILL_IMPORT' AND asset_id=?",DOWNLOAD);
        assertThat(pack).containsEntry("owner_user_id",1L).containsEntry("source_type","LINK").containsEntry("manifest_json",originalManifest)
                .containsEntry("manifest_sha256",sha(MANIFEST)).containsEntry("stored_content_sha256",sha(originalManifest));
        assertThat(jdbc.queryForObject("SELECT created_at FROM content_revision WHERE asset_id=?",LocalDateTime.class,SKILL)).isEqualTo(UTC);
        assertThat(jdbc.queryForObject("SELECT reviewed_at FROM content_revision WHERE asset_id=?",LocalDateTime.class,SKILL)).isEqualTo(UTC.plusMinutes(20));
        assertThat(jdbc.queryForObject("SELECT execution_deadline FROM workflow_instance WHERE workflow_id=?",LocalDateTime.class,DOWNLOAD)).isEqualTo(UTC.plusMinutes(5));
        assertThat(jdbc.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.lease.createdAt')) FROM workflow_instance WHERE workflow_id=?",String.class,DOWNLOAD)).isEqualTo("2026-11-05T02:30:00.123456");
        var downloads=new SkillDownloadStore(jdbc,new ObjectMapper());
        assertThat(downloads.download(1,DOWNLOAD,false)).containsEntry("request_id","Download_Case_Sensitive").containsEntry("status","DRAFT_CREATED").containsEntry("skill_id",SKILL);
        assertThat(downloads.lookup(2,DOWNLOAD,false)).isEmpty();
        assertThat(downloads.packageEvidence(2,DOWNLOAD)).isEmpty();
        assertThat(downloads.requested(1,"download_case_sensitive")).isEmpty();
        assertThat(downloads.held(1)).containsOnlyKeys(RUNNING).containsEntry(RUNNING,4194304L);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='SKILL_DOWNLOAD' AND claim_token IS NULL AND lease_expires_at IS NULL AND fence=0",Long.class)).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_id=?",Long.class,RUNNING)).isZero();
        assertSourceVersionPreserved();
    }

    private static String sha(String value) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    }
}
