package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.module.app.testsupport.SupportCopyMySqlFixture;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;

/** Five actual legacy sources, exact bytes/NULL clocks, independent compact projections and ECS only. */
@EnabledIfSystemProperty(named="doorhandle.support.source.config",matches=".+")
@EnabledIfSystemProperty(named="doorhandle.support.mysql.config",matches=".+")
class SupportCopyMigrationMySqlTest {
    private static final LocalDateTime WALL=LocalDateTime.of(2026,2,3,14,15,16);
    private static final long LARGE_ID=9007199254740993L;
    SupportCopyMySqlFixture fixture;
    JdbcTemplate source,target;
    @BeforeEach void setup() throws Exception {
        fixture=new SupportCopyMySqlFixture();source=fixture.source();target=fixture.target();seed();fixture.copyReferences();
    }
    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}

    @Test void allOriginalColumnsAndFingerprintFactsSurviveWithExactSourceBytesAndHighWaterHoles() throws Exception {
        var original=snapshot();
        fixture.copyChatAndFingerprints();fixture.copyOwnerLocks();
        assertThat(snapshot()).isEqualTo(original);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'",Integer.class)).isEqualTo(29);
        for(String table:List.of("chat_project","chat_message")) {
            String columns=columns(table);
            assertThat(target.queryForList("SELECT "+columns+" FROM `"+table+"` ORDER BY id"))
                    .isEqualTo(source.queryForList("SELECT "+columns+" FROM `"+table+"` ORDER BY id"));
            assertThat(target.queryForObject("SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=?",Long.class,table))
                    .isEqualTo(source.queryForObject("SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=?",Long.class,table));
        }
        assertThat(target.queryForObject("SELECT created_at FROM chat_project WHERE id=41",String.class)).isNull();
        assertThat(target.queryForObject("SELECT updated_at FROM chat_project WHERE id=41",String.class)).isNull();
        assertThat(target.queryForObject("SELECT created_at FROM chat_message WHERE id=51",String.class)).isNull();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_kind='DETECTION_IMAGE'",Integer.class)).isEqualTo(3);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace='DETECTION_FINGERPRINT' AND current_ref='shared-task'",Integer.class)).isEqualTo(2);
        String sourceObject=jsonObject("detection_image_fingerprint","s");
        var originals=source.queryForList("SELECT id,CAST("+sourceObject+" AS CHAR CHARACTER SET utf8mb4) row_json,SHA2(CAST("+sourceObject+" AS CHAR CHARACTER SET utf8mb4),256) row_sha256 FROM detection_image_fingerprint s ORDER BY id");
        for(var row:originals) {
            var stored=target.queryForMap("SELECT a.owner_user_id,a.legacy_owner_reference,a.identity_key,a.title,a.filename,a.current_version,a.lifecycle,a.revision,a.created_at,a.updated_at,r.version AS revision_version,r.manifest_json,r.manifest_sha256,r.content_sha256,r.object_key FROM content_asset a JOIN content_revision r ON r.asset_id=a.asset_id AND r.asset_kind=a.asset_kind AND r.version=a.current_version WHERE a.legacy_source='detection_image_fingerprint' AND a.legacy_id=?",row.get("id"));
            var raw=source.queryForMap("SELECT * FROM detection_image_fingerprint WHERE id=?",row.get("id"));
            assertThat(stored).containsEntry("owner_user_id",null).containsEntry("legacy_owner_reference",raw.get("owner_user_id"))
                    .containsEntry("manifest_json",row.get("row_json")).containsEntry("manifest_sha256",row.get("row_sha256"))
                    .containsEntry("created_at",raw.get("created_at")).containsEntry("updated_at",raw.get("updated_at"))
                    .containsEntry("title",raw.get("file_name")).containsEntry("filename",raw.get("file_name"))
                    .containsEntry("object_key",raw.get("object_key"))
                    .containsEntry("current_version",1).containsEntry("revision_version",1).containsEntry("lifecycle","ACTIVE");
            assertThat(stored.get("identity_key")).isEqualTo(raw.get("sha256").toString().toLowerCase(java.util.Locale.ROOT));
            assertThat(stored.get("content_sha256")).isEqualTo(stored.get("identity_key"));
            var state=target.queryForMap("SELECT * FROM runtime_state WHERE namespace='DETECTION_FINGERPRINT' AND scope_key=?",stored.get("identity_key"));
            assertThat(state).containsEntry("owner_id",0L).containsEntry("state_code",raw.get("status"))
                    .containsEntry("current_ref",raw.get("last_task_id")).containsEntry("created_at",raw.get("created_at"))
                    .containsEntry("updated_at",raw.get("updated_at"));
            assertThat(target.queryForObject("SELECT CAST(JSON_EXTRACT(payload_json,'$.originalId') AS DECIMAL(20,0)) FROM runtime_state WHERE namespace='DETECTION_FINGERPRINT' AND scope_key=?",java.math.BigDecimal.class,stored.get("identity_key")))
                    .isEqualByComparingTo(raw.get("id").toString());
        }
        assertThat(target.queryForObject("SELECT legacy_owner_reference FROM content_asset WHERE legacy_id=?",String.class,LARGE_ID)).isEqualTo("not-a-number");
        assertThat(target.queryForObject("SELECT JSON_TYPE(JSON_EXTRACT(payload_json,'$.sourceOwnerKey')) FROM runtime_state WHERE namespace='DETECTION_FINGERPRINT' AND scope_key=?",String.class,"a".repeat(64))).isEqualTo("NULL");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM users",Integer.class)).isEqualTo(1);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM detection_task",Integer.class)).isZero();
    }

    @Test void ownerLocksRetainKnownSourceTimeAndLeaveUnavailableTimesUnknown() throws Exception {
        var original=snapshot();fixture.copyOwnerLocks();assertThat(snapshot()).isEqualTo(original);
        var research=target.queryForList("SELECT owner_id,created_at,updated_at FROM runtime_state WHERE namespace='RESEARCH_STORAGE' ORDER BY owner_id");
        assertThat(research).hasSize(2);
        assertThat(research.get(0)).containsEntry("owner_id",7L).containsEntry("updated_at",null);
        assertThat(target.queryForObject("SELECT created_at FROM runtime_state WHERE namespace='RESEARCH_STORAGE' AND owner_id=7",LocalDateTime.class))
                .isEqualTo(WALL.withNano(123456000));
        assertThat(target.queryForList("SELECT created_at,updated_at FROM runtime_state WHERE namespace='SKILL_DOWNLOAD'"))
                .hasSize(2).allSatisfy(row->assertThat(row).containsEntry("created_at",null).containsEntry("updated_at",null));
        assertThat(target.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace IN ('RESEARCH_STORAGE','SKILL_DOWNLOAD') AND (revision<>0 OR payload_json IS NOT NULL OR current_ref IS NOT NULL OR state_code IS NOT NULL)",Integer.class)).isZero();
    }

    @Test void originalCaseInsensitivePadSpaceParentKeysAndTextCollationsSurviveWithoutRewritingTheirBytes() throws Exception {
        source.update("INSERT INTO chat_session(id,session_id,username,user_id,title,status,pinned,created_at,updated_at,state_json,checkpoint_version,checkpoint_node,checkpoint_exit_reason,checkpoint_updated_at) VALUES(32,'Session-CI ','SOURCE-USER ',7,'旧父键','ACTIVE',0,NULL,NULL,NULL,0,'Node-CI','Reason-CI',NULL)");
        source.update("INSERT INTO chat_message(id,session_id,role,message_type,content,intent,action_id,created_at) VALUES(59,'SESSION-ci','assistant','TEXT','父子键大小写和尾空格原样保留',NULL,NULL,NULL)");
        target.update("INSERT INTO chat_session(id,session_id,username,user_id,title,status,pinned,created_at,updated_at,state_json,checkpoint_version,checkpoint_node,checkpoint_exit_reason,checkpoint_updated_at) VALUES(32,'Session-CI ','SOURCE-USER ',7,'旧父键','ACTIVE',0,NULL,NULL,NULL,0,'Node-CI','Reason-CI',NULL)");
        var original=snapshot();fixture.copyChatAndFingerprints();assertThat(snapshot()).isEqualTo(original);
        assertThat(target.queryForObject("SELECT session_id FROM chat_message WHERE id=59",String.class)).isEqualTo("SESSION-ci");
        assertThat(target.queryForObject("SELECT session_id FROM chat_session WHERE id=32",String.class)).isEqualTo("Session-CI ");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM chat_message m JOIN chat_session s ON s.session_id=m.session_id WHERE m.id=59 AND s.id=32",Integer.class)).isEqualTo(1);
        target.update("UPDATE chat_session SET project_id='P-EXACT ' WHERE id=32");
        assertThat(target.queryForObject("SELECT project_id FROM chat_session WHERE id=32",String.class)).isEqualTo("P-EXACT ");
        for(String table:List.of("chat_project","chat_session","chat_message")) {
            for(var column:source.queryForList("SELECT column_name,collation_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=? AND collation_name IS NOT NULL",table)) {
                assertThat(target.queryForObject("SELECT collation_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=? AND column_name=?",String.class,table,column.get("column_name")))
                        .as("Original text semantics of %s.%s",table,column.get("column_name")).isEqualTo(column.get("collation_name"));
            }
        }
        assertThat(target.queryForObject("SELECT collation_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chat_session' AND column_name='fork_source_session_id'",String.class)).isEqualTo("utf8mb4_bin");
        assertThat(target.queryForObject("SELECT collation_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='chat_message' AND column_name='execution_run_id'",String.class)).isEqualTo("utf8mb4_bin");
        assertThatThrownBy(()->target.update("INSERT INTO chat_project(project_id,username,user_id,name) VALUES('P-EXACT ','source-user',7,'重复原键')"))
                .isInstanceOf(org.springframework.dao.DataAccessException.class);
    }

    @Test void repeatingEitherCopyRefusesToReplaceAnyPriorRows() throws Exception {
        fixture.copyChatAndFingerprints();fixture.copyOwnerLocks();var original=snapshot();
        var imported=targetSnapshot();
        assertThatThrownBy(fixture::copyChatAndFingerprints).isInstanceOf(Exception.class);
        assertThatThrownBy(fixture::copyOwnerLocks).isInstanceOf(Exception.class);
        assertThat(targetSnapshot()).isEqualTo(imported);assertThat(snapshot()).isEqualTo(original);
    }

    @ParameterizedTest @ValueSource(strings={"unknown_column","invalid_sha","damaged_projection","damaged_current_pointer"})
    void invalidSourceOrChangedProjectionRollsBackChatAndFingerprintTogether(String mutation) {
        switch(mutation) {
            case "unknown_column"->source.execute("ALTER TABLE detection_image_fingerprint ADD unreviewed_column VARCHAR(12) NULL");
            case "invalid_sha"->source.update("UPDATE detection_image_fingerprint SET sha256=REPEAT('X',64),updated_at=? WHERE id=61",WALL);
            case "damaged_projection"->target.execute("CREATE TRIGGER corrupt_support BEFORE INSERT ON runtime_state FOR EACH ROW SET NEW.current_ref=IF(NEW.namespace='DETECTION_FINGERPRINT','wrong-task',NEW.current_ref)");
            case "damaged_current_pointer"->target.execute("CREATE TRIGGER corrupt_current_pointer BEFORE UPDATE ON content_asset FOR EACH ROW SET NEW.current_version=IF(NEW.asset_kind='DETECTION_IMAGE',NULL,NEW.current_version)");
            default->throw new AssertionError(mutation);
        }
        var original=snapshot();
        var rejected=assertThatThrownBy(fixture::copyChatAndFingerprints).isInstanceOf(Exception.class);
        if(mutation.equals("damaged_current_pointer"))rejected.hasStackTraceContaining("compact_support_guard");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM chat_project",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM chat_message",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM content_asset",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM content_revision",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace='DETECTION_FINGERPRINT'",Integer.class)).isZero();
        assertThat(snapshot()).isEqualTo(original);
    }

    @Test void unreviewedOwnerColumnCannotProduceAPartialLockImport() {
        source.execute("ALTER TABLE agent_skill_download_owner ADD unreviewed_column INT NULL");
        var original=snapshot();assertThatThrownBy(fixture::copyOwnerLocks).isInstanceOf(Exception.class);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace IN ('RESEARCH_STORAGE','SKILL_DOWNLOAD')",Integer.class)).isZero();
        assertThat(snapshot()).isEqualTo(original);
    }

    private Map<String,Object> snapshot() {
        var result=new LinkedHashMap<String,Object>();
        for(String table:SupportCopyMySqlFixture.SUPPORT) {
            String key=switch(table){case "agent_research_storage_owner"->"user_id";case "agent_skill_download_owner"->"owner_user_id";default->"id";};
            result.put(table,source.queryForList("SELECT * FROM `"+table+"` ORDER BY `"+key+"`"));
        }
        result.put("highWater",source.queryForList("SELECT table_name,auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY table_name"));
        return result;
    }
    private Map<String,Object> targetSnapshot() {
        return Map.of("projects",target.queryForList("SELECT * FROM chat_project ORDER BY id"),
                "messages",target.queryForList("SELECT * FROM chat_message ORDER BY id"),
                "assets",target.queryForList("SELECT * FROM content_asset ORDER BY id"),
                "revisions",target.queryForList("SELECT * FROM content_revision ORDER BY id"),
                "states",target.queryForList("SELECT * FROM runtime_state ORDER BY namespace,owner_id,scope_key"));
    }
    private String columns(String table) {
        return String.join(",",source.queryForList("SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=? ORDER BY ordinal_position",String.class,table).stream().map(name->"`"+name+"`").toList());
    }
    private String jsonObject(String table,String alias) {
        return "JSON_OBJECT("+String.join(",",source.queryForList("SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=? ORDER BY ordinal_position",String.class,table).stream().map(name->"'"+name+"',"+alias+".`"+name+"`").toList())+")";
    }
    private void seed() {
        source.update("INSERT INTO users(id,username,password,role,created_at,updated_at) VALUES(7,'source-user','fixture','INSPECTOR',NULL,NULL)");
        source.update("INSERT INTO chat_session(id,session_id,username,user_id,title,status,pinned,created_at,updated_at,state_json,checkpoint_version,checkpoint_node,checkpoint_exit_reason,checkpoint_updated_at) VALUES(31,'session-source','source-user',7,'原会话','ACTIVE',0,NULL,NULL,NULL,0,NULL,NULL,NULL)");
        source.update("INSERT INTO chat_project(id,project_id,username,user_id,name,description,color,sort_order,created_at,updated_at) VALUES(41,'p-null','source-user',7,'项目 NULL',NULL,NULL,NULL,NULL,NULL),(45,'p-exact','source-user',7,'项目😀','null','#0055ff',-7,?,?)",WALL,WALL.plusSeconds(1));
        source.update("INSERT INTO chat_message(id,session_id,role,message_type,content,intent,action_id,created_at) VALUES(51,'session-source','assistant','TEXT','原始内容\n空格  ',NULL,'null',NULL),(55,'session-source','user','BUSINESS','{\"raw\":\"null\"}','原意图',NULL,?)",WALL);
        source.update("INSERT INTO detection_image_fingerprint(id,sha256,file_name,object_key,status,last_task_id,owner_user_id,version,created_at,updated_at) VALUES(61,?,'原图😀.png','images/a.png','NEW','shared-task',NULL,3,?,?),(64,?,'另一图.jpg','images/b.jpg','SUCCESS','shared-task','0042',4,?,?),(?,?, 'non-numeric-owner.png','images/c.png','FAILED',NULL,'not-a-number',0,?,?)",
                "A".repeat(64),WALL,WALL.plusSeconds(1),"B".repeat(64),WALL,WALL.plusSeconds(2),LARGE_ID,"c".repeat(64),WALL,WALL.plusSeconds(3));
        source.update("INSERT INTO agent_research_storage_owner(user_id,created_at) VALUES(7,?),(42,?)",WALL.withNano(123456000),WALL.withNano(654321000));
        source.update("INSERT INTO agent_skill_download_owner(owner_user_id) VALUES(7),(42)");
        source.execute("ALTER TABLE chat_project AUTO_INCREMENT=50000");
        source.execute("ALTER TABLE chat_message AUTO_INCREMENT=60000");
        source.execute("ALTER TABLE detection_image_fingerprint AUTO_INCREMENT=9007199254741099");
    }
}
