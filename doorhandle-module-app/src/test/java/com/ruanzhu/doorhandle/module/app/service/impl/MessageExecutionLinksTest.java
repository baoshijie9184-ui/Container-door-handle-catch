package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.module.app.dto.chat.ChatMessageResponse;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

/** H2 MySQL-mode SQL boundary tests; not a substitute for a real MySQL migration rehearsal. */
class MessageExecutionLinksTest {
    JdbcTemplate jdbc;
    MessageExecutionLinks links;
    TenantContext alice=new TenantContext(1L,"alice");
    @BeforeEach void database()throws Exception{
        jdbc=new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa",""));
        jdbc.execute("CREATE TABLE chat_session(session_id VARCHAR(128) PRIMARY KEY,user_id BIGINT)");
        jdbc.execute("CREATE TABLE chat_message(id BIGINT PRIMARY KEY,session_id VARCHAR(128),role VARCHAR(20),message_type VARCHAR(20))");
        jdbc.execute("CREATE TABLE agent_run(run_id VARCHAR(36) PRIMARY KEY,user_id BIGINT,session_id VARCHAR(128),entry_point VARCHAR(20),status VARCHAR(20))");
        try(var input=getClass().getResourceAsStream("/db/migration-V66-chat-message-execution.sql")){
            String ddl=new String(Objects.requireNonNull(input).readAllBytes(),StandardCharsets.UTF_8);
            jdbc.execute(ddl.replaceAll(" COLLATE(?:=| )utf8mb4_bin","").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",""));
        }
        jdbc.update("INSERT INTO chat_session VALUES ('s1',1),('s2',2),('s3',1)");
        jdbc.update("INSERT INTO chat_message VALUES (11,'s1','assistant','TEXT'),(12,'s1','user','TEXT'),(13,'s2','assistant','TEXT'),(14,'s3','assistant','TEXT'),(15,'s1','assistant','TEXT')");
        jdbc.update("INSERT INTO agent_run VALUES ('run-1',1,'s1','CHAT','COMPLETED'),('run-2',2,'s2','AGUI','COMPLETED'),('run-3',1,'s3','CHAT','COMPLETED'),('run-4',1,'s1','AGUI','COMPLETED')");
        links=new MessageExecutionLinks(jdbc);
    }
    ChatMessageResponse message(long id,String session){var m=new ChatMessageResponse();m.setId(id);m.setSessionId(session);m.setRole("assistant");m.setMessageType("TEXT");m.setContent("正文保持原样");return m;}
    int count(){return jdbc.queryForObject("SELECT COUNT(*) FROM agent_message_execution",Integer.class);}

    @Test void aFreshServiceRestoresTheExactPersistedMessageLink(){
        links.bind(alice,"s1",11L,"run-1");assertThat(count()).isEqualTo(1);
        var saved=message(11,"s1");new MessageExecutionLinks(jdbc).hydrate(alice,"s1",List.of(saved));
        assertThat(saved.getRunId()).isEqualTo("run-1");assertThat(saved.getContent()).isEqualTo("正文保持原样");
    }
    @Test void rejectsCrossAccountCrossSessionAndUserMessages(){
        links.bind(alice,"s1",11L,"run-2");links.bind(alice,"s1",11L,"run-3");
        links.bind(alice,"s2",13L,"run-2");links.bind(alice,"s1",12L,"run-1");links.bind(alice,"s1",14L,"run-1");
        assertThat(count()).isZero();
    }
    @Test void doesNotAssociateARunningOrSpecialistRunButAllowsASavedWaitingReply(){
        jdbc.update("UPDATE agent_run SET status='RUNNING' WHERE run_id='run-1'");links.bind(alice,"s1",11L,"run-1");assertThat(count()).isZero();
        jdbc.update("UPDATE agent_run SET status='COMPLETED',entry_point='CHILD' WHERE run_id='run-1'");links.bind(alice,"s1",11L,"run-1");assertThat(count()).isZero();
        jdbc.update("UPDATE agent_run SET status='INTERRUPTED',entry_point='AGUI' WHERE run_id='run-1'");links.bind(alice,"s1",11L,"run-1");assertThat(count()).isEqualTo(1);
    }
    @Test void repeatedBindingsNeverReassignAMessageOrShareOneRunBetweenReplies(){
        links.bind(alice,"s1",11L,"run-1");links.bind(alice,"s1",11L,"run-1");links.bind(alice,"s1",11L,"run-4");links.bind(alice,"s1",15L,"run-1");
        assertThat(count()).isEqualTo(1);assertThat(jdbc.queryForObject("SELECT run_id FROM agent_message_execution WHERE message_id=11",String.class)).isEqualTo("run-1");
    }
    @Test void historyReadsCheckOwnershipAndDoNotGuessFromAnotherMessage(){
        links.bind(alice,"s1",11L,"run-1");
        var wrong=message(11,"s1");links.hydrate(new TenantContext(2L,"bob"),"s1",List.of(wrong));assertThat(wrong.getRunId()).isNull();
        var legacy=message(15,"s1");links.hydrate(alice,"s1",List.of(legacy));assertThat(legacy.getRunId()).isNull();
        jdbc.update("UPDATE chat_session SET user_id=2 WHERE session_id='s1'");links.hydrate(alice,"s1",List.of(wrong));assertThat(wrong.getRunId()).isNull();
    }
    @Test void missingMigrationKeepsTheMessageUsableAndDoesNotThrow(){
        jdbc.execute("DROP TABLE agent_message_execution");var m=message(11,"s1");
        assertThatCode(()->{links.hydrate(alice,"s1",List.of(m));links.bind(alice,"s1",11L,"run-1");}).doesNotThrowAnyException();
        assertThat(m.getContent()).isEqualTo("正文保持原样");assertThat(m.getRunId()).isNull();
    }
    @Test void batchesVisibleMessageIdsInsteadOfQueryingEveryBubble(){
        links.bind(alice,"s1",11L,"run-1");var spy=org.mockito.Mockito.spy(jdbc);var reader=new MessageExecutionLinks(spy);
        var page=new ArrayList<ChatMessageResponse>();for(long id=11;id<=311;id++)page.add(message(id,"s1"));reader.hydrate(alice,"s1",page);
        assertThat(page.get(0).getRunId()).isEqualTo("run-1");
        assertThat(org.mockito.Mockito.mockingDetails(spy).getInvocations().stream().filter(inv->inv.getMethod().getName().equals("queryForList")).count()).isEqualTo(2);
    }
    @Test void archiveAndRuntimeMigrationCopiesMatchAndDoNotBackfillHistory()throws Exception{
        String archive=Files.readString(Path.of("../sql/mysql/migration-V66-chat-message-execution.sql"));
        try(var input=getClass().getResourceAsStream("/db/migration-V66-chat-message-execution.sql")){
            assertThat(new String(Objects.requireNonNull(input).readAllBytes(),StandardCharsets.UTF_8)).isEqualTo(archive);
        }
        assertThat(archive).contains("CREATE TABLE IF NOT EXISTS","idx_message_execution_owner").doesNotContain("INSERT INTO","UPDATE chat_message","ALTER TABLE chat_message");
    }
}
