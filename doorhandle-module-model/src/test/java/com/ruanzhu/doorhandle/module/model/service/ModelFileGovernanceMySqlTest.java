package com.ruanzhu.doorhandle.module.model.service;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.testsupport.ModelFileMigrationFixture;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ScriptStatementFailedException;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@EnabledIfSystemProperty(named="model.file.copy.source-config",matches=".+")
@EnabledIfSystemProperty(named="model.file.copy.target-config",matches=".+")
class ModelFileGovernanceMySqlTest {
    private static final LocalDateTime CREATED=LocalDateTime.of(2026,10,14,12,30,1,123456000),UPDATED=CREATED.plusHours(3);
    private static final String RESERVED="00000000-0000-0000-0000-000000000001",READY="00000000-0000-0000-0000-000000000002",
            REGISTERED="00000000-0000-0000-0000-000000000003",RETAINED="00000000-0000-0000-0000-000000000004",
            RECEIPT="10000000-0000-0000-0000-000000000001",SECOND="10000000-0000-0000-0000-000000000002",LEGACY="10000000-0000-0000-0000-000000000003";
    private final ObjectMapper json=new ObjectMapper().findAndRegisterModules().disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
            .setSerializationInclusion(JsonInclude.Include.NON_NULL);
    private ModelFileMigrationFixture fixture;
    private JdbcTemplate source,target;
    private ModelFilePersistence files;
    private ModelFileJournal journal;
    private ModelMutationIdentity identity;
    private OperationsAuditApi operations;
    private TransactionTemplate tx;
    @TempDir Path directory;
    @BeforeEach void setup() throws Exception {
        fixture=new ModelFileMigrationFixture();source=fixture.source();target=fixture.target();
        var manager=new DataSourceTransactionManager(fixture.targetDataSource());tx=new TransactionTemplate(manager);
        files=new ModelFilePersistence(target,json);
        identity=mock(ModelMutationIdentity.class);operations=mock(OperationsAuditApi.class);
        when(identity.supervisor()).thenReturn(actor(77));when(identity.requestId()).thenReturn("runtime-request");
        journal=new ModelFileJournal(files,manager,operations,identity);journal.requireSchema();
    }
    @AfterEach void cleanup() throws Exception {if(fixture!=null)fixture.close();}
    private AgentActor actor(long id){return new AgentActor(id,"supervisor-"+id,AgentActor.Role.SUPERVISOR);}
    private static String path(String id){return "/srv/doorhandle/models/"+id+".onnx";}
    private void seed() {
        for(String id:List.of(RESERVED,READY,REGISTERED,RETAINED)) {
            boolean reserved=id.equals(RESERVED),registered=id.equals(REGISTERED),retained=id.equals(RETAINED);
            String state=reserved?"RESERVED":registered?"REGISTERED":retained?"RETAINED":"FILE_READY";
            Integer modelId=registered?Integer.valueOf(Integer.MIN_VALUE):retained?Integer.valueOf(0):null;
            source.update("""
                    INSERT INTO detection_model_file_journal(file_id,actor_user_id,request_id,storage_path,path_sha256,content_sha256,byte_size,model_id,state,revision,created_at,updated_at)
                    VALUES(?,77,?,?,?,?,?,?,?,?,?,?)
                    """,id,"upload-"+id,path(id),ModelFileJournal.pathDigest(path(id)),reserved?null:"a".repeat(64),reserved?null:123L,
                    modelId,state,reserved?0:registered?2:retained?3:1,CREATED,UPDATED);
        }
        for(String id:List.of(RECEIPT,SECOND,LEGACY)) {
            boolean legacy=id.equals(LEGACY);String p=legacy?"/old/model path ":path(RETAINED);
            source.update("""
                    INSERT INTO detection_model_file_retention(retention_id,model_id,actor_user_id,request_id,file_id,storage_path,path_sha256,content_sha256,byte_size,state,revision,created_at,updated_at)
                    VALUES(?,?,88,'same-request',?,?,?,?,?,?,?,?,?)
                    """,id,legacy?-1:0,legacy?null:RETAINED,p,ModelFileJournal.pathDigest(p),legacy?null:"a".repeat(64),legacy?null:123L,
                    legacy?"RETAINED_LEGACY":"RETAINED",legacy?7L:4L,CREATED,UPDATED);
        }
    }
    private List<Map<String,Object>> uploadSource(){return source.queryForList("SELECT * FROM detection_model_file_journal ORDER BY file_id");}
    private List<Map<String,Object>> retentionSource(){return source.queryForList("SELECT * FROM detection_model_file_retention ORDER BY retention_id");}
    private void empty(){assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance",Long.class)).isZero();assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event",Long.class)).isZero();}
    private String state(String fileId){return target.queryForObject("SELECT status FROM workflow_instance WHERE resource_id=? AND kind='MODEL_FILE_UPLOAD'",String.class,fileId);}

    @Test void actualV53CopiesEveryFactWithoutModelFkOrInventedContentVersions() throws Exception {
        seed();var before=uploadSource();var beforeRetained=retentionSource();fixture.copy();
        assertThat(fixture.sourceName()).isNotEqualTo(fixture.targetName());assertThat(uploadSource()).isEqualTo(before);assertThat(retentionSource()).isEqualTo(beforeRetained);
        var view=journal.list(null,100);assertThat(view.uploads()).hasSize(4);assertThat(view.retained()).hasSize(3);
        assertThat(view.uploads()).extracting(ModelFileJournal.UploadView::state).containsExactly("RETAINED","REGISTERED","FILE_READY","RESERVED");
        assertThat(view.uploads().get(1).modelId()).isEqualTo(Integer.MIN_VALUE);assertThat(view.uploads().get(0).modelId()).isZero();
        assertThat(view.uploads()).extracting(ModelFileJournal.UploadView::updatedAt).containsOnly(UPDATED);
        assertThat(view.retained()).extracting(ModelFileJournal.RetentionView::updatedAt).containsOnly(UPDATED);
        assertThat(journal.list("same-request",100).retained()).hasSize(3);
        assertThat(view.retained()).filteredOn(row->row.retentionId().equals(LEGACY)).singleElement()
                .satisfies(row->{assertThat(row.fileId()).isNull();assertThat(row.sha256()).isNull();assertThat(row.bytes()).isNull();assertThat(row.modelId()).isEqualTo(-1);assertThat(row.revision()).isEqualTo(7);});
        assertThat(target.queryForObject("SELECT COUNT(*) FROM model_management",Long.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'",Long.class)).isEqualTo(29);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('detection_model_file_journal','detection_model_file_retention')",Long.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM content_asset",Long.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM content_revision",Long.class)).isZero();
        assertThat(target.queryForList("SELECT occurred_at FROM audit_event",LocalDateTime.class)).containsOnly(CREATED.minusHours(8));
        assertThat(target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.legacyUpdatedAt')) FROM audit_event WHERE event_id=?",String.class,"model-retain:"+LEGACY)).isEqualTo("2026-10-14T15:30:01.123456");
        assertThat(json.writeValueAsString(view)).contains("\"updatedAt\":\"2026-10-14T15:30:01.123456\"")
                .doesNotContain("/srv/","/old/","storagePath");
    }

    @Test void realUploadRegistersAndRetainsBytesWhenAnotherSupervisorDeletesTheModel() throws Exception {
        @SuppressWarnings("unchecked") ObjectProvider<ModelFileJournal> provider=mock(ObjectProvider.class);when(provider.getIfAvailable()).thenReturn(journal);
        var uploads=new ModelUploadFiles(provider,identity,directory.toString(),1000L);
        var prepared=uploads.write(new MockMultipartFile("file","model.onnx","application/octet-stream",new byte[]{1,2,3,4}));
        uploads.verify(prepared);assertThat(state(prepared.fileId())).isEqualTo("FILE_READY");
        tx.executeWithoutResult(status->{target.update("INSERT INTO model_management(model_id,model_name,version,model_path) VALUES(-7,'runtime','1',?)",prepared.path().toString());journal.registered(prepared,-7);});
        assertThat(state(prepared.fileId())).isEqualTo("REGISTERED");
        when(identity.supervisor()).thenReturn(actor(88));
        var model=new ModelInfo();model.setModelId(-7);model.setModelPath(prepared.path().toString());
        tx.executeWithoutResult(status->{journal.retain(model);target.update("DELETE FROM model_management WHERE model_id=-7");});
        assertThat(state(prepared.fileId())).isEqualTo("RETAINED");assertThat(Files.readAllBytes(prepared.path())).containsExactly(new byte[]{1,2,3,4});
        assertThat(journal.list(null,100).retained()).singleElement().satisfies(row->{assertThat(row.actorUserId()).isEqualTo(88);assertThat(row.modelId()).isEqualTo(-7);assertThat(row.sha256()).isEqualTo(prepared.sha256());});
        assertThat(target.queryForObject("SELECT owner_user_id FROM workflow_instance",Long.class)).isEqualTo(77);
        assertThat(target.queryForObject("SELECT JSON_CONTAINS_PATH(payload_json,'all','$.legacyCreatedAt','$.legacyUpdatedAt') FROM workflow_instance",Integer.class)).isEqualTo(1);
        when(identity.supervisor()).thenThrow(new SecurityException("revoked"));assertThatThrownBy(()->journal.list(null,100)).isInstanceOf(SecurityException.class);
    }

    @Test void auditFailureRollsBackReservationRegistrationAndRetentionWithoutDeletingFiles() throws Exception {
        String id=UUID.randomUUID().toString();String p=directory.resolve("kept.onnx").toString();Files.write(Path.of(p),new byte[]{9});
        doThrow(new IllegalStateException("audit unavailable")).when(operations).append(any());
        assertThatThrownBy(()->journal.reserve(id,"reserve",p)).isInstanceOf(IllegalStateException.class);empty();assertThat(Files.exists(Path.of(p))).isTrue();
        reset(operations);journal.reserve(id,"reserve",p);var prepared=new ModelUploadFiles.Prepared(id,"reserve",77,Path.of(p),"b".repeat(64),1);
        journal.ready(prepared);
        doThrow(new IllegalStateException("audit unavailable")).when(operations).append(any());
        assertThatThrownBy(()->tx.executeWithoutResult(status->{target.update("INSERT INTO model_management(model_id,model_name,version,model_path) VALUES(0,'rollback','1',?)",p);journal.registered(prepared,0);})).isInstanceOf(IllegalStateException.class);
        assertThat(state(id)).isEqualTo("FILE_READY");assertThat(target.queryForObject("SELECT COUNT(*) FROM model_management",Long.class)).isZero();
        reset(operations);tx.executeWithoutResult(status->journal.registered(prepared,0));
        doThrow(new IllegalStateException("audit unavailable")).when(operations).append(any());
        var model=new ModelInfo();model.setModelId(0);model.setModelPath(p);
        assertThatThrownBy(()->tx.executeWithoutResult(status->journal.retain(model))).isInstanceOf(IllegalStateException.class);
        assertThat(state(id)).isEqualTo("REGISTERED");assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event",Long.class)).isZero();assertThat(Files.exists(Path.of(p))).isTrue();
    }

    @Test void uploadRequestAndPathUniquenessRemainPermanentAndPreparedOwnershipIsRechecked() {
        String id=UUID.randomUUID().toString(),path=directory.resolve("identity.onnx").toString();journal.reserve(id,"once",path);
        assertThatThrownBy(()->journal.reserve(UUID.randomUUID().toString(),"once",path+"2")).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(()->journal.reserve(UUID.randomUUID().toString(),"another",path)).isInstanceOf(DataAccessException.class);
        var wrong=new ModelUploadFiles.Prepared(id,"once",99,Path.of(path),"a".repeat(64),1);
        assertThatThrownBy(()->journal.ready(wrong)).isInstanceOf(IllegalStateException.class);assertThat(state(id)).isEqualTo("RESERVED");
        assertThatThrownBy(()->tx.executeWithoutResult(status->journal.reserve(UUID.randomUUID().toString(),"inside",path+"3"))).isInstanceOf(IllegalStateException.class);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance",Long.class)).isEqualTo(1);
    }

    @ParameterizedTest @ValueSource(strings={"request","path"})
    void concurrentReservationsHaveOneWinnerForEitherPermanentUniqueIdentity(String conflict) throws Exception {
        var start=new java.util.concurrent.CountDownLatch(1);var executor=java.util.concurrent.Executors.newFixedThreadPool(2);
        try {
            var results=new java.util.ArrayList<java.util.concurrent.Future<Boolean>>();
            for(int number=0;number<2;number++) {
                int n=number;results.add(executor.submit(()->{
                    if(!start.await(5,java.util.concurrent.TimeUnit.SECONDS))throw new IllegalStateException("fixture barrier timeout");
                    try {journal.reserve(UUID.randomUUID().toString(),conflict.equals("request")?"shared-request":"request-"+n,
                            directory.resolve(conflict.equals("path")?"shared.onnx":"model-"+n+".onnx").toString());return true;}
                    catch(DataAccessException|IllegalStateException expected){return false;}
                }));
            }
            start.countDown();int winners=0;for(var result:results)if(result.get(20,java.util.concurrent.TimeUnit.SECONDS))winners++;
            assertThat(winners).isEqualTo(1);assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance",Long.class)).isEqualTo(1);
        } finally {executor.shutdownNow();if(!executor.awaitTermination(20,java.util.concurrent.TimeUnit.SECONDS))throw new IllegalStateException("Fixture reservation threads did not stop");}
    }

    @ParameterizedTest @ValueSource(strings={"columns","type","nullable","collation","default","index","check","trigger"})
    void changedV53MetadataCannotBeSilentlyAccepted(String change) {
        seed();switch(change) {
            case "columns"->source.execute("ALTER TABLE detection_model_file_retention ADD forgotten VARCHAR(10) NULL");
            case "type"->source.execute("ALTER TABLE detection_model_file_journal MODIFY storage_path VARCHAR(2049) COLLATE utf8mb4_bin NOT NULL");
            case "nullable"->source.execute("ALTER TABLE detection_model_file_journal MODIFY actor_user_id BIGINT NULL");
            case "collation"->source.execute("ALTER TABLE detection_model_file_journal MODIFY request_id VARCHAR(128) COLLATE utf8mb4_unicode_ci NOT NULL");
            case "default"->source.execute("ALTER TABLE detection_model_file_journal ALTER COLUMN revision SET DEFAULT 1");
            case "index"->source.execute("ALTER TABLE detection_model_file_journal DROP INDEX uk_detection_model_file_path");
            case "check"->source.execute("ALTER TABLE detection_model_file_retention ADD CONSTRAINT unseen CHECK(actor_user_id>0)");
            case "trigger"->source.execute("CREATE TRIGGER unseen BEFORE INSERT ON detection_model_file_retention FOR EACH ROW SET NEW.revision=NEW.revision");
            default->throw new IllegalArgumentException(change);
        }
        var a=uploadSource();var b=retentionSource();assertThatThrownBy(fixture::copy).isInstanceOf(ScriptStatementFailedException.class);empty();assertThat(uploadSource()).isEqualTo(a);assertThat(retentionSource()).isEqualTo(b);
    }

    @ParameterizedTest @ValueSource(strings={"owner","path-hash","content-hash","negative-size","state","unexpected-model","missing-source-file","timestamp"})
    void illegalHistoricalFactsAbortTheWholeCopyInsteadOfFilteringRows(String change) {
        seed();switch(change) {
            case "owner"->source.update("UPDATE detection_model_file_journal SET actor_user_id=0 WHERE file_id=?",RESERVED);
            case "path-hash"->source.update("UPDATE detection_model_file_journal SET path_sha256=? WHERE file_id=?","f".repeat(64),RESERVED);
            case "content-hash"->source.update("UPDATE detection_model_file_journal SET content_sha256='not-a-hash' WHERE file_id=?",READY);
            case "negative-size"->source.update("UPDATE detection_model_file_journal SET byte_size=-1 WHERE file_id=?",READY);
            case "state"->source.update("UPDATE detection_model_file_journal SET state='FILE_READY ' WHERE file_id=?",READY);
            case "unexpected-model"->source.update("UPDATE detection_model_file_journal SET model_id=0 WHERE file_id=?",RESERVED);
            case "missing-source-file"->source.update("UPDATE detection_model_file_retention SET file_id=? WHERE retention_id=?",UUID.randomUUID().toString(),RECEIPT);
            case "timestamp"->source.update("UPDATE detection_model_file_retention SET updated_at='9999-01-01 00:00:00' WHERE retention_id=?",LEGACY);
            default->throw new IllegalArgumentException(change);
        }
        var a=uploadSource();var b=retentionSource();assertThatThrownBy(fixture::copy).isInstanceOf(ScriptStatementFailedException.class);empty();assertThat(uploadSource()).isEqualTo(a);assertThat(retentionSource()).isEqualTo(b);
    }

    @ParameterizedTest @ValueSource(strings={"upload-source-space","upload-key-space","upload-legacy-time","retention-source-space","retention-key-space","retention-legacy-time","retention-extra-hash"})
    void byteExactReconciliationRejectsTargetCorruptionWithTheSameRowCount(String change) {
        seed();boolean upload=change.startsWith("upload");String field=change.contains("source-space")?"NEW.legacy_source=CONCAT(NEW.legacy_source,' ')":change.contains("key-space")?"NEW.legacy_key=CONCAT(NEW.legacy_key,' ')":change.contains("extra-hash")?"NEW.previous_sha256=REPEAT('a',64)":"NEW.payload_json=JSON_SET(NEW.payload_json,'$.legacyUpdatedAt','2026-10-15T15:30:01.123456')";
        target.execute("CREATE TRIGGER corrupt_file_copy BEFORE INSERT ON "+(upload?"workflow_instance":"audit_event")+" FOR EACH ROW SET "+field);
        assertThatThrownBy(fixture::copy).isInstanceOf(ScriptStatementFailedException.class).hasMessageContaining("LEFT JOIN");empty();
    }

    @ParameterizedTest @ValueSource(strings={"+00:00","-05:30"})
    void explicitOffsetPreservesBothOriginalTimesAndTheIndependentUpdatedInstant(String offset) throws Exception {
        seed();fixture.copy(offset,fixture.sourceName());
        var original=java.time.ZoneOffset.of(offset);
        assertThat(target.queryForList("SELECT occurred_at FROM audit_event",LocalDateTime.class)).containsOnly(CREATED.atOffset(original).withOffsetSameInstant(java.time.ZoneOffset.UTC).toLocalDateTime());
        assertThat(journal.list(null,100).retained()).extracting(ModelFileJournal.RetentionView::updatedAt)
                .containsOnly(UPDATED.atOffset(original).withOffsetSameInstant(java.time.ZoneOffset.ofHours(8)).toLocalDateTime());
    }

    @Test void sameSchemaAndRepeatCopyCannotOverwriteEvidence() throws Exception {
        seed();assertThatThrownBy(()->fixture.copy("+08:00",fixture.targetName())).isInstanceOf(ScriptStatementFailedException.class);empty();
        fixture.copy();assertThatThrownBy(fixture::copy).isInstanceOf(ScriptStatementFailedException.class);
        assertThat(journal.list(null,100).uploads()).hasSize(4);assertThat(journal.list(null,100).retained()).hasSize(3);
    }
}
