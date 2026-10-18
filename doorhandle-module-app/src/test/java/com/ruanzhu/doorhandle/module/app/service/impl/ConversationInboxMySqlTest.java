package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zaxxer.hikari.HikariDataSource;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.UUID;
import static org.assertj.core.api.Assertions.assertThat;

/** Explicit native SQL/locking verification on a random, restricted test database. */
@Timeout(90)
@EnabledIfEnvironmentVariable(named="DOORHANDLE_INBOX_MYSQL_CONFIG",matches=".+")
class ConversationInboxMySqlTest extends ConversationInboxServiceTest {
    @Override java.time.Duration executionWait(){return java.time.Duration.ofSeconds(15);}
    @Override javax.sql.DataSource source(){
        try{
            var project=Path.of("..").toAbsolutePath().normalize();
            var file=Path.of(System.getenv("DOORHANDLE_INBOX_MYSQL_CONFIG")).toAbsolutePath().normalize();
            assertThat(file.startsWith(project.resolve("work"))).isTrue();
            var config=new ObjectMapper().readTree(Files.readString(file));
            String database=config.path("database").asText(),username=config.path("username").asText();
            assertThat(database).matches("doorhandle_wb_verify_[a-f0-9]{10}");
            assertThat(username).isEqualTo("wb_verify_"+database.substring(database.lastIndexOf('_')+1));
            String url=config.path("url").asText();
            assertThat(url).startsWith("jdbc:mysql://127.0.0.1:").contains("/"+database+"?");
            var pool=new HikariDataSource();pool.setJdbcUrl(url+"&rewriteBatchedStatements=true");pool.setUsername(username);pool.setPassword(config.path("password").asText());
            pool.setMaximumPoolSize(6);pool.setConnectionInitSql("SET time_zone='+08:00'");pool.setConnectionTimeout(10000);
            try{
                var db=new JdbcTemplate(pool);
                assertThat(db.queryForObject("SELECT DATABASE()",String.class)).isEqualTo(database);
                assertThat(db.queryForObject("SELECT @@session.time_zone",String.class)).isEqualTo("+08:00");
                for(String table:new String[]{"agent_conversation_input_audit","agent_conversation_input","agent_conversation_input_owner"})db.execute("DROP TABLE IF EXISTS "+table);
                for(String name:new String[]{"migration-V36-conversation-inbox.sql","migration-V39-conversation-owner-dispatch.sql"}){
                    String sql=Files.readString(Path.of("../sql/mysql/"+name)).replaceAll("(?m)^--.*$", "");
                    for(String statement:sql.split(";"))if(!statement.isBlank())db.execute(statement);
                }
                return pool;
            }catch(Throwable error){pool.close();throw error;}
        }catch(Exception error){throw new IllegalStateException("Cannot initialize the isolated inbox MySQL fixture",error);}
    }
    @Test void nativeDispatchQueriesUseTheOwnerIndexWithoutSortingTheBacklog()throws Exception{
        var parameters=new ArrayList<Object[]>();
        for(int i=0;i<4000;i++)parameters.add(new Object[]{UUID.randomUUID().toString(),1L+i%4,Timestamp.valueOf(LocalDateTime.now().plusHours(1))});
        jdbc.batchUpdate("INSERT INTO agent_conversation_input(input_id,user_id,username,session_id,mode,requested_mode,status,content,content_sha256,expires_at) VALUES(?,?,'fixture','fixture','NEXT_TURN','NEXT_TURN','COMPLETED','','"+"a".repeat(64)+"',?)",parameters);
        for(int i=0;i<16;i++)enqueue("queued-"+i);
        jdbc.execute("ANALYZE TABLE agent_conversation_input");
        var owners=jdbc.queryForList("EXPLAIN SELECT DISTINCT user_id FROM agent_conversation_input WHERE status='QUEUED' AND user_id>0 AND user_id<=10000 ORDER BY user_id LIMIT 32");
        var inputs=jdbc.queryForList("EXPLAIN SELECT * FROM agent_conversation_input WHERE user_id=1 AND status='QUEUED' ORDER BY id LIMIT 16");
        var out=Path.of("../work/inbox-mysql-query-plans.json");
        Files.writeString(out,new ObjectMapper().writeValueAsString(java.util.Map.of("owners",owners,"inputs",inputs,"version",jdbc.queryForObject("SELECT VERSION()",String.class))));
        for(var rows:java.util.List.of(owners,inputs))assertThat(rows).singleElement().satisfies(row->{
            assertThat(String.valueOf(row.get("possible_keys"))).contains("idx_conversation_input_dispatch_owner");
            assertThat(row.get("key")).isNotNull();assertThat(String.valueOf(row.get("type"))).isIn("ref","range");
            assertThat(((Number)row.get("rows")).longValue()).isLessThanOrEqualTo(64);
            assertThat(String.valueOf(row.get("Extra"))).doesNotContain("Using filesort");
        });
    }
}
