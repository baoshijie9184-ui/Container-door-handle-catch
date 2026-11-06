package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.app.dto.chat.*;
import com.ruanzhu.doorhandle.module.app.service.ChatSessionService;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import com.ruanzhu.doorhandle.module.app.testsupport.CompactMySqlFixture;
import com.ruanzhu.doorhandle.module.app.testsupport.FeatureMySql;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@Timeout(180)
@EnabledIfSystemProperty(named="doorhandle.feature.mysql.config",matches=".+")
class AgentWorkspaceServiceTest {
    @TempDir Path directory;
    final AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),bob=new AgentActor(2,"bob",AgentActor.Role.SUPERVISOR);
    JdbcTemplate jdbc;AgentWorkspaceService workspace;ChatSessionService sessions;BusinessUserDirectory users;
    CompactMySqlFixture fixture;
    @BeforeEach void setup()throws Exception{
        var source=FeatureMySql.source();fixture=new CompactMySqlFixture(source);jdbc=new JdbcTemplate(source);
        jdbc.update("INSERT INTO users(id,username,password) VALUES(1,'alice','fixture'),(2,'bob','fixture')");
        jdbc.update("INSERT INTO chat_session(session_id,user_id,username) VALUES ('s1',1,'alice'),('s2',1,'alice'),('bob-session',2,'bob')");
        users=mock(BusinessUserDirectory.class);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));when(users.current(2,"bob")).thenReturn(new BusinessUserDirectory.Identity(2,"bob",true));
        sessions=mock(ChatSessionService.class);when(sessions.resolveTenantForSystemCallback(anyString())).thenAnswer(inv->new TenantContext(inv.<String>getArgument(0).equals("bob-session")?2L:1L,inv.<String>getArgument(0).equals("bob-session")?"bob":"alice"));
        var provider=mock(ObjectProvider.class);workspace=new AgentWorkspaceService(sessions,users,provider,jdbc,new DataSourceTransactionManager(source),directory.toString(),1024,2048);workspace.validate();
    }
    @AfterEach void close(){if(fixture!=null)fixture.close();}
    private void transaction(Runnable work){new org.springframework.transaction.support.TransactionTemplate(new DataSourceTransactionManager(jdbc.getDataSource())).executeWithoutResult(status->work.run());}
    private AgentWorkspaceService secondInstance(){var other=new AgentWorkspaceService(sessions,users,mock(ObjectProvider.class),jdbc,new DataSourceTransactionManager(jdbc.getDataSource()),directory.toString(),1024,2048);other.validate();return other;}
    @Test void realFileFormatsRetainTheirBytesAndUnicodeMetadataAcrossInstances()throws Exception{
        var content=new LinkedHashMap<String,byte[]>();
        for(String format:List.of("png","jpeg")){var bytes=new java.io.ByteArrayOutputStream();assertThat(javax.imageio.ImageIO.write(new java.awt.image.BufferedImage(8,4,java.awt.image.BufferedImage.TYPE_INT_RGB),format,bytes)).isTrue();content.put("检测图片."+format,bytes.toByteArray());}
        content.put("检测图片.webp",Base64.getDecoder().decode("UklGRh4AAABXRUJQVlA4TBEAAAAvAkAAAAdQqGaUsf+BiOh/AAA="));content.put("检测报告.pdf",WorkspaceFileContentTest.pdf("PRIVATE-ROUNDTRIP-EVIDENCE"));
        for(var entry:Map.of("说明.txt","检测证据 原文","报告.md","# 检测报告\n待人工复核","结果.csv","编号,缺陷数\nA,7","检测𠀀.json","{\"编号\":\"一\",\"数量\":7}","源码.html","<script>NEVER_EXECUTE()</script>","源码.svg","<svg onload='NEVER_EXECUTE()'/>").entrySet())content.put(entry.getKey(),entry.getValue().getBytes(StandardCharsets.UTF_8));
        var writer=new AgentWorkspaceService(sessions,users,mock(ObjectProvider.class),jdbc,new DataSourceTransactionManager(jdbc.getDataSource()),directory.toString(),4096,65536);writer.validate();
        var reader=new AgentWorkspaceService(sessions,users,mock(ObjectProvider.class),jdbc,new DataSourceTransactionManager(jdbc.getDataSource()),directory.toString(),4096,65536);reader.validate();
        int request=0;
        for(var entry:content.entrySet()){
            var file=writer.upload(alice,"s1","format-"+request++,entry.getKey(),entry.getValue(),"uploads");var stored=reader.requireFile(alice,"s1",file.id());
            assertThat(stored.name()).isEqualTo(entry.getKey());assertThat(stored.bytes()).isEqualTo(entry.getValue().length);assertThat(stored.sha256()).isEqualTo(HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(entry.getValue())));assertThat(reader.bytes(alice,"s1",file.id())).isEqualTo(entry.getValue());
            assertThatThrownBy(()->reader.bytes(bob,"bob-session",file.id())).hasMessageContaining("404");
            if(stored.contentType().startsWith("image/"))assertThat(reader.readText(alice,"s1",file.id())).contains("尚未接入视觉识别或 OCR");
            else if(stored.contentType().equals("application/pdf")){assertThat(reader.readText(alice,"s1",file.id())).contains("PRIVATE-ROUNDTRIP-EVIDENCE");var preview=reader.previewPdf(alice,"s1",file.id(),1);assertThat(preview.page()).isEqualTo(1);assertThat(javax.imageio.ImageIO.read(new java.io.ByteArrayInputStream(preview.png()))).isNotNull();}
            else{assertThat(stored.contentType()).startsWith("text/plain");assertThat(reader.readText(alice,"s1",file.id())).isEqualTo(new String(entry.getValue(),StandardCharsets.UTF_8));}
        }
        assertThat(reader.files(alice,"s1")).hasSize(10);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='WORKSPACE' AND action='FILE_CREATED'",Integer.class)).isEqualTo(10);
        try(var files=Files.walk(directory)){assertThat(files.filter(Files::isRegularFile).count()).isEqualTo(10);}
    }
    @Test void twoInstancesCannotBothConsumeTheLastAccountQuotaSlot()throws Exception{
        upload("prefill","prefill.txt","x".repeat(1024));var other=secondInstance();var gate=new java.util.concurrent.CountDownLatch(1);var racers=java.util.concurrent.Executors.newFixedThreadPool(2);var outcomes=new java.util.concurrent.CopyOnWriteArrayList<Integer>();
        try{
            var tasks=new ArrayList<java.util.concurrent.Future<?>>();
            for(int index=0;index<2;index++){int candidate=index;tasks.add(racers.submit(()->{gate.await();try{(candidate==0?workspace:other).upload(alice,candidate==0?"s1":"s2","last-"+candidate,"last-"+candidate+".txt","y".repeat(1024).getBytes(StandardCharsets.UTF_8),"uploads");outcomes.add(200);}catch(org.springframework.web.server.ResponseStatusException rejected){outcomes.add(rejected.getStatusCode().value());}return null;}));}
            gate.countDown();for(var task:tasks)task.get(30,java.util.concurrent.TimeUnit.SECONDS);
            assertThat(outcomes).containsExactlyInAnyOrder(200,413);assertThat(jdbc.queryForObject("SELECT SUM(byte_length) FROM content_revision WHERE asset_kind='WORKSPACE_FILE' AND owner_user_id=1",Long.class)).isEqualTo(2048);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_kind='WORKSPACE_FILE' AND owner_user_id=1",Integer.class)).isEqualTo(2);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='WORKSPACE' AND owner_user_id=1 AND action='FILE_CREATED'",Integer.class)).isEqualTo(2);
            try(var files=Files.walk(directory)){assertThat(files.filter(Files::isRegularFile).count()).isEqualTo(2);}
            assertThat(other.upload(bob,"bob-session","independent","other.txt","z".repeat(1024).getBytes(StandardCharsets.UTF_8),"uploads").bytes()).isEqualTo(1024);
        }finally{racers.shutdownNow();}
    }
    @Test void concurrentSameRequestAcrossInstancesCreatesOneFileAndOneAudit()throws Exception{
        var other=secondInstance();var gate=new java.util.concurrent.CountDownLatch(1);var racers=java.util.concurrent.Executors.newFixedThreadPool(2);var ids=new java.util.concurrent.CopyOnWriteArrayList<String>();
        try{
            var tasks=new ArrayList<java.util.concurrent.Future<?>>();
            for(int index=0;index<6;index++){int candidate=index;tasks.add(racers.submit(()->{gate.await();ids.add((candidate%2==0?workspace:other).upload(alice,"s1","same-request","same.txt","same bytes".getBytes(StandardCharsets.UTF_8),"uploads").id());return null;}));}
            gate.countDown();for(var task:tasks)task.get(30,java.util.concurrent.TimeUnit.SECONDS);
            assertThat(ids).hasSize(6);assertThat(new HashSet<>(ids)).hasSize(1);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_kind='WORKSPACE_FILE'",Integer.class)).isEqualTo(1);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='WORKSPACE' AND action='FILE_CREATED'",Integer.class)).isEqualTo(1);
            try(var files=Files.walk(directory)){assertThat(files.filter(Files::isRegularFile).count()).isEqualTo(1);}
        }finally{racers.shutdownNow();}
    }
    WorkbenchSessionApi.File upload(String request,String name,String text){return workspace.upload(alice,"s1",request,name,text.getBytes(StandardCharsets.UTF_8),"uploads");}
    @Test void privateUploadIsIdempotentAndCannotBeReadThroughAnotherSessionOrAccount(){var file=upload("upload-1","notes.md","PRIVATE_NOTES");assertThat(upload("upload-1","notes.md","PRIVATE_NOTES")).isEqualTo(file);assertThat(workspace.readText(alice,"s1",file.id())).isEqualTo("PRIVATE_NOTES");assertThatThrownBy(()->workspace.bytes(bob,"bob-session",file.id())).hasMessageContaining("404");assertThatThrownBy(()->workspace.bytes(alice,"s2",file.id())).hasMessageContaining("404");assertThatThrownBy(()->upload("upload-1","notes.md","different")).hasMessageContaining("409");assertThat(jdbc.queryForList("SELECT * FROM audit_event WHERE kind='WORKSPACE'").toString()).doesNotContain("PRIVATE_NOTES");}
    @Test void filenamesMimeSniffingQuotaAndChangedDiskContentAreEnforced()throws Exception{
        assertThatThrownBy(()->upload("bad","../notes.md","text")).hasMessageContaining("400");assertThatThrownBy(()->upload("bad2","fake.png","not png")).hasMessageContaining("415");assertThatThrownBy(()->upload("big","big.txt","x".repeat(1025))).hasMessageContaining("400");
        var file=upload("one","one.txt","x".repeat(1024));upload("two","two.txt","y".repeat(1024));assertThatThrownBy(()->upload("three","three.txt","z")).hasMessageContaining("413");
        Files.writeString(directory.resolve("users/1/"+file.id()+".bin"),"changed");assertThatThrownBy(()->workspace.bytes(alice,"s1",file.id())).hasMessageContaining("409");
    }
    @Test void htmlAndSvgArePlainTextAndGeneratedJsonIsValidated(){var file=upload("html","page.html","<script>alert(1)</script>");assertThat(file.contentType()).startsWith("text/plain");assertThat(workspace.readText(alice,"s1",file.id())).contains("<script>");assertThatThrownBy(()->workspace.createArtifact(alice,"s1","artifact","bad.json","{bad}")).hasMessageContaining("400");assertThat(workspace.createArtifact(alice,"s1","csv","data.csv","name,count\na,2").folder()).isEqualTo("artifacts");}
    @Test void removalIsIdempotentAndDoesNotEraseAForkedReference(){var file=upload("one","one.md","hello");jdbc.update("INSERT INTO chat_session(session_id,user_id,username) VALUES('forked',1,'alice')");transaction(()->new WorkspacePersistence(jdbc).linkFile(1,"forked",file.id()));workspace.remove(alice,"s1",file.id(),"remove-1");workspace.remove(alice,"s1",file.id(),"remove-1");assertThat(workspace.files(alice,"s1")).isEmpty();assertThat(workspace.readText(alice,"forked",file.id())).isEqualTo("hello");assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='WORKSPACE' AND action='FILE_UNLINKED'",Integer.class)).isEqualTo(1);}
    @Test void pdfToolReadsRequireFreshAccountSessionAndDiskIntegrity()throws Exception{
        var file=workspace.upload(alice,"s1","pdf","report.pdf",WorkspaceFileContentTest.pdf("PRIVATE-PDF-EVIDENCE"),"uploads");
        assertThat(workspace.readText(alice,"s1",file.id())).contains("PRIVATE-PDF-EVIDENCE");
        assertThatThrownBy(()->workspace.readText(bob,"bob-session",file.id())).hasMessageContaining("404");
        assertThatThrownBy(()->workspace.readText(alice,"s2",file.id())).hasMessageContaining("404");
        assertThatThrownBy(()->workspace.previewPdf(bob,"bob-session",file.id(),1)).hasMessageContaining("404");
        when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",true));
        assertThatThrownBy(()->workspace.readText(alice,"s1",file.id())).isInstanceOf(SecurityException.class);
        when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        var path=directory.resolve("users/1/"+file.id()+".bin");byte[] changed=Files.readAllBytes(path);changed[20]^=1;Files.write(path,changed);
        assertThatThrownBy(()->workspace.readText(alice,"s1",file.id())).hasMessageContaining("409");
    }
    @Test void rejectedFilesDoNotCreateMetadataAuditOrPrivateFiles()throws Exception{
        assertThatThrownBy(()->upload("bad-pdf","header.pdf","%PDF-1.4\nnot a document\n%%EOF")).hasMessageContaining("415");
        assertThatThrownBy(()->upload("bad-json","bad.json","{} []")).hasMessageContaining("415");
        assertThat(workspace.files(alice,"s1")).isEmpty();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='WORKSPACE'",Integer.class)).isZero();
        try(var paths=Files.walk(directory)){assertThat(paths.filter(Files::isRegularFile).count()).isZero();}
    }
    @Test void previewLimitIsConfigurableAndJsonValidationCannotBeBypassedByFilenameCase(){org.springframework.test.util.ReflectionTestUtils.setField(workspace,"previewBytes",4);var file=upload("text","text.txt","123456");assertThat(workspace.readText(alice,"s1",file.id())).startsWith("1234\n[内容已").doesNotContain("123456");assertThat(workspace.limits().get("previewBytes")).isEqualTo(4);assertThatThrownBy(()->workspace.createArtifact(alice,"s1","json","bad.JSON","{} trailing")).hasMessageContaining("400");}
    @Test void auditFailureRollsBackMetadataAndRemovesTheNewPrivateFile()throws Exception{jdbc.execute("ALTER TABLE audit_event ADD CONSTRAINT reject_upload CHECK(kind<>'WORKSPACE' OR action<>'FILE_CREATED')");assertThatThrownBy(()->upload("one","one.md","PRIVATE")).isInstanceOf(org.springframework.dao.DataAccessException.class);assertThat(workspace.files(alice,"s1")).isEmpty();try(var paths=Files.walk(directory)){assertThat(paths.filter(Files::isRegularFile).count()).isZero();}}
    @Test void forkCopiesOnlyTheFinishedPrefixAndOnlyFilesPresentAtThatTime(){
        var user=new ChatMessageResponse();user.setId(1L);user.setRole("user");user.setContent("first");var answer=new ChatMessageResponse();answer.setId(2L);answer.setRole("assistant");answer.setContent("answer");answer.setCreatedAt("2026-10-17 10:00:00");var later=new ChatMessageResponse();later.setId(3L);later.setRole("user");later.setContent("later");when(sessions.listMessages("alice","s1")).thenReturn(List.of(user,answer,later));var target=new ChatSessionResponse();target.setSessionId("forked");when(sessions.createForkSession("alice")).thenAnswer(inv->{jdbc.update("INSERT INTO chat_session(session_id,user_id,username) VALUES('forked',1,'alice')");return target;});
        var cutoff=LocalDateTime.of(2026,10,17,10,0).atZone(java.time.ZoneId.systemDefault()).withZoneSameInstant(java.time.ZoneOffset.UTC).toLocalDateTime();
        var early=upload("early","early.txt","early");var late=upload("late","late.txt","late");jdbc.update("UPDATE content_link SET created_at=? WHERE link_kind='WORKSPACE_FILE' AND workspace_file_id=?",cutoff.minusHours(1),early.id());jdbc.update("UPDATE content_link SET created_at=? WHERE link_kind='WORKSPACE_FILE' AND workspace_file_id=?",cutoff.plusHours(1),late.id());
        assertThat(workspace.fork(alice,"s1",2,"fork-1")).isEqualTo("forked");assertThat(workspace.fork(alice,"s1",2,"fork-1")).isEqualTo("forked");verify(sessions,times(1)).appendUserMessage(new TenantContext(1L,"alice"),"forked","first");verify(sessions,never()).appendUserMessage(any(),anyString(),eq("later"));assertThat(workspace.files(alice,"forked")).extracting(WorkbenchSessionApi.File::id).containsExactly(early.id());
        assertThat(workspace.lineage(alice,"forked").get("throughMessageId")).isEqualTo(2L);
        jdbc.update("DELETE FROM chat_session WHERE session_id='forked'");
        assertThat(workspace.fork(alice,"s1",2,"fork-1")).isEqualTo("forked");
        verify(sessions,times(1)).createForkSession("alice");
    }
    @Test void unknownCommitAcknowledgementKeepsTheOnlyFileAndRetryReadsTheCommittedReceipt()throws Exception{
        var uncertain=new DataSourceTransactionManager(jdbc.getDataSource()){
            @Override protected void doCommit(org.springframework.transaction.support.DefaultTransactionStatus status){
                super.doCommit(status);throw new org.springframework.transaction.TransactionSystemException("simulated lost COMMIT acknowledgement");
            }
        };
        var writer=new AgentWorkspaceService(sessions,users,mock(ObjectProvider.class),jdbc,uncertain,directory.toString(),1024,2048);
        assertThatThrownBy(()->writer.upload(alice,"s1","uncertain","receipt.txt","only copy".getBytes(StandardCharsets.UTF_8),"uploads")).isInstanceOf(org.springframework.transaction.TransactionSystemException.class);
        var retained=workspace.upload(alice,"s1","uncertain","receipt.txt","only copy".getBytes(StandardCharsets.UTF_8),"uploads");
        assertThat(workspace.bytes(alice,"s1",retained.id())).isEqualTo("only copy".getBytes(StandardCharsets.UTF_8));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_kind='WORKSPACE_FILE'",Long.class)).isEqualTo(1);
        try(var paths=Files.walk(directory)){assertThat(paths.filter(Files::isRegularFile).count()).isEqualTo(1);}
    }
    @Test void newReferencesRejectCrossOwnerAndMissingFilesDespiteRetainedLegacyOrphans(){
        var file=upload("owned","owned.md","private");var store=new WorkspacePersistence(jdbc);
        assertThatThrownBy(()->transaction(()->store.linkFile(2,"bob-session",file.id()))).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->transaction(()->store.linkFile(1,"s1",UUID.randomUUID().toString()))).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->jdbc.update("DELETE FROM content_asset WHERE asset_id=?",file.id())).isInstanceOf(org.springframework.dao.DataAccessException.class);
    }
    @Test void businessReferencesKeepOriginalCaseInsensitiveKindUniquenessAndMutationReceipts(){
        var api=mock(AgentBusinessFilesApi.class);when(api.list(any(),anyString(),anyString())).thenReturn(List.of());
        ObjectProvider<AgentBusinessFilesApi> provider=mock(ObjectProvider.class);when(provider.getIfAvailable()).thenReturn(api);when(provider.getObject()).thenReturn(api);workspace.setBusiness(provider);
        workspace.attachBusinessFiles(alice,"s1","attach-1","DETECTION","task-1");
        workspace.attachBusinessFiles(alice,"s1","attach-1","DETECTION","task-1");
        workspace.attachBusinessFiles(alice,"s1","attach-2","detection","task-1");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_link WHERE link_kind='WORKSPACE_BUSINESS'",Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT target_type FROM content_link WHERE link_kind='WORKSPACE_BUSINESS'",String.class)).isEqualTo("DETECTION");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='WORKSPACE_MUTATION'",Long.class)).isEqualTo(2);
        assertThatThrownBy(()->workspace.attachBusinessFiles(alice,"s1","attach-1","DETECTION","task-2")).hasMessageContaining("409");
        when(api.list(alice,"DETECTION","task-1")).thenThrow(new SecurityException("access revoked"));
        assertThat(workspace.businessFiles(alice,"s1")).isEmpty();
    }
    @Test void exactSnapshotInheritsOnlyReferencesPresentAtTheTurnAndStillLinkedAtFork(){
        jdbc.update("INSERT INTO chat_message(id,session_id,role,message_type,content) VALUES(11,'s1','assistant','TEXT','done')");
        var early=upload("early","early.md","early");var removed=upload("removed","removed.md","removed");
        var store=new WorkspacePersistence(jdbc);transaction(()->store.linkBusiness(1,"s1","DETECTION","task-1"));
        var snapshots=new WorkspaceTurnSnapshotService(jdbc,new com.fasterxml.jackson.databind.ObjectMapper().setSerializationInclusion(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL));
        transaction(()->snapshots.capture(new TenantContext(1L,"alice"),"s1",11));
        upload("late","late.md","late");workspace.remove(alice,"s1",removed.id(),"remove-after-turn");
        transaction(()->assertThat(snapshots.inherit(1,"s1",11,"s2")).isTrue());
        assertThat(workspace.files(alice,"s2")).extracting(WorkbenchSessionApi.File::id).containsExactly(early.id());
        assertThat(store.hasBusiness(1,"s2","DETECTION","task-1")).isTrue();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='MESSAGE_WORKSPACE_SNAPSHOT'",Long.class)).isEqualTo(1);
    }
}
