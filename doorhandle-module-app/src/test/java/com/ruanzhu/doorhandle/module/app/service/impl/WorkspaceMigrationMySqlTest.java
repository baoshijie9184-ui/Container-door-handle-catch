package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.app.testsupport.WorkspaceMigrationFixture;
import java.time.LocalDateTime;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;

/** Complete V38 copy and rollback using the actual public schema; never opens or grants a database. */
@EnabledIfSystemProperty(named="doorhandle.workspace.source.config",matches=".+")
class WorkspaceMigrationMySqlTest {
    static final String FILE="11111111-1111-1111-1111-111111111111",ORPHAN_FILE="22222222-2222-2222-2222-222222222222",MISSING_FILE="33333333-3333-3333-3333-333333333333";
    static final Set<String> FORK_COLUMNS=Set.of("fork_owner_user_id","fork_request_id","fork_source_session_id","fork_through_message_id","fork_legacy_id");
    WorkspaceMigrationFixture fixture;JdbcTemplate source,target;
    final ObjectMapper json=new ObjectMapper().enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
    @BeforeEach void start()throws Exception{fixture=new WorkspaceMigrationFixture();source=fixture.source();target=fixture.target();}
    @AfterEach void close()throws Exception{if(fixture!=null)fixture.close();}
    private void transaction(Runnable action){new TransactionTemplate(new DataSourceTransactionManager(target.getDataSource())).executeWithoutResult(status->action.run());}
    private void seed(){
        target.update("INSERT INTO users(id,username,password) VALUES(1,'alice','fixture')");
        target.update("INSERT INTO chat_session(session_id,user_id,username) VALUES('source',1,'alice'),('child',1,'alice'),('different-owner-child',1,'alice')");
        source.update("INSERT INTO agent_workspace_owner VALUES(1),(999)");
        source.update("INSERT INTO agent_workspace_file(id,file_id,user_id,request_id,filename,content_type,byte_length,sha256,folder,created_at) VALUES(11,?,1,'Upload_Case','资料𠀀.md','text/plain; charset=utf-8',7,UPPER(SHA2('private',256)),'uploads','2026-10-17 12:34:56.123456'),(12,?,999,'orphan-file','历史.csv','text/plain; charset=utf-8',0,SHA2('',256),'artifacts','2026-10-17 12:34:56.654321')",FILE,ORPHAN_FILE);
        source.update("INSERT INTO agent_workspace_file_ref VALUES(21,1,'source',?,'2026-10-17 12:35:01.123456'),(22,999,'missing-session',?,'2026-10-17 12:35:02.234567'),(23,2,'source',?,'2026-10-17 12:35:03.345678'),(24,1,'old-session',?,'2026-10-17 12:35:04.456789')",FILE,MISSING_FILE,FILE,FILE);
        source.update("INSERT INTO agent_workspace_request VALUES(31,1,'Remove_Case',SHA2(CONCAT('source:',?,':REMOVE'),256)),(32,999,'orphan-request',UPPER(SHA2('unknown legacy mutation',256)))",FILE);
        source.update("INSERT INTO agent_session_fork VALUES(41,1,'Fork_Case','source',100,'child'),(42,999,'orphan-fork','missing-source',900,'missing-child'),(43,2,'different-owner','source',100,'different-owner-child')");
        source.update("INSERT INTO agent_workspace_audit VALUES(51,1,'source',?,'FILE_CREATED',UPPER(SHA2('private',256)),'2026-10-17 12:36:01.123456'),(52,999,'missing-session','missing-resource','LEGACY_ACTION',SHA2('legacy',256),'2026-10-17 12:36:02.234567')",FILE);
        source.update("INSERT INTO agent_workspace_business_ref VALUES(61,1,'source','DETECTION','task-1','2026-10-17 12:37:01.123456'),(62,999,'missing-session','LegacyKind','legacy-resource','2026-10-17 12:37:02.234567')");
        for(String table:WorkspaceMigrationFixture.SOURCES)if(!table.equals("agent_workspace_owner"))source.execute("ALTER TABLE "+table+" AUTO_INCREMENT=99999");
    }
    private Map<String,List<Map<String,Object>>> snapshot(){
        var result=new TreeMap<String,List<Map<String,Object>>>();for(String table:WorkspaceMigrationFixture.SOURCES)result.put(table,source.queryForList("SELECT * FROM "+table+" ORDER BY "+(table.equals("agent_workspace_owner")?"user_id":"id")));
        result.put("sequenceReceipt",source.queryForList("SELECT table_name,auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY table_name"));return result;
    }
    private void emptyImport(){
        for(String table:List.of("content_asset","content_revision","content_link","workflow_instance","audit_event","runtime_state"))assertThat(target.queryForObject("SELECT COUNT(*) FROM "+table,Long.class)).as(table).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM chat_session WHERE fork_request_id IS NOT NULL",Long.class)).isZero();
    }
    private void richChild(boolean nullClocks){
        target.update("INSERT INTO chat_project(project_id,username,user_id,name) VALUES('original-project','alice',1,'原项目')");
        LocalDateTime created=nullClocks?null:LocalDateTime.parse("2018-02-03T04:05:06");
        LocalDateTime updated=nullClocks?null:LocalDateTime.parse("2019-03-04T05:06:07");
        target.update("UPDATE chat_session SET project_id='original-project',title=?,status='ARCHIVED',pinned=?,state_json=?,checkpoint_version=7,checkpoint_node=?,checkpoint_exit_reason=?,checkpoint_updated_at=?,created_at=?,updated_at=? WHERE session_id='child'",
                "历史标题𠀀 ",nullClocks?null:Boolean.TRUE,"{ \"original\" : true, \"text\" : \"保留 原文\" }","OriginalNode ","WAITING",nullClocks?null:LocalDateTime.parse("2019-03-04T05:00:00"),created,updated);
    }
    private List<Map<String,Object>> nonForkSessionFacts(){
        return target.queryForList("SELECT * FROM chat_session ORDER BY id").stream().map(row->{Map<String,Object> unchanged=new LinkedHashMap<>(row);FORK_COLUMNS.forEach(unchanged::remove);return unchanged;}).toList();
    }
    @ParameterizedTest @ValueSource(booleans={false,true})
    void forkProjectionPreservesAllOtherSessionFactsIncludingOldOrNullClocks(boolean nullClocks)throws Exception{
        seed();richChild(nullClocks);var original=snapshot();var before=nonForkSessionFacts();
        fixture.migrate("+08:00");
        assertThat(nonForkSessionFacts()).isEqualTo(before);assertThat(snapshot()).isEqualTo(original);
        assertThat(target.queryForObject("SELECT updated_at FROM chat_session WHERE session_id='child'",LocalDateTime.class))
                .isEqualTo(nullClocks?null:LocalDateTime.parse("2019-03-04T05:06:07"));
        assertThat(target.queryForMap("SELECT fork_owner_user_id,fork_request_id,fork_source_session_id,fork_through_message_id,fork_legacy_id FROM chat_session WHERE session_id='child'"))
                .containsEntry("fork_owner_user_id",1L).containsEntry("fork_request_id","Fork_Case").containsEntry("fork_source_session_id","source").containsEntry("fork_through_message_id",100L);
        assertThat(target.queryForObject("SELECT fork_legacy_id FROM chat_session WHERE session_id='child'",Long.class)).isEqualTo(41);
    }
    @ParameterizedTest @ValueSource(strings={"title_space","username_case","state_json_space","checkpoint","created_at_null","updated_at","session_key","row_id"})
    void targetTriggersCannotChangeAnyExistingSessionFactWhileAttachingForkEvidence(String mutation){
        seed();richChild(false);
        String assignment=switch(mutation){
            case "title_space"->"NEW.title=CONCAT(OLD.title,' ')";
            case "username_case"->"NEW.username=UPPER(OLD.username)";
            case "state_json_space"->"NEW.state_json=CONCAT(OLD.state_json,' ')";
            case "checkpoint"->"NEW.checkpoint_version=OLD.checkpoint_version+1";
            case "created_at_null"->"NEW.created_at=NULL";
            case "updated_at"->"NEW.updated_at='2001-01-02 03:04:05'";
            case "session_key"->"NEW.session_id=UPPER(OLD.session_id)";
            case "row_id"->"NEW.id=OLD.id+1000";
            default->throw new AssertionError(mutation);
        };
        target.execute("CREATE TRIGGER damage_existing_session BEFORE UPDATE ON chat_session FOR EACH ROW SET "+assignment);
        var original=snapshot();var sessions=target.queryForList("SELECT * FROM chat_session ORDER BY id");
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class).hasMessageContaining("compact_workspace_session_snapshot");
        emptyImport();assertThat(snapshot()).isEqualTo(original);
        assertThat(target.queryForList("SELECT * FROM chat_session ORDER BY id")).isEqualTo(sessions);
    }
    @Test void allThirtyNineFieldsAndAbsentParentsAreRetainedWithoutInventingTimesOrFiles()throws Exception{
        seed();var original=snapshot();fixture.migrate("+08:00");assertThat(snapshot()).isEqualTo(original);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_kind='WORKSPACE_FILE'",Long.class)).isEqualTo(2);
        var revision=target.queryForMap("SELECT * FROM content_revision WHERE legacy_source='agent_workspace_file' AND legacy_id=11");
        assertThat(revision).containsEntry("filename","资料𠀀.md").containsEntry("media_type","text/plain; charset=utf-8").containsEntry("byte_length",7L).containsEntry("request_id","Upload_Case").containsEntry("object_key","users/1/"+FILE+".bin");
        assertThat(revision.get("content_sha256")).isEqualTo(source.queryForObject("SELECT sha256 FROM agent_workspace_file WHERE id=11",String.class));
        assertThat(json.readValue((String)revision.get("manifest_json"),WorkspacePersistence.FileManifestV1.class)).isEqualTo(new WorkspacePersistence.FileManifestV1("uploads","2026-10-17 12:34:56.123456","+08:00"));
        assertThat(target.queryForObject("SELECT created_at FROM content_revision WHERE legacy_source='agent_workspace_file' AND legacy_id=11",LocalDateTime.class)).isEqualTo(LocalDateTime.parse("2026-10-17T04:34:56.123456"));
        assertThat(target.queryForObject("SELECT COUNT(*) FROM content_link WHERE link_kind='WORKSPACE_FILE'",Long.class)).isEqualTo(4);
        assertThat(target.queryForMap("SELECT * FROM content_link WHERE legacy_source='agent_workspace_file_ref' AND legacy_id=22")).containsEntry("target_id",MISSING_FILE).containsEntry("owner_user_id",999L).containsEntry("asset_id",null).containsEntry("legacy_utc_offset","+08:00");
        assertThat(target.queryForObject("SELECT legacy_created_at FROM content_link WHERE legacy_source='agent_workspace_file_ref' AND legacy_id=22",LocalDateTime.class)).isEqualTo(LocalDateTime.parse("2026-10-17T12:35:02.234567"));
        assertThat(target.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_id=?",Long.class,MISSING_FILE)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM users WHERE id=999",Long.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE created_at IS NULL AND updated_at IS NULL AND finished_at IS NULL",Long.class)).isEqualTo(5);
        assertThat(target.queryForObject("SELECT request_sha256 FROM workflow_instance WHERE legacy_source='agent_workspace_request' AND legacy_key='32'",String.class)).isEqualTo(source.queryForObject("SELECT signature FROM agent_workspace_request WHERE id=32",String.class));
        assertThat(target.queryForObject("SELECT fork_legacy_id FROM chat_session WHERE session_id='child'",Long.class)).isEqualTo(41);
        assertThat(target.queryForObject("SELECT fork_legacy_id FROM chat_session WHERE session_id='different-owner-child'",Long.class)).isNull();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='WORKSPACE'",Long.class)).isEqualTo(2);
        assertThat(target.queryForObject("SELECT target_type FROM content_link WHERE legacy_source='agent_workspace_business_ref' AND legacy_id=62",String.class)).isEqualTo("LegacyKind");
        assertThat(new WorkspacePersistence(target).files(1,"source")).hasSize(1);
        assertThat(new WorkspacePersistence(target).files(2,"source")).isEmpty();
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);assertThat(snapshot()).isEqualTo(original);
    }
    @Test void permanentForkAndMutationReceiptsStillReplayAfterCurrentChildDeletion()throws Exception{
        seed();fixture.migrate("+08:00");target.update("DELETE FROM chat_session WHERE session_id='child'");var store=new WorkspacePersistence(target);
        transaction(()->assertThat(store.fork(1,"Fork_Case")).get().satisfies(fork->{assertThat(fork.resultSessionId()).isEqualTo("child");assertThat(fork.sourceSessionId()).isEqualTo("source");assertThat(fork.throughMessageId()).isEqualTo(100);}));
        String signature=source.queryForObject("SELECT signature FROM agent_workspace_request WHERE id=31",String.class);
        transaction(()->assertThat(store.hasMutation(1,"Remove_Case",signature)).isTrue());
        transaction(()->assertThat(store.hasMutation(1,"remove_case",signature)).isFalse());
        assertThatThrownBy(()->transaction(()->store.hasMutation(1,"Remove_Case","0".repeat(64)))).hasMessageContaining("409");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance",Long.class)).isEqualTo(5);
    }
    @ParameterizedTest @ValueSource(strings={"unknown_column","nullable","business_collation","source_trigger","target_session_column","missing_folder","unused_field","legacy_space","changed_audit","changed_fork_projection"})
    void metadataOrTargetCorruptionRejectsTheWholeCopyAndNeverChangesSource(String mutation){
        seed();switch(mutation){
            case "unknown_column"->source.execute("ALTER TABLE agent_workspace_request ADD unexpected INT NULL");
            case "nullable"->source.execute("ALTER TABLE agent_workspace_file_ref MODIFY created_at DATETIME(6) NULL DEFAULT CURRENT_TIMESTAMP(6)");
            case "business_collation"->source.execute("ALTER TABLE agent_workspace_business_ref MODIFY kind VARCHAR(20) COLLATE utf8mb4_bin NOT NULL");
            case "source_trigger"->source.execute("CREATE TRIGGER unexpected_source BEFORE INSERT ON agent_workspace_request FOR EACH ROW SET NEW.signature=NEW.signature");
            case "target_session_column"->target.execute("ALTER TABLE chat_session ADD unreviewed_clock DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP");
            case "missing_folder"->target.execute("CREATE TRIGGER damage_workspace BEFORE INSERT ON content_revision FOR EACH ROW SET NEW.manifest_json=JSON_REMOVE(NEW.manifest_json,'$.folder')");
            case "unused_field"->target.execute("CREATE TRIGGER damage_workspace BEFORE INSERT ON content_revision FOR EACH ROW SET NEW.content_text='unassigned hidden field'");
            case "legacy_space"->target.execute("CREATE TRIGGER damage_workspace BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.legacy_source=CONCAT(NEW.legacy_source,' ')");
            case "changed_audit"->target.execute("CREATE TRIGGER damage_workspace BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.content_sha256=REPEAT('a',64)");
            case "changed_fork_projection"->target.execute("CREATE TRIGGER damage_workspace BEFORE UPDATE ON chat_session FOR EACH ROW SET NEW.fork_source_session_id='wrong-source'");
            default->throw new AssertionError(mutation);
        }
        var original=snapshot();var sessions=target.queryForList("SELECT * FROM chat_session ORDER BY session_id");
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);emptyImport();assertThat(snapshot()).isEqualTo(original);
        assertThat(target.queryForList("SELECT * FROM chat_session ORDER BY session_id")).isEqualTo(sessions);
    }
    @ParameterizedTest @ValueSource(strings={"agent_workspace_file","agent_workspace_file_ref","agent_workspace_audit","agent_workspace_business_ref"})
    void unchangedOutOfRangeConversionCannotBecomeFabricatedUtc(String table){
        seed();source.update("UPDATE "+table+" SET created_at='9999-01-01 12:34:56.123456'");var original=snapshot();
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);emptyImport();assertThat(snapshot()).isEqualTo(original);
    }
    @Test void invalidOffsetAndIndependentSourceUniquenessCannotBeSilentlyChanged(){
        seed();assertThatThrownBy(()->fixture.migrate("SYSTEM")).isInstanceOf(IllegalArgumentException.class);emptyImport();
        source.execute("ALTER TABLE agent_workspace_request DROP INDEX uk_workspace_mutation");var original=snapshot();
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);emptyImport();assertThat(snapshot()).isEqualTo(original);
    }
}
