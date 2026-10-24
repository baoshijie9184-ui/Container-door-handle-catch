package com.ruanzhu.doorhandle.module.ai.evolution;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.transaction.support.TransactionTemplate;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;

class SkillDownloadLeasesTest {
    @TempDir Path root;
    JdbcTemplate jdbc;DriverManagerDataSource source;SkillLinkStorage storage;SkillDownloadLeases leases;TransactionTemplate tx;
    @BeforeEach void setup()throws Exception{
        boolean mysql=System.getProperty("agent.skill.mysql-file")!=null;
        if(mysql){var config=new ObjectMapper().readTree(Files.readString(Path.of(System.getProperty("agent.skill.mysql-file"))));String database=config.path("database").asText(),url=config.path("url").asText();if(!database.matches("doorhandle_skill_verify_[a-f0-9]{10}")||!url.startsWith("jdbc:mysql://127.0.0.1:3306/"+database+"?"))throw new SecurityException("Only a dedicated local Skill verification database is allowed");source=new DriverManagerDataSource(url,config.path("username").asText(),config.path("password").asText());}
        else source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=5000","sa","");
        jdbc=new JdbcTemplate(source);tx=new TransactionTemplate(new DataSourceTransactionManager(source));
        if(mysql)for(String table:List.of("agent_skill_download_event","agent_skill_download_lease","agent_skill_download_owner","agent_skill_download"))jdbc.execute("DROP TABLE IF EXISTS "+table);
        jdbc.execute("CREATE TABLE agent_skill_download(download_id VARCHAR(64) PRIMARY KEY,owner_user_id BIGINT,status VARCHAR(32),error_code VARCHAR(80),updated_at DATETIME)");
        String ddl=Files.readString(Path.of("../sql/mysql/migration-V46-skill-download-leases.sql"));
        if(!mysql)ddl=ddl.replace(" COLLATE utf8mb4_bin","").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","").replaceAll("(?m)^\\s*(?:UNIQUE )?KEY .*\\n","").replaceAll(",\\s*\\)","\n)");
        for(String statement:ddl.split(";"))if(!statement.isBlank())jdbc.execute(statement);
        storage=new SkillLinkStorage(jdbc,new ObjectMapper(),root.toString());leases=new SkillDownloadLeases(jdbc,storage);
    }
    String reserve(){String id="download-"+UUID.randomUUID();tx.executeWithoutResult(s->{leases.lock(1);jdbc.update("INSERT INTO agent_skill_download VALUES(?,1,'DOWNLOADING',NULL,CURRENT_TIMESTAMP)",id);leases.reserve(1,id);});return id;}
    void expired(String id){jdbc.update("UPDATE agent_skill_download_lease SET lease_expires_at=TIMESTAMPADD(MINUTE,-1,CURRENT_TIMESTAMP) WHERE download_id=?",id);tx.executeWithoutResult(s->{leases.lock(1);leases.expire(1,id);});}
    @Test void separateConnectionsCannotReserveBeyondTheSameAccountQuota()throws Exception{
        var ready=new CountDownLatch(2);var start=new CountDownLatch(1);var accepted=new AtomicInteger();var denied=new AtomicInteger();var pool=Executors.newFixedThreadPool(2);var futures=new ArrayList<Future<?>>();
        try{for(int i=0;i<2;i++)futures.add(pool.submit(()->{ready.countDown();try{start.await();var connection=new JdbcTemplate(source);var other=new SkillDownloadLeases(connection,storage);var transaction=new TransactionTemplate(new DataSourceTransactionManager(source));transaction.executeWithoutResult(s->{other.lock(1);other.capacity(1,SkillDownloadLeases.PACKAGE_BYTES);String id="download-"+UUID.randomUUID();connection.update("INSERT INTO agent_skill_download VALUES(?,1,'DOWNLOADING',NULL,CURRENT_TIMESTAMP)",id);other.reserve(1,id);});accepted.incrementAndGet();}catch(org.springframework.web.server.ResponseStatusException expected){denied.incrementAndGet();}catch(InterruptedException e){Thread.currentThread().interrupt();throw new RuntimeException(e);}}));assertThat(ready.await(5,TimeUnit.SECONDS)).isTrue();start.countDown();for(var f:futures)f.get(10,TimeUnit.SECONDS);assertThat(accepted).hasValue(1);assertThat(denied).hasValue(1);assertThat(leases.held(1)).hasSize(1);}finally{pool.shutdownNow();}
    }
    @Test void expiredRunningProcessKeepsReservationAndRejectsLateSuccess(){String id=reserve();tx.executeWithoutResult(s->{leases.lock(1);assertThat(leases.claim(1,id,"worker-a")).isTrue();});expired(id);assertThat(jdbc.queryForObject("SELECT status FROM agent_skill_download WHERE download_id=?",String.class,id)).isEqualTo("NEEDS_REVIEW");assertThat(leases.held(1)).containsEntry(id,SkillDownloadLeases.PACKAGE_BYTES);assertThatThrownBy(()->tx.executeWithoutResult(s->{leases.lock(1);leases.seal(1,id,"worker-a");})).hasMessageContaining("不能导入");}
    @Test void abandonedUnstartedReservationCanReleaseButExistingBytesRemainCharged()throws Exception{String id=reserve();Path directory=storage.directory(1,id);Files.createDirectories(directory);Files.write(directory.resolve("partial.txt"),new byte[100]);expired(id);assertThat(leases.held(1)).isEmpty();assertThat(leases.charged(1)).isEqualTo(100);assertThat(jdbc.queryForObject("SELECT exit_verified FROM agent_skill_download_lease WHERE download_id=?",Boolean.class,id)).isTrue();}
    @Test void partialPackageIsChargedOnceAtItsBound()throws Exception{String id=reserve();Path directory=storage.directory(1,id);Files.createDirectories(directory);Files.write(directory.resolve("partial.txt"),new byte[100]);assertThat(leases.charged(1)).isEqualTo(SkillDownloadLeases.PACKAGE_BYTES);}
    @Test void oneWorkerClaimsAndOnlyItsVerifiedExitCanRelease(){String id=reserve();tx.executeWithoutResult(s->{leases.lock(1);assertThat(leases.claim(1,id,"worker-a")).isTrue();assertThat(leases.claim(1,id,"worker-b")).isFalse();leases.fail(1,id,"worker-b",true,"FORGED_EXIT");});assertThat(leases.held(1)).containsKey(id);tx.executeWithoutResult(s->{leases.lock(1);leases.fail(1,id,"worker-a",false,"DOWNLOAD_EXIT_UNVERIFIED");});assertThat(leases.held(1)).containsKey(id);tx.executeWithoutResult(s->{leases.lock(1);leases.fail(1,id,"worker-a",true,"VERIFIED_EXIT");});assertThat(leases.held(1)).isEmpty();}
    @Test void legacyUnreceiptedExecutionRetainsFullReservation(){String id="download-"+UUID.randomUUID();jdbc.update("INSERT INTO agent_skill_download VALUES(?,1,'NEEDS_REVIEW','DOWNLOAD_EXIT_UNVERIFIED',CURRENT_TIMESTAMP)",id);assertThat(leases.held(1)).containsEntry(id,SkillDownloadLeases.PACKAGE_BYTES);}
    @Test void auditFailureRollsBackTheClaim(){String id=reserve();jdbc.execute("DROP TABLE agent_skill_download_event");assertThatThrownBy(()->tx.executeWithoutResult(s->{leases.lock(1);leases.claim(1,id,"worker-a");})).isInstanceOf(org.springframework.dao.DataAccessException.class);assertThat(jdbc.queryForObject("SELECT status FROM agent_skill_download_lease WHERE download_id=?",String.class,id)).isEqualTo("RESERVED");}
}
