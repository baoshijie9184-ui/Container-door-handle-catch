package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.app.dto.chat.*;
import com.ruanzhu.doorhandle.module.app.service.ChatSessionService;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentWorkspaceServiceTest {
    @TempDir Path directory;
    final AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),bob=new AgentActor(2,"bob",AgentActor.Role.SUPERVISOR);
    JdbcTemplate jdbc;AgentWorkspaceService workspace;ChatSessionService sessions;BusinessUserDirectory users;
    @BeforeEach void setup()throws Exception{
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");jdbc=new JdbcTemplate(source);
        String ddl=Files.readString(Path.of("../sql/mysql/migration-V38-agent-workspace.sql")).replaceAll("(?m)^--.*$", "").replace(" COLLATE utf8mb4_bin","").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","")
            .replaceAll("(?m)^(\\s*)UNIQUE KEY (\\w+)\\s*(\\([^\\n]+\\))", "$1CONSTRAINT $2 UNIQUE $3").replaceAll("(?m)^\\s*KEY .*\\n","").replaceAll(",\\s*\\)",")");
        if(Boolean.getBoolean("workbench.mysql")){
            var config=new com.fasterxml.jackson.databind.ObjectMapper().readTree(Path.of("../work/workbench-mysql/connection.json").toFile());String database=config.path("database").asText();
            if(!database.matches("doorhandle_wb_verify_[a-f0-9]{10}")||!config.path("url").asText().startsWith("jdbc:mysql://127.0.0.1:13308/"+database+"?"))throw new IllegalStateException("Only the isolated verification database is allowed");
            source=new DriverManagerDataSource(config.path("url").asText(),config.path("username").asText(),config.path("password").asText());jdbc=new JdbcTemplate(source);
            for(String table:List.of("agent_workspace_file_ref","agent_workspace_file","agent_workspace_request","agent_workspace_owner","agent_session_fork","agent_workspace_audit","agent_workspace_business_ref"))jdbc.execute("DROP TABLE IF EXISTS "+table);
            ddl=Files.readString(Path.of("../sql/mysql/migration-V38-agent-workspace.sql")).replaceAll("(?m)^--.*$", "");
        }
        for(String sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
        users=mock(BusinessUserDirectory.class);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));when(users.current(2,"bob")).thenReturn(new BusinessUserDirectory.Identity(2,"bob",true));
        sessions=mock(ChatSessionService.class);when(sessions.resolveTenantForSystemCallback(anyString())).thenAnswer(inv->new TenantContext(inv.<String>getArgument(0).equals("bob-session")?2L:1L,inv.<String>getArgument(0).equals("bob-session")?"bob":"alice"));
        var provider=mock(ObjectProvider.class);workspace=new AgentWorkspaceService(sessions,users,provider,jdbc,new DataSourceTransactionManager(source),directory.toString(),1024,2048);workspace.validate();
    }
    WorkbenchSessionApi.File upload(String request,String name,String text){return workspace.upload(alice,"s1",request,name,text.getBytes(StandardCharsets.UTF_8),"uploads");}
    @Test void privateUploadIsIdempotentAndCannotBeReadThroughAnotherSessionOrAccount(){var file=upload("upload-1","notes.md","PRIVATE_NOTES");assertThat(upload("upload-1","notes.md","PRIVATE_NOTES")).isEqualTo(file);assertThat(workspace.readText(alice,"s1",file.id())).isEqualTo("PRIVATE_NOTES");assertThatThrownBy(()->workspace.bytes(bob,"bob-session",file.id())).hasMessageContaining("404");assertThatThrownBy(()->workspace.bytes(alice,"s2",file.id())).hasMessageContaining("404");assertThatThrownBy(()->upload("upload-1","notes.md","different")).hasMessageContaining("409");assertThat(jdbc.queryForList("SELECT * FROM agent_workspace_audit").toString()).doesNotContain("PRIVATE_NOTES");}
    @Test void filenamesMimeSniffingQuotaAndChangedDiskContentAreEnforced()throws Exception{
        assertThatThrownBy(()->upload("bad","../notes.md","text")).hasMessageContaining("400");assertThatThrownBy(()->upload("bad2","fake.png","not png")).hasMessageContaining("415");assertThatThrownBy(()->upload("big","big.txt","x".repeat(1025))).hasMessageContaining("400");
        var file=upload("one","one.txt","x".repeat(1024));upload("two","two.txt","y".repeat(1024));assertThatThrownBy(()->upload("three","three.txt","z")).hasMessageContaining("413");
        Files.writeString(directory.resolve("users/1/"+file.id()+".bin"),"changed");assertThatThrownBy(()->workspace.bytes(alice,"s1",file.id())).hasMessageContaining("409");
    }
    @Test void htmlAndSvgArePlainTextAndGeneratedJsonIsValidated(){var file=upload("html","page.html","<script>alert(1)</script>");assertThat(file.contentType()).startsWith("text/plain");assertThat(workspace.readText(alice,"s1",file.id())).contains("<script>");assertThatThrownBy(()->workspace.createArtifact(alice,"s1","artifact","bad.json","{bad}")).hasMessageContaining("400");assertThat(workspace.createArtifact(alice,"s1","csv","data.csv","name,count\na,2").folder()).isEqualTo("artifacts");}
    @Test void removalIsIdempotentAndDoesNotEraseAForkedReference(){var file=upload("one","one.md","hello");jdbc.update("INSERT INTO agent_workspace_file_ref(user_id,session_id,file_id) VALUES(?,?,?)",1,"forked",file.id());workspace.remove(alice,"s1",file.id(),"remove-1");workspace.remove(alice,"s1",file.id(),"remove-1");assertThat(workspace.files(alice,"s1")).isEmpty();assertThat(workspace.readText(alice,"forked",file.id())).isEqualTo("hello");assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_workspace_audit WHERE action='FILE_UNLINKED'",Integer.class)).isEqualTo(1);}
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
        assertThat(workspace.files(alice,"s1")).isEmpty();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_workspace_audit",Integer.class)).isZero();
        try(var paths=Files.walk(directory)){assertThat(paths.filter(Files::isRegularFile).count()).isZero();}
    }
    @Test void previewLimitIsConfigurableAndJsonValidationCannotBeBypassedByFilenameCase(){org.springframework.test.util.ReflectionTestUtils.setField(workspace,"previewBytes",4);var file=upload("text","text.txt","123456");assertThat(workspace.readText(alice,"s1",file.id())).startsWith("1234\n[内容已").doesNotContain("123456");assertThat(workspace.limits().get("previewBytes")).isEqualTo(4);assertThatThrownBy(()->workspace.createArtifact(alice,"s1","json","bad.JSON","{} trailing")).hasMessageContaining("400");}
    @Test void auditFailureRollsBackMetadataAndRemovesTheNewPrivateFile()throws Exception{jdbc.execute("ALTER TABLE agent_workspace_audit ADD CONSTRAINT reject_upload CHECK(action<>'FILE_CREATED')");assertThatThrownBy(()->upload("one","one.md","PRIVATE")).isInstanceOf(org.springframework.dao.DataAccessException.class);assertThat(workspace.files(alice,"s1")).isEmpty();try(var paths=Files.walk(directory)){assertThat(paths.filter(Files::isRegularFile).count()).isZero();}}
    @Test void forkCopiesOnlyTheFinishedPrefixAndOnlyFilesPresentAtThatTime(){
        var user=new ChatMessageResponse();user.setId(1L);user.setRole("user");user.setContent("first");var answer=new ChatMessageResponse();answer.setId(2L);answer.setRole("assistant");answer.setContent("answer");answer.setCreatedAt("2026-10-17 10:00:00");var later=new ChatMessageResponse();later.setId(3L);later.setRole("user");later.setContent("later");when(sessions.listMessages("alice","s1")).thenReturn(List.of(user,answer,later));var target=new ChatSessionResponse();target.setSessionId("forked");when(sessions.createSession("alice")).thenReturn(target);
        var early=upload("early","early.txt","early");var late=upload("late","late.txt","late");jdbc.update("UPDATE agent_workspace_file_ref SET created_at=? WHERE file_id=?",LocalDateTime.of(2026,10,17,9,0),early.id());jdbc.update("UPDATE agent_workspace_file_ref SET created_at=? WHERE file_id=?",LocalDateTime.of(2026,10,17,11,0),late.id());
        assertThat(workspace.fork(alice,"s1",2,"fork-1")).isEqualTo("forked");assertThat(workspace.fork(alice,"s1",2,"fork-1")).isEqualTo("forked");verify(sessions,times(1)).appendUserMessage(new TenantContext(1L,"alice"),"forked","first");verify(sessions,never()).appendUserMessage(any(),anyString(),eq("later"));assertThat(workspace.files(alice,"forked")).extracting(WorkbenchSessionApi.File::id).containsExactly(early.id());
    }
}
