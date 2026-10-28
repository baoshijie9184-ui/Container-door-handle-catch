package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.detection.dto.report.QualityReportDtos.*;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.repository.QualityReportRepository;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.*;
import org.springframework.context.annotation.*;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.jdbc.core.*;
import org.springframework.jdbc.datasource.*;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import javax.sql.DataSource;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** 真实生产 Service、事务、报告表和约束，任务 Mapper 为隔离 SQL fixture。 */
class QualityReportServiceTest {
    static final Identity alice=new Identity(1,"alice",false),other=new Identity(2,"other",false),boss=new Identity(3,"boss",true),boss2=new Identity(4,"boss2",true);
    AnnotationConfigApplicationContext context;JdbcTemplate jdbc;QualityReportService service;Map<Long,Boolean> roles;
    @BeforeEach void setup() throws Exception {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(),""),DetectionTask.class);
        context=new AnnotationConfigApplicationContext(Config.class);jdbc=context.getBean(JdbcTemplate.class);service=context.getBean(QualityReportService.class);roles=context.getBean(RoleStore.class).roles;
        String sql=Files.readString(Path.of("../sql/mysql/migration-V21-quality-report-approval.sql"),StandardCharsets.UTF_8)
                .replaceAll("(?m)\\) ENGINE=InnoDB[^;]*;", ");");
        try(var connection=context.getBean(DataSource.class).getConnection()){ScriptUtils.executeSqlScript(connection,new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)));}
        String origin=Files.readString(Path.of("../sql/mysql/migration-V22-agent-report-origin.sql"),StandardCharsets.UTF_8).replaceAll("(?m)\\) ENGINE=InnoDB[^;]*;", ");");
        try(var connection=context.getBean(DataSource.class).getConnection()){ScriptUtils.executeSqlScript(connection,new ByteArrayResource(origin.getBytes(StandardCharsets.UTF_8)));}
        String delivery=Files.readString(Path.of("../sql/mysql/migration-V30-report-event-delivery.sql"),StandardCharsets.UTF_8).replaceAll("(?m)\\) ENGINE=InnoDB[^;]*;", ");");
        try(var connection=context.getBean(DataSource.class).getConnection()){ScriptUtils.executeSqlScript(connection,new ByteArrayResource(delivery.getBytes(StandardCharsets.UTF_8)));}
        jdbc.execute("CREATE TABLE detection_task(task_id VARCHAR(128) PRIMARY KEY,created_by VARCHAR(50),assignee VARCHAR(50),status VARCHAR(20),flow_status VARCHAR(30),total_images INT,processed_images INT,successful_images INT,failed_images INT,defect_count INT,review_status VARCHAR(20),review_conclusion VARCHAR(30),recheck_required BOOLEAN,source_oss_prefix VARCHAR(200))");
        jdbc.update("INSERT INTO detection_task VALUES('task-1','alice','alice','COMPLETED','REVIEWED',12,12,12,0,2,'REVIEWED','DEFECT',false,'private-oss-key')");
        jdbc.update("INSERT INTO detection_task VALUES('task-2','other','other','COMPLETED','REVIEWED',12,12,12,0,0,'REVIEWED','PASS',false,'other-secret')");
    }
    @AfterEach void close(){context.close();}
    String key(){return UUID.randomUUID().toString();}
    View create(){return service.create(alice,new Create("task-1","检测报告","人工说明 <script>alert(1)</script>",key()));}
    View submitted(){var draft=create();return service.submit(alice,draft.reportId(),new Command(draft.version(),key()));}
    Decision approvedRequest(View row,Identity actor){var preview=service.preview(actor,row.reportId(),new DecisionPreview(row.version(),"APPROVE","已核对检测依据"));return new Decision(row.version(),preview.decision(),preview.reason(),preview.confirmationToken(),key());}
    long count(String table){return jdbc.queryForObject("SELECT COUNT(*) FROM "+table,Long.class);}
    @Test void deliveryReadAndRetryPreserveScopeConfirmationAndIdempotentAudit(){
        var row=submitted();var event=service.events(alice,row.reportId()).get(0);
        assertThat(event.deliveryStatus()).isEqualTo("PENDING");assertThatThrownBy(()->service.events(other,row.reportId())).isInstanceOf(BusinessException.class);
        jdbc.update("UPDATE detection_report_outbox SET delivery_status='RETRY',attempts=2 WHERE event_id=?",event.eventId());
        var request=new RetryEvent(2,true,key());
        assertThatThrownBy(()->service.retryEvent(alice,row.reportId(),event.eventId(),request)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->service.retryEvent(boss,row.reportId(),event.eventId(),new RetryEvent(2,false,key()))).isInstanceOf(BusinessException.class);
        assertThatThrownBy(()->service.retryEvent(boss,row.reportId(),event.eventId(),new RetryEvent(1,true,key()))).isInstanceOf(BusinessException.class);
        assertThat(service.retryEvent(boss,row.reportId(),event.eventId(),request)).singleElement().satisfies(item->assertThat(item.deliveryStatus()).isEqualTo("RETRY"));
        assertThat(service.retryEvent(boss,row.reportId(),event.eventId(),request)).hasSize(1);
        assertThat(service.audit(boss,row.reportId())).filteredOn(a->a.action().equals("EVENT_RETRY")).hasSize(1);
        jdbc.update("UPDATE detection_report_outbox SET delivery_status='DELIVERED' WHERE event_id=?",event.eventId());
        assertThatThrownBy(()->service.retryEvent(boss,row.reportId(),event.eventId(),new RetryEvent(2,true,key()))).isInstanceOf(BusinessException.class);
        assertThat(service.get(alice,row.reportId()).version()).isEqualTo(row.version());
    }
    @Test void retryAuditFailureRollsBackQueueChangeAndCommand(){
        var row=submitted();var event=service.events(alice,row.reportId()).get(0);jdbc.update("UPDATE detection_report_outbox SET delivery_status='FAILED',attempts=1 WHERE event_id=?",event.eventId());
        jdbc.execute("ALTER TABLE detection_report_audit ADD CONSTRAINT fail_retry CHECK(action<>'EVENT_RETRY')");long before=count("detection_report_command");
        assertThatThrownBy(()->service.retryEvent(boss,row.reportId(),event.eventId(),new RetryEvent(1,true,key()))).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(service.events(alice,row.reportId()).get(0).deliveryStatus()).isEqualTo("FAILED");assertThat(count("detection_report_command")).isEqualTo(before);
    }
    @Test void normalApprovalFreezesSourceAndExportsWithAuditWithoutTaskWrite(){
        var row=submitted();var request=approvedRequest(row,boss);var approved=service.decide(boss,row.reportId(),request);
        assertThat(approved.status()).isEqualTo("APPROVED");assertThat(approved.version()).isEqualTo(3);
        assertThat(service.export(alice,row.reportId())).contains("已审批检测报告","boss","&lt;script&gt;").doesNotContain("private-oss-key","<script>");
        assertThat(service.audit(alice,row.reportId())).extracting(Audit::action).containsExactly("EXPORT","APPROVE","SUBMIT","CREATE");
        assertThat(count("detection_report_outbox")).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT flow_status FROM detection_task WHERE task_id='task-1'",String.class)).isEqualTo("REVIEWED");
    }
    @Test void approvedReportsProduceReadableWordPdfAndExcelWithFrozenIdentity()throws Exception{
        var row=submitted();var approved=service.decide(boss,row.reportId(),approvedRequest(row,boss));
        var output=Path.of("../work/feature-tests-20261027/report-artifacts");Files.createDirectories(output);
        for(String format:List.of("docx","pdf","xlsx")){
            var file=service.exportDocument(alice,row.reportId(),format);Files.write(output.resolve("approved-report."+format),file.bytes());
            String text;
            if(format.equals("docx")){try(var document=new org.apache.poi.xwpf.usermodel.XWPFDocument(new java.io.ByteArrayInputStream(file.bytes()))){text=document.getParagraphs().stream().map(org.apache.poi.xwpf.usermodel.XWPFParagraph::getText).collect(java.util.stream.Collectors.joining("\n"));}}
            else if(format.equals("xlsx")){try(var workbook=new org.apache.poi.xssf.usermodel.XSSFWorkbook(new java.io.ByteArrayInputStream(file.bytes()))){var content=new StringBuilder();for(var item:workbook.getSheetAt(0))for(var cell:item)content.append(cell.getStringCellValue()).append('\n');text=content.toString();}}
            else try(var document=org.apache.pdfbox.Loader.loadPDF(file.bytes())){text=new org.apache.pdfbox.text.PDFTextStripper().getText(document);javax.imageio.ImageIO.write(new org.apache.pdfbox.rendering.PDFRenderer(document).renderImageWithDPI(0,110),"png",output.resolve("approved-report-page1.png").toFile());}
            assertThat(text).contains("已审批检测报告","boss","task-1");
            // PDF may wrap a long fingerprint; extracted line breaks do not change its identity.
            assertThat(text.replaceAll("\\s+", "")).contains(approved.snapshotSha256());
        }
        assertThat(service.audit(alice,row.reportId())).filteredOn(a->a.action().equals("EXPORT")).hasSize(3);
        assertThat(service.get(alice,row.reportId()).snapshotSha256()).isEqualTo(approved.snapshotSha256());
    }
    @Test void officeExportsCannotBypassDraftPrivacyOrFrozenHash(){var draft=create();for(String format:List.of("docx","pdf","xlsx"))assertThatThrownBy(()->service.exportDocument(alice,draft.reportId(),format)).isInstanceOf(BusinessException.class);var row=submitted();service.decide(boss,row.reportId(),approvedRequest(row,boss));assertThatThrownBy(()->service.exportDocument(other,row.reportId(),"pdf")).isInstanceOf(BusinessException.class);jdbc.update("UPDATE detection_quality_report SET snapshot_sha256=? WHERE report_id=?","0".repeat(64),row.reportId());assertThatThrownBy(()->service.exportDocument(alice,row.reportId(),"xlsx")).isInstanceOf(BusinessException.class);assertThat(service.audit(alice,row.reportId())).filteredOn(a->a.action().equals("EXPORT")).isEmpty();}
    @Test void crossEmployeeAndOtherSupervisorCannotReadPrivateDraft(){
        var row=create();assertThatThrownBy(()->service.get(other,row.reportId())).isInstanceOf(BusinessException.class);
        assertThatThrownBy(()->service.get(boss,row.reportId())).isInstanceOf(BusinessException.class);
        assertThat(service.list(other,1,20,null,null).get("total")).isEqualTo(0L);
        assertThat(service.list(boss,1,20,"DRAFT",null).get("total")).isEqualTo(0L);
        assertThatThrownBy(()->service.create(alice,new Create("task-2","越权","意见",key()))).isInstanceOf(BusinessException.class);
    }
    @Test void repeatedCreateSubmitAndDecisionHaveNoRepeatedSideEffects(){
        var request=new Create("task-1","标题","意见",key());var draft=service.create(alice,request);
        assertThat(service.create(alice,request)).isEqualTo(draft);
        var submit=new Command(draft.version(),key());var row=service.submit(alice,draft.reportId(),submit);
        assertThat(service.submit(alice,draft.reportId(),submit)).isEqualTo(row);
        var decide=approvedRequest(row,boss);var result=service.decide(boss,row.reportId(),decide);
        assertThat(service.decide(boss,row.reportId(),decide)).isEqualTo(result);
        assertThat(count("detection_quality_report")).isEqualTo(1);assertThat(count("detection_report_audit")).isEqualTo(3);assertThat(count("detection_report_outbox")).isEqualTo(2);
        assertThatThrownBy(()->service.create(alice,new Create("task-1","不同标题","意见",request.requestId()))).hasMessageContaining("不同参数");
    }
    @Test void frozenReportCannotBeEditedAndOnlyOwnerMaySubmitOrWithdraw(){
        var row=submitted();assertThatThrownBy(()->service.edit(alice,row.reportId(),new Edit(row.version(),"标题","更改",key()))).hasMessageContaining("状态");
        assertThatThrownBy(()->service.withdraw(boss,row.reportId(),new Command(row.version(),key()))).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->service.edit(boss,row.reportId(),new Edit(row.version(),"标题","更改",key()))).isInstanceOf(SecurityException.class);
    }
    @Test void employeesCannotApproveAndSupervisorCannotApproveOwnSubmission(){
        var row=submitted();assertThatThrownBy(()->service.preview(alice,row.reportId(),new DecisionPreview(row.version(),"APPROVE","意见"))).isInstanceOf(SecurityException.class);
        var draft=service.create(boss,new Create("task-1","主管草稿","意见",key()));var own=service.submit(boss,draft.reportId(),new Command(draft.version(),key()));
        assertThatThrownBy(()->service.preview(boss,own.reportId(),new DecisionPreview(own.version(),"APPROVE","意见"))).hasMessageContaining("独立");
        assertThat(service.decide(boss2,own.reportId(),approvedRequest(own,boss2)).status()).isEqualTo("APPROVED");
    }
    @Test void rejectionAndRevisionKeepOriginalSnapshotAndHistory(){
        var row=submitted();var preview=service.preview(boss,row.reportId(),new DecisionPreview(row.version(),"REJECT","补充说明"));
        var rejected=service.decide(boss,row.reportId(),new Decision(row.version(),"REJECT","补充说明",preview.confirmationToken(),key()));
        var draft=service.revise(alice,row.reportId(),new Command(rejected.version(),key()));
        assertThat(draft.status()).isEqualTo("DRAFT");assertThat(draft.previousReportId()).isEqualTo(row.reportId());
        var edited=service.edit(alice,draft.reportId(),new Edit(draft.version(),"修订","新说明",key()));assertThat(edited.narrative()).isEqualTo("新说明");
        assertThat(service.get(alice,row.reportId()).narrative()).isEqualTo(row.narrative());
        assertThatThrownBy(()->service.export(alice,row.reportId())).hasMessageContaining("状态");
    }
    @Test void withdrawnReportCanBeRevisedButNotApproved(){
        var row=submitted();var withdrawn=service.withdraw(alice,row.reportId(),new Command(row.version(),key()));
        assertThat(withdrawn.status()).isEqualTo("WITHDRAWN");
        assertThatThrownBy(()->service.preview(boss,row.reportId(),new DecisionPreview(withdrawn.version(),"APPROVE","意见"))).hasMessageContaining("状态");
        assertThat(service.revise(alice,row.reportId(),new Command(withdrawn.version(),key())).previousReportId()).isEqualTo(row.reportId());
    }
    @Test void sourceChangesRequireRefreshBeforeSubmissionAndInvalidateApprovalPreview(){
        var row=create();jdbc.update("UPDATE detection_task SET defect_count=4 WHERE task_id='task-1'");
        assertThatThrownBy(()->service.submit(alice,row.reportId(),new Command(row.version(),key()))).hasMessageContaining("依据已变化");
        var refreshed=service.edit(alice,row.reportId(),new Edit(row.version(),row.title(),row.narrative(),key()));
        var pending=service.submit(alice,row.reportId(),new Command(refreshed.version(),key()));var request=approvedRequest(pending,boss);
        jdbc.update("UPDATE detection_task SET defect_count=7 WHERE task_id='task-1'");
        assertThatThrownBy(()->service.decide(boss,row.reportId(),request)).hasMessageContaining("依据已变化");
        assertThat(service.get(alice,row.reportId()).status()).isEqualTo("SUBMITTED");
    }
    @Test void incompleteOrUnreviewedTasksCannotPassApprovalGate(){
        var row=submitted();jdbc.update("UPDATE detection_task SET review_status='PENDING' WHERE task_id='task-1'");
        var withdrawn=service.withdraw(alice,row.reportId(),new Command(row.version(),key()));var draft=service.revise(alice,row.reportId(),new Command(withdrawn.version(),key()));
        var pending=service.submit(alice,draft.reportId(),new Command(draft.version(),key()));
        assertThatThrownBy(()->service.preview(boss,pending.reportId(),new DecisionPreview(pending.version(),"APPROVE","意见"))).hasMessageContaining("复核");
        assertThat(service.preview(boss,pending.reportId(),new DecisionPreview(pending.version(),"REJECT","请先复核")).decision()).isEqualTo("REJECT");
    }
    @Test void tokenIsBoundToActorDecisionReasonVersionAndExpiry(){
        var row=submitted();var request=approvedRequest(row,boss);
        assertThatThrownBy(()->service.decide(boss2,row.reportId(),request)).hasMessageContaining("不一致");
        assertThatThrownBy(()->service.decide(boss,row.reportId(),new Decision(row.version(),"REJECT",request.reason(),request.confirmationToken(),key()))).hasMessageContaining("不一致");
        assertThatThrownBy(()->service.decide(boss,row.reportId(),new Decision(row.version(),"APPROVE","改动意见",request.confirmationToken(),key()))).hasMessageContaining("不一致");
        jdbc.update("UPDATE detection_report_confirmation SET expires_at=DATEADD('MINUTE',-1,CURRENT_TIMESTAMP)");
        assertThatThrownBy(()->service.decide(boss,row.reportId(),request)).hasMessageContaining("过期");
    }
    @Test void twoSupervisorsCompetingForSameReportOnlyCommitOneDecision() throws Exception {
        var row=submitted();var a=approvedRequest(row,boss);var b=approvedRequest(row,boss2);var workers=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try{
            var left=workers.submit(()->{start.await();try{service.decide(boss,row.reportId(),a);return true;}catch(BusinessException error){return false;}});
            var right=workers.submit(()->{start.await();try{service.decide(boss2,row.reportId(),b);return true;}catch(BusinessException error){return false;}});
            start.countDown();assertThat((left.get(10,TimeUnit.SECONDS)?1:0)+(right.get(10,TimeUnit.SECONDS)?1:0)).isEqualTo(1);
            assertThat(service.audit(alice,row.reportId())).filteredOn(audit->"APPROVE".equals(audit.action())).hasSize(1);
        }finally{workers.shutdownNow();}
    }
    @Test void auditFailureRollsBackDecisionTokenCommandAndOutbox(){
        var row=submitted();var request=approvedRequest(row,boss);
        jdbc.execute("ALTER TABLE detection_report_audit ADD CONSTRAINT fail_audit CHECK(action<>'APPROVE')");
        assertThatThrownBy(()->service.decide(boss,row.reportId(),request)).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(service.get(alice,row.reportId()).status()).isEqualTo("SUBMITTED");
        assertThat(count("detection_report_command")).isEqualTo(2);assertThat(count("detection_report_outbox")).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM detection_report_confirmation WHERE used_at IS NOT NULL",Long.class)).isZero();
    }
    @Test void outboxFailureRollsBackSubmissionAndAudit(){
        var row=create();jdbc.execute("ALTER TABLE detection_report_outbox ADD CONSTRAINT fail_event CHECK(event_type<>'detection.report.submitted.v1')");
        assertThatThrownBy(()->service.submit(alice,row.reportId(),new Command(row.version(),key()))).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(service.get(alice,row.reportId()).status()).isEqualTo("DRAFT");assertThat(count("detection_report_audit")).isEqualTo(1);
    }
    @Test void revokedRoleAndTaskReassignmentApplyToExistingSessionsAndRecordedRequests(){
        var row=submitted();var request=approvedRequest(row,boss);roles.put(3L,false);
        assertThatThrownBy(()->service.decide(boss,row.reportId(),request)).isInstanceOf(SecurityException.class);
        jdbc.update("UPDATE detection_task SET created_by='other',assignee='other' WHERE task_id='task-1'");
        assertThatThrownBy(()->service.get(alice,row.reportId())).isInstanceOf(BusinessException.class);
        assertThat(service.list(alice,1,20,null,null).get("total")).isEqualTo(0L);
    }
    @Test void storedHashesAreCanonicalAcrossNewServiceInstancesAndSnapshotsStayHistorical(){
        var row=submitted();var request=approvedRequest(row,boss);
        var newService=new QualityReportService(context.getBean(QualityReportRepository.class),context.getBean(DetectionTaskMapper.class),context.getBean(BusinessUserDirectory.class),new DetectionTaskAccessPolicy(),new ObjectMapper().findAndRegisterModules());
        assertThat(newService.get(alice,row.reportId()).snapshotSha256()).isEqualTo(row.snapshotSha256());
        service.decide(boss,row.reportId(),request);jdbc.update("UPDATE detection_task SET defect_count=99 WHERE task_id='task-1'");
        assertThat(service.get(alice,row.reportId()).source().get("defectCount")).isEqualTo(2);
        assertThat(service.export(alice,row.reportId())).contains("缺陷数量：2");
    }
    @Test void changedFrozenContentFailsIntegrityCheck(){
        var row=submitted();jdbc.update("UPDATE detection_quality_report SET narrative='篡改' WHERE report_id=?",row.reportId());
        assertThatThrownBy(()->service.preview(boss,row.reportId(),new DecisionPreview(row.version(),"REJECT","意见"))).hasMessageContaining("快照校验");
    }
    @Test void agentDraftFacadeStoresOriginAndReplaysWithoutCreatingAnotherDraft(){
        var api=context.getBean(com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.class);
        var actor=new com.ruanzhu.doorhandle.contracts.agent.AgentActor(1,"alice",com.ruanzhu.doorhandle.contracts.agent.AgentActor.Role.INSPECTOR);
        var origin=new com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.Origin(key(),"run-1","call-1","create_report_draft");
        var draft=new com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.Draft("task-1","草稿","意见");
        var saved=api.createDraft(actor,draft,origin);var repeat=api.createDraft(actor,draft,new com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.Origin(origin.requestId(),"run-1","call-2","create_report_draft"));
        assertThat(repeat).isEqualTo(saved);assertThat(saved.report().status()).isEqualTo("DRAFT");
        assertThat(count("detection_report_agent_origin")).isEqualTo(1);assertThat(count("detection_quality_report")).isEqualTo(1);
        assertThat(service.audit(alice,saved.report().reportId()).get(0).runId()).isEqualTo("run-1");
        assertThat(service.audit(alice,saved.report().reportId()).get(0).callId()).isEqualTo("call-1");
        var edit=api.editDraft(actor,new com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.Edit(saved.report().reportId(),1,"新标题","新意见"),
                new com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.Origin(key(),"run-1","call-3","edit_report_draft"));
        assertThat(edit.report().version()).isEqualTo(2);assertThat(count("detection_report_agent_origin")).isEqualTo(2);
    }
    @Test void agentOriginFailureRollsBackDraftBusinessAuditAndCommand(){
        var api=context.getBean(com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.class);
        jdbc.execute("ALTER TABLE detection_report_agent_origin ADD CONSTRAINT fail_origin CHECK(tool_name<>'create_report_draft')");
        var actor=new com.ruanzhu.doorhandle.contracts.agent.AgentActor(1,"alice",com.ruanzhu.doorhandle.contracts.agent.AgentActor.Role.INSPECTOR);
        assertThatThrownBy(()->api.createDraft(actor,new com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.Draft("task-1","草稿","意见"),
                new com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.Origin(key(),"run-1","call-1","create_report_draft"))).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(count("detection_quality_report")).isZero();assertThat(count("detection_report_audit")).isZero();assertThat(count("detection_report_command")).isZero();
    }
    @Test void agentListIsSummaryOnlyAndSubmittedReportCannotBeEditedThroughFacade(){
        var row=submitted();var api=context.getBean(com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.class);
        var actor=new com.ruanzhu.doorhandle.contracts.agent.AgentActor(1,"alice",com.ruanzhu.doorhandle.contracts.agent.AgentActor.Role.INSPECTOR);
        assertThat(api.list(actor,1,20,"SUBMITTED",null).records()).hasSize(1);
        assertThatThrownBy(()->api.editDraft(actor,new com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.Edit(row.reportId(),row.version(),"改动","改动"),
                new com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi.Origin(key(),"run-1","call-1","edit_report_draft"))).hasMessageContaining("状态");
    }
    static class RoleStore {final Map<Long,Boolean> roles=new ConcurrentHashMap<>(Map.of(1L,false,2L,false,3L,true,4L,true));}
    @Configuration @EnableTransactionManagement static class Config {
        @Bean ReportDocumentRenderer documentRenderer(){return new ReportDocumentRenderer();}
        @Bean DataSource source(){return new DriverManagerDataSource("jdbc:h2:mem:report"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");}
        @Bean JdbcTemplate jdbc(DataSource ds){return new JdbcTemplate(ds);}
        @Bean DataSourceTransactionManager transactions(DataSource ds){return new DataSourceTransactionManager(ds);}
        @Bean QualityReportRepository repository(JdbcTemplate jdbc){return new QualityReportRepository(jdbc);}
        @Bean RoleStore roles(){return new RoleStore();}
        @Bean BusinessUserDirectory users(RoleStore store){return (id,name)->new Identity(id,name,store.roles.get(id));}
        @Bean DetectionTaskMapper tasks(JdbcTemplate jdbc){
            var mapper=mock(DetectionTaskMapper.class);
            when(mapper.selectOne(any())).thenAnswer(call->{var query=(LambdaQueryWrapper<DetectionTask>)call.getArgument(0);String segment=query.getSqlSegment();String id=(String)query.getParamNameValuePairs().values().iterator().next();
                var rows=jdbc.query("SELECT * FROM detection_task WHERE task_id=?"+(segment.contains("FOR UPDATE")?" FOR UPDATE":""),BeanPropertyRowMapper.newInstance(DetectionTask.class),id);return rows.isEmpty()?null:rows.get(0);});
            return mapper;
        }
        @Bean QualityReportService service(QualityReportRepository repository,DetectionTaskMapper tasks,BusinessUserDirectory users){return new QualityReportService(repository,tasks,users,new DetectionTaskAccessPolicy(),new ObjectMapper().findAndRegisterModules());}
        @Bean com.ruanzhu.doorhandle.contracts.agent.QualityReportAgentApi reportApi(QualityReportService service,JdbcTemplate jdbc){return new com.ruanzhu.doorhandle.module.detection.api.QualityReportAgentApiImpl(service,jdbc);}
    }
}
