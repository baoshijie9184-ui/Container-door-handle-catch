package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.detection.testsupport.FeatureMySql;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import javax.sql.DataSource;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;

@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@EnabledIfSystemProperty(named="doorhandle.digest.mysql.config",matches=".+")
class QualityDigestMySqlTest {
    AnnotationConfigApplicationContext context;JdbcTemplate jdbc;QualityDigestService service;Directory directory;
    final ZoneId beijing=ZoneId.of("Asia/Shanghai");
    @BeforeAll void start()throws Exception {
        context=new AnnotationConfigApplicationContext();
        context.getEnvironment().getPropertySources().addFirst(new org.springframework.core.env.MapPropertySource("digest-test",Map.of("app.quality-automation.enabled","true")));
        context.register(Config.class,QualityDigestService.class,ReportDocumentRenderer.class);context.refresh();
        jdbc=context.getBean(JdbcTemplate.class);service=context.getBean(QualityDigestService.class);directory=context.getBean(Directory.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",Long.class)).as("separate empty ECS digest schema").isZero();
        FeatureMySql.migrate(context.getBean(DataSource.class),"compact/baseline/10-core.sql");
        FeatureMySql.migrate(context.getBean(DataSource.class),"compact/baseline/30-operations.sql");
        com.ruanzhu.doorhandle.module.detection.support.FixtureSourceSnapshot.installLegacyClockGuards(jdbc,java.nio.file.Path.of("../sql/mysql/compact/baseline"));
    }
    @AfterAll void close(){if(context!=null)context.close();}
    @BeforeEach void reset(){FeatureMySql.clear(jdbc,"audit_event","workflow_instance","scheduled_plan","runtime_state","detection_task");directory.roles.put(3L,true);directory.account.set(new Identity(3,"boss",true));directory.onCurrent=null;}
    String key(){return UUID.randomUUID().toString();}
    Map<String,Object> schedule(boolean enabled){return service.save(null,new QualityDigestService.Save("每日质检统计","0 0 8 * * *",enabled,0,key()));}
    String id(Map<String,Object> row){return row.get("schedule_id").toString();}
    int version(Map<String,Object> row){return ((Number)row.get("version")).intValue();}
    LocalDate yesterday(){return LocalDate.now(beijing).minusDays(1);}
    String run(Map<String,Object> schedule,LocalDate date,String request){return service.generate(id(schedule),new QualityDigestService.Generate(date,version(schedule),request)).get("runId").toString();}
    LocalDateTime start(LocalDate date){return date.atStartOfDay(beijing).withZoneSameInstant(ZoneOffset.UTC).toLocalDateTime();}
    void task(String id,LocalDateTime created,int count){jdbc.update("INSERT INTO detection_task(task_id,status,created_at,total_images,successful_images,failed_images,defect_count,review_status) VALUES(?,'COMPLETED',?,?,?,0,2,'PENDING')",id,created,count,count);}
    @Test void generatedDigestUsesBeijingCreationDayAndRetainsImmutableSnapshot(){var schedule=schedule(false);LocalDate date=yesterday();task("inside",start(date).plusHours(1),8);task("before",start(date).minusSeconds(1),99);task("after",start(date.plusDays(1)),77);String run=run(schedule,date,key());service.pump();var records=service.runs(id(schedule));assertThat(records).hasSize(1);assertThat(records.get(0).get("status")).isEqualTo("COMPLETED");var file=service.download(run,"md");String text=new String(file.bytes(),StandardCharsets.UTF_8);assertThat(text).contains("图片数：8","任务数：1","登记待复核：1","模型缺陷目标：2");task("later",start(date).plusHours(2),100);assertThat(new String(service.download(run,"md").bytes(),StandardCharsets.UTF_8)).isEqualTo(text);}
    @Test void mysqlJsonFormattingDoesNotBreakHashButContentTamperingDoes(){var schedule=schedule(false);task("inside",start(yesterday()).plusHours(1),8);String run=run(schedule,yesterday(),key());service.pump();jdbc.update("UPDATE workflow_instance SET result_json=JSON_PRETTY(result_json) WHERE kind='DIGEST_RUN' AND workflow_id=?",run);assertThat(service.download(run,"md").bytes()).isNotEmpty();jdbc.update("UPDATE workflow_instance SET result_json=JSON_SET(result_json,'$.reportDate','1999-01-01') WHERE kind='DIGEST_RUN' AND workflow_id=?",run);assertThatThrownBy(()->service.download(run,"md")).isInstanceOf(BusinessException.class).hasMessageContaining("摘要");}
    @Test void idempotentCreationAndManualSubmissionDoNotDuplicateSchedulesOrRuns(){String request=key();var command=new QualityDigestService.Save("质量日报","0 0 8 * * *",false,0,request);var first=service.save(null,command);assertThat(id(service.save(null,command))).isEqualTo(id(first));String key=key();assertThat(run(first,yesterday(),key)).isEqualTo(run(first,yesterday(),key));assertThat(service.runs(id(first))).hasSize(1);assertThatThrownBy(()->service.save(id(first),new QualityDigestService.Save("修改","0 0 9 * * *",false,0,key()))).isInstanceOf(BusinessException.class);}
    @Test void otherSupervisorsCannotReadPrivateSchedulesAndRevokedOwnerCannotDownload(){var schedule=schedule(false);String run=run(schedule,yesterday(),key());service.pump();directory.account.set(new Identity(4,"boss2",true));assertThat(service.schedules()).isEmpty();assertThatThrownBy(()->service.runs(id(schedule))).isInstanceOf(BusinessException.class);assertThatThrownBy(()->service.download(run,"md")).isInstanceOf(BusinessException.class);directory.account.set(new Identity(3,"boss",true));directory.roles.put(3L,false);assertThatThrownBy(()->service.download(run,"md")).isInstanceOf(BusinessException.class);}
    @Test void authorityRevokedBeforeFinalCommitStopsSnapshotDelivery(){var schedule=schedule(false);String run=run(schedule,yesterday(),key());var calls=new AtomicInteger();directory.onCurrent=()->{if(calls.incrementAndGet()==2)directory.roles.put(3L,false);};service.pump();assertThat(jdbc.queryForObject("SELECT status FROM workflow_instance WHERE kind='DIGEST_RUN' AND workflow_id=?",String.class,run)).isEqualTo("BLOCKED");assertThat(jdbc.queryForObject("SELECT result_json FROM workflow_instance WHERE kind='DIGEST_RUN' AND workflow_id=?",String.class,run)).isNull();}
    @Test void twoSchedulersClaimOneDueSlotAndDoNotBackfillAnOutage()throws Exception{var schedule=schedule(true);jdbc.update("UPDATE scheduled_plan SET next_fire_at=? WHERE kind='DIGEST_SCHEDULE' AND plan_id=?",LocalDateTime.now(ZoneOffset.UTC).minusDays(2),id(schedule));var pool=Executors.newFixedThreadPool(2);try{var a=pool.submit(service::pump);var b=pool.submit(service::pump);a.get(8,TimeUnit.SECONDS);b.get(8,TimeUnit.SECONDS);assertThat(service.runs(id(schedule))).hasSize(1);assertThat(jdbc.queryForObject("SELECT next_fire_at FROM scheduled_plan WHERE kind='DIGEST_SCHEDULE' AND plan_id=?",LocalDateTime.class,id(schedule))).isAfter(LocalDateTime.now(ZoneOffset.UTC));}finally{pool.shutdownNow();}}
    @Test void expiredReadOnlyJobLeaseCanBeReclaimedAndStaleTokenCannotOverwriteResult(){var schedule=schedule(false);String run=run(schedule,yesterday(),key());jdbc.update("UPDATE workflow_instance SET status='RUNNING',fence=1,claim_token='old-worker',lease_expires_at=? WHERE kind='DIGEST_RUN' AND workflow_id=?",LocalDateTime.now(ZoneOffset.UTC).minusMinutes(1),run);service.pump();assertThat(jdbc.queryForObject("SELECT status FROM workflow_instance WHERE kind='DIGEST_RUN' AND workflow_id=?",String.class,run)).isEqualTo("COMPLETED");assertThat(jdbc.queryForObject("SELECT fence FROM workflow_instance WHERE kind='DIGEST_RUN' AND workflow_id=?",Long.class,run)).isEqualTo(2L);int changed=jdbc.update("UPDATE workflow_instance SET error_code='stale' WHERE kind='DIGEST_RUN' AND workflow_id=? AND status='RUNNING' AND claim_token='old-worker'",run);assertThat(changed).isZero();assertThat(service.download(run,"pdf").bytes()).startsWith(new byte[]{'%','P','D','F'});}
    @Test void cronAndFutureDatesAreRejectedAndDisabledPlansStillFinishAlreadyQueuedRuns(){assertThatThrownBy(()->service.save(null,new QualityDigestService.Save("过频计划","* * * * * *",true,0,key()))).isInstanceOf(BusinessException.class);var schedule=schedule(false);assertThatThrownBy(()->run(schedule,LocalDate.now(beijing).plusDays(1),key())).isInstanceOf(BusinessException.class);String run=run(schedule,yesterday(),key());service.pump();assertThat(jdbc.queryForObject("SELECT status FROM workflow_instance WHERE kind='DIGEST_RUN' AND workflow_id=?",String.class,run)).isEqualTo("COMPLETED");assertThat(jdbc.queryForObject("SELECT enabled FROM scheduled_plan WHERE kind='DIGEST_SCHEDULE' AND plan_id=?",Boolean.class,id(schedule))).isFalse();}
    @Test void dailyQuotaDisablesAutomaticPlanWithoutGrowingTheQueue(){
        var schedule=schedule(true);for(int i=0;i<500;i++)run(schedule,yesterday(),key());
        jdbc.update("UPDATE scheduled_plan SET next_fire_at=? WHERE kind='DIGEST_SCHEDULE' AND plan_id=?",LocalDateTime.now(ZoneOffset.UTC).minusMinutes(1),id(schedule));
        service.pump();
        assertThat(jdbc.queryForObject("SELECT enabled FROM scheduled_plan WHERE kind='DIGEST_SCHEDULE' AND plan_id=?",Boolean.class,id(schedule))).isFalse();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='DIGEST_RUN'",Long.class)).isEqualTo(500);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='DIGEST' AND action='RUN_QUOTA_BLOCKED'",Long.class)).isEqualTo(1);
    }
    @Test void identicalManualRequestIdsAreScopedToEachSchedule(){
        var one=schedule(false);var two=schedule(false);String request=key();
        assertThat(run(one,yesterday(),request)).isNotEqualTo(run(two,yesterday(),request));
        assertThat(service.runs(id(one))).hasSize(1);assertThat(service.runs(id(two))).hasSize(1);
    }
    @Test void httpPlanGenerationAndDocumentExportUseRealSnapshotAndRequiredMarker()throws Exception{
        var http=org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(new com.ruanzhu.doorhandle.module.detection.controller.QualityDigestController(service)).setControllerAdvice(new com.ruanzhu.doorhandle.common.GlobalExceptionHandler()).build();
        var json=context.getBean(ObjectMapper.class);String body=json.writeValueAsString(new QualityDigestService.Save("HTTP日报","0 0 8 * * *",false,0,key()));
        http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post("/api/quality/digests").contentType("application/json").content(body)).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.code").value(400));assertThat(service.schedules()).isEmpty();
        var created=http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post("/api/quality/digests").header("X-Digest-Action","update").contentType("application/json").content(body)).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.code").value(200)).andReturn();
        String id=json.readTree(created.getResponse().getContentAsByteArray()).at("/data/schedule_id").asText();
        String generate="{\"reportDate\":\""+yesterday()+"\",\"expectedVersion\":1,\"requestId\":\"http-digest-run\"}";
        http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post("/api/quality/digests/"+id+"/runs").header("X-Digest-Action","update").contentType("application/json").content(generate)).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.code").value(200));
        service.pump();String run=service.runs(id).get(0).get("run_id").toString();
        var file=http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post("/api/quality/digests/runs/"+run+"/export").param("format","pdf").header("X-Digest-Action","update")).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isOk()).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.content().contentType("application/pdf")).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.header().string("Cache-Control","no-store")).andReturn().getResponse().getContentAsByteArray();
        assertThat(file).startsWith(new byte[]{'%','P','D','F'});
    }
    static class Directory implements BusinessUserDirectory{final Map<Long,Boolean> roles=new ConcurrentHashMap<>(Map.of(3L,true,4L,true));final ThreadLocal<Identity> account=ThreadLocal.withInitial(()->new Identity(3,"boss",true));volatile Runnable onCurrent;public Identity authenticated(){return account.get();}public Identity current(long id,String name){if(onCurrent!=null)onCurrent.run();return new Identity(id,name,roles.getOrDefault(id,false));}public Identity lockCurrent(long id,String name){return current(id,name);}}
    @Configuration static class Config{
        @Bean DataSource source()throws Exception{return com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql.open(System.getProperty("doorhandle.digest.mysql.config"),"doorhandle_detection_verify_");}@Bean JdbcTemplate jdbc(DataSource source){return new JdbcTemplate(source);}@Bean DataSourceTransactionManager transactions(DataSource source){return new DataSourceTransactionManager(source);}@Bean Directory users(){return new Directory();}@Bean ObjectMapper json(){return new ObjectMapper().findAndRegisterModules();}
    }
}
