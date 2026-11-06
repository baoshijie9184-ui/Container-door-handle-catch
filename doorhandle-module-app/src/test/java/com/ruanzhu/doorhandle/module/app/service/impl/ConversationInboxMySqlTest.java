package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowPayloads;
import com.ruanzhu.doorhandle.module.app.testsupport.CompactMySqlFixture;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.UUID;
import static org.assertj.core.api.Assertions.assertThat;

/** Explicit native SQL/locking verification on a random, restricted test database. */
@Timeout(90)
@EnabledIfEnvironmentVariable(named="DOORHANDLE_INBOX_MYSQL_CONFIG",matches=".+")
class ConversationInboxMySqlTest extends ConversationInboxServiceTest {
    private CompactMySqlFixture fixture;
    @Override java.time.Duration executionWait(){return java.time.Duration.ofSeconds(15);}
    @Override void installSchema()throws Exception{fixture=new CompactMySqlFixture(jdbc.getDataSource());}
    @Override void cleanupSchema(){if(fixture!=null)fixture.close();}
    @Override javax.sql.DataSource source(){
        try{
            var project=Path.of("..").toAbsolutePath().normalize();
            var file=Path.of(System.getenv("DOORHANDLE_INBOX_MYSQL_CONFIG")).normalize();
            assertThat(file.startsWith(project.resolve("work"))).isTrue();
            var pool=com.ruanzhu.doorhandle.module.app.EcsIsolatedMysql.pool(
                    file.toString(), "doorhandle_wb_verify_", "wb_verify_", 6);
            pool.setJdbcUrl(pool.getJdbcUrl()+"&rewriteBatchedStatements=true");
            pool.setConnectionTimeout(10000);
            try{
                var db=new JdbcTemplate(pool);
                assertThat(db.queryForObject("SELECT @@session.time_zone",String.class)).isEqualTo("+08:00");
                return pool;
            }catch(Throwable error){pool.close();throw error;}
        }catch(Exception error){throw new IllegalStateException("Cannot initialize the isolated inbox MySQL fixture",error);}
    }
    @Test void nativeDispatchQueriesUseTheOwnerIndexWithoutSortingTheBacklog()throws Exception{
        var parameters=new ArrayList<Object[]>();
        String digest=java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(new byte[0]));
        String payload=new ObjectMapper().writeValueAsString(new WorkflowPayloads.ConversationInputV1("fixture","NEXT_TURN","NEXT_TURN","CHAT","",digest));
        for(int i=0;i<4000;i++){
            String id=UUID.randomUUID().toString();long owner=1L+i%4;
            parameters.add(new Object[]{id,"OWNER:"+owner,id,digest,owner,owner,payload});
        }
        jdbc.batchUpdate("INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,session_id,status,payload_version,payload_json,expires_at,finished_at) VALUES(?,'CONVERSATION_INPUT',?,?,?,?,?,'fixture','COMPLETED',1,?,UTC_TIMESTAMP(6)+INTERVAL 1 HOUR,UTC_TIMESTAMP(6))",parameters);
        for(int i=0;i<16;i++)enqueue("queued-"+i);
        jdbc.execute("ANALYZE TABLE workflow_instance");
        var owners=jdbc.queryForList("EXPLAIN SELECT DISTINCT owner_user_id FROM workflow_instance WHERE kind='CONVERSATION_INPUT' AND status='QUEUED' AND owner_user_id>0 AND owner_user_id<=10000 ORDER BY owner_user_id LIMIT 32");
        var inputs=jdbc.queryForList("EXPLAIN SELECT * FROM workflow_instance WHERE kind='CONVERSATION_INPUT' AND owner_user_id=1 AND status IN ('QUEUED') ORDER BY id ASC LIMIT 16");
        var out=Path.of("../work/inbox-mysql-query-plans.json");
        Files.writeString(out,new ObjectMapper().writeValueAsString(java.util.Map.of("owners",owners,"inputs",inputs,"version",jdbc.queryForObject("SELECT VERSION()",String.class))));
        for(var rows:java.util.List.of(owners,inputs))assertThat(rows).singleElement().satisfies(row->{
            assertThat(String.valueOf(row.get("possible_keys"))).contains("ix_workflow_dispatch_owner");
            assertThat(row.get("key")).isNotNull();assertThat(String.valueOf(row.get("type"))).isIn("ref","range");
            assertThat(((Number)row.get("rows")).longValue()).isLessThanOrEqualTo(64);
            assertThat(String.valueOf(row.get("Extra"))).doesNotContain("Using filesort");
        });
    }
}
