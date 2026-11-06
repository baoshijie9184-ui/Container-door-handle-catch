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
        if(mysql)source=com.ruanzhu.doorhandle.module.ai.EcsIsolatedMysql.open(
                System.getProperty("agent.skill.mysql-file"), "doorhandle_skill_verify_");
        else source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=5000","sa","");
        jdbc=new JdbcTemplate(source);tx=new TransactionTemplate(new DataSourceTransactionManager(source));
        if(mysql)for(String table:List.of("audit_event","workflow_instance","scheduled_plan","runtime_state"))jdbc.execute("DROP TABLE IF EXISTS "+table);
        com.ruanzhu.doorhandle.module.ai.testsupport.CompactWorkflowFixture.install(jdbc);
        storage=new SkillLinkStorage(jdbc,new ObjectMapper(),root.toString());leases=new SkillDownloadLeases(jdbc,storage);
    }
    void createDownload(SkillDownloadStore store,String id){store.create(1,id,id,"a".repeat(64),"https://github.com/fixtures/skills/tree/main/reader","INSPECTOR",null,null);}
    String reserve(){String id="download-"+UUID.randomUUID();tx.executeWithoutResult(s->{leases.lock(1);createDownload(storage.downloads(),id);leases.reserve(1,id);});return id;}
    void expired(String id){jdbc.update("UPDATE workflow_instance SET execution_deadline=TIMESTAMPADD(MINUTE,-1,UTC_TIMESTAMP(6)),lease_expires_at=CASE WHEN claim_token IS NULL THEN NULL ELSE TIMESTAMPADD(MINUTE,-1,UTC_TIMESTAMP(6)) END WHERE kind='SKILL_DOWNLOAD' AND workflow_id=?",id);tx.executeWithoutResult(s->{leases.lock(1);leases.expire(1,id);});}
    @Test void separateConnectionsCannotReserveBeyondTheSameAccountQuota()throws Exception{
        var ready=new CountDownLatch(2);var start=new CountDownLatch(1);var accepted=new AtomicInteger();var denied=new AtomicInteger();var pool=Executors.newFixedThreadPool(2);var futures=new ArrayList<Future<?>>();
        try{for(int i=0;i<2;i++)futures.add(pool.submit(()->{ready.countDown();try{start.await();var connection=new JdbcTemplate(source);var other=new SkillDownloadLeases(connection,storage);var transaction=new TransactionTemplate(new DataSourceTransactionManager(source));transaction.executeWithoutResult(s->{other.lock(1);other.capacity(1,SkillDownloadLeases.PACKAGE_BYTES);String id="download-"+UUID.randomUUID();createDownload(new SkillDownloadStore(connection,new ObjectMapper()),id);other.reserve(1,id);});accepted.incrementAndGet();}catch(org.springframework.web.server.ResponseStatusException expected){denied.incrementAndGet();}catch(InterruptedException e){Thread.currentThread().interrupt();throw new RuntimeException(e);}}));assertThat(ready.await(5,TimeUnit.SECONDS)).isTrue();start.countDown();for(var f:futures)f.get(10,TimeUnit.SECONDS);assertThat(accepted).hasValue(1);assertThat(denied).hasValue(1);assertThat(leases.held(1)).hasSize(1);}finally{pool.shutdownNow();}
    }
    @Test void expiredRunningProcessKeepsReservationAndRejectsLateSuccess(){String id=reserve();tx.executeWithoutResult(s->{leases.lock(1);assertThat(leases.claim(1,id,"worker-a")).isTrue();});expired(id);assertThat(jdbc.queryForObject("SELECT status FROM workflow_instance WHERE kind='SKILL_DOWNLOAD' AND workflow_id=?",String.class,id)).isEqualTo("NEEDS_REVIEW");assertThat(leases.held(1)).containsEntry(id,SkillDownloadLeases.PACKAGE_BYTES);assertThatThrownBy(()->tx.executeWithoutResult(s->{leases.lock(1);leases.seal(1,id,"worker-a");})).hasMessageContaining("租约");}
    @Test void abandonedUnstartedReservationCanReleaseButExistingBytesRemainCharged()throws Exception{String id=reserve();Path directory=storage.directory(1,id);Files.createDirectories(directory);Files.write(directory.resolve("partial.txt"),new byte[100]);expired(id);assertThat(leases.held(1)).isEmpty();assertThat(leases.charged(1)).isEqualTo(100);assertThat(jdbc.queryForObject("SELECT exit_verified FROM workflow_instance WHERE kind='SKILL_DOWNLOAD' AND workflow_id=?",Boolean.class,id)).isTrue();}
    @Test void partialPackageIsChargedOnceAtItsBound()throws Exception{String id=reserve();Path directory=storage.directory(1,id);Files.createDirectories(directory);Files.write(directory.resolve("partial.txt"),new byte[100]);assertThat(leases.charged(1)).isEqualTo(SkillDownloadLeases.PACKAGE_BYTES);}
    @Test void oneWorkerClaimsAndOnlyItsVerifiedExitCanRelease(){String id=reserve();tx.executeWithoutResult(s->{leases.lock(1);assertThat(leases.claim(1,id,"worker-a")).isTrue();assertThat(leases.claim(1,id,"worker-b")).isFalse();leases.fail(1,id,"worker-b",true,"FORGED_EXIT");});assertThat(leases.held(1)).containsKey(id);tx.executeWithoutResult(s->{leases.lock(1);leases.fail(1,id,"worker-a",false,"DOWNLOAD_EXIT_UNVERIFIED");});assertThat(leases.held(1)).containsKey(id);tx.executeWithoutResult(s->{leases.lock(1);leases.fail(1,id,"worker-a",true,"VERIFIED_EXIT");});assertThat(leases.held(1)).isEmpty();}
    @Test void legacyUnreceiptedExecutionRetainsFullReservation(){String id="download-"+UUID.randomUUID();tx.executeWithoutResult(s->{leases.lock(1);createDownload(storage.downloads(),id);});jdbc.update("UPDATE workflow_instance SET status='NEEDS_REVIEW',error_code='DOWNLOAD_EXIT_UNVERIFIED' WHERE kind='SKILL_DOWNLOAD' AND workflow_id=?",id);assertThat(leases.held(1)).containsEntry(id,SkillDownloadLeases.PACKAGE_BYTES);}
    @Test void auditFailureRollsBackTheClaim(){String id=reserve();jdbc.execute("DROP TABLE audit_event");assertThatThrownBy(()->tx.executeWithoutResult(s->{leases.lock(1);leases.claim(1,id,"worker-a");})).isInstanceOf(org.springframework.dao.DataAccessException.class);assertThat(jdbc.queryForObject("SELECT execution_state FROM workflow_instance WHERE kind='SKILL_DOWNLOAD' AND workflow_id=?",String.class,id)).isEqualTo("RESERVED");}
}
