package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.*;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.*;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskProgressResponse;
import com.ruanzhu.doorhandle.module.detection.dto.report.QualityReportDtos.*;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.repository.QualityReportRepository;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.support.ReportMySqlFixture;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.module.system.service.*;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.*;
import org.springframework.core.env.MapPropertySource;
import org.springframework.jdbc.core.*;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.mock.web.*;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.web.context.request.*;
import javax.sql.DataSource;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/** Actual task participant, claim identity and report services on admitted ECS MySQL only. */
@EnabledIfSystemProperty(named="doorhandle.report.mysql.config",matches=".+")
class DetectionCollaborationMySqlTest {
    static final AtomicBoolean rejectAudit=new AtomicBoolean();
    static final BusinessUserDirectory.Identity alice=new BusinessUserDirectory.Identity(1,"alice",false),boss=new BusinessUserDirectory.Identity(3,"boss",true);
    AnnotationConfigApplicationContext context;JdbcTemplate jdbc;DetectionTaskClaimService claims;QualityReportService reports;
    @Configuration @EnableAspectJAutoProxy(proxyTargetClass=true) @EnableTransactionManagement
    static class Config {
        @Bean(destroyMethod="close") ReportMySqlFixture fixture(){return new ReportMySqlFixture();}
        @Bean DataSource data(ReportMySqlFixture fixture){return fixture.source();}
        @Bean JdbcTemplate jdbc(DataSource data){return new JdbcTemplate(data);}
        @Bean PlatformTransactionManager transactions(DataSource data){return new DataSourceTransactionManager(data);}
        @Bean ObjectMapper json(){return new ObjectMapper().findAndRegisterModules();}
        @Bean BusinessUserDirectory users(JdbcTemplate jdbc){return new BusinessUserDirectory(){
            public Identity current(long id,String username){var rows=jdbc.queryForList("SELECT username,role,enabled FROM users WHERE id=?",id);if(rows.size()!=1)throw new SecurityException("account missing or ineligible");var row=rows.get(0);Object enabled=row.get("enabled");if(!username.equals(row.get("username"))||!(Boolean.TRUE.equals(enabled)||enabled instanceof Number number&&number.intValue()==1)||!Set.of("INSPECTOR","SUPERVISOR").contains(row.get("role")))throw new SecurityException("account missing or ineligible");return new Identity(id,username,"SUPERVISOR".equals(row.get("role")));}
            public Identity lockCurrent(long id,String username){jdbc.queryForList("SELECT id FROM users WHERE id=? FOR UPDATE",id);return current(id,username);}
            public Identity authenticated(){var principal=(BusinessPrincipal)SecurityContextHolder.getContext().getAuthentication().getPrincipal();return current(principal.userId(),principal.username());}
        };}
        @Bean OperationsAuditApi audit(JdbcTemplate jdbc,BusinessUserDirectory users){
            var actual=new OperationsAuditService(jdbc,users);
            return new OperationsAuditApi(){public void append(Event event){actual.append(event);}public void appendChange(ChangeEvent event){if(rejectAudit.get())throw new IllegalStateException("audit unavailable");actual.appendChange(event);}};
        }
        @Bean BusinessMutationAudit aspect(OperationsAuditApi audit,BusinessUserDirectory users,PlatformTransactionManager manager){return new BusinessMutationAudit(audit,users,manager);}
        @Bean DetectionTaskMapper tasks(JdbcTemplate jdbc){
            var mapper=mock(DetectionTaskMapper.class);
            when(mapper.selectOne(any())).thenAnswer(call->{var query=(com.baomidou.mybatisplus.core.conditions.AbstractWrapper<?,?,?>)call.getArgument(0);query.getSqlSegment();var id=query.getParamNameValuePairs().get("MPGENVAL1");
                var rows=jdbc.query("SELECT * FROM detection_task WHERE task_id=?"+(query.getSqlSegment().contains("FOR UPDATE")?" FOR UPDATE":""),BeanPropertyRowMapper.newInstance(DetectionTask.class),id);return rows.isEmpty()?null:rows.get(0);});
            when(mapper.updateById(any(DetectionTask.class))).thenAnswer(call->{DetectionTask task=call.getArgument(0);return jdbc.update("UPDATE detection_task SET assignee=?,quality_station=?,flow_status=?,assignment_remark=?,assigned_at=?,due_at=?,updated_at=? WHERE task_id=?",task.getAssignee(),task.getQualityStation(),task.getFlowStatus(),task.getAssignmentRemark(),task.getAssignedAt(),task.getDueAt(),task.getUpdatedAt(),task.getTaskId());});
            when(mapper.clearClaimCandidates(anyString())).thenAnswer(call->jdbc.update("UPDATE detection_task SET claim_candidate_ids=NULL WHERE task_id=?",(String)call.getArgument(0)));
            return mapper;
        }
        @Bean DetectionTaskAccessPolicy policy(){
            // The claim's persisted identity writes are enabled independently of a historical identity-mode rollout.
            return new DetectionTaskAccessPolicy(){@Override public void setIdentities(DetectionIdentityService ignored){}};
        }
        @Bean DetectionMutationParticipant participant(JdbcTemplate jdbc,DetectionTaskAccessPolicy policy){return new DetectionMutationParticipant(jdbc,policy);}
        @Bean AgentUserDirectory inspectors(){var directory=mock(AgentUserDirectory.class);when(directory.inspector("alice")).thenReturn(new AgentUserDirectory.Inspector(1,"alice","a".repeat(64)));when(directory.inspector("other")).thenReturn(new AgentUserDirectory.Inspector(2,"other","b".repeat(64)));when(directory.lockInspector(any())).thenAnswer(call->call.getArgument(0));return directory;}
        @Bean BusinessAccountLookupApi accounts(JdbcTemplate jdbc){var lookup=mock(BusinessAccountLookupApi.class);when(lookup.username(anyLong())).thenAnswer(call->{var rows=jdbc.queryForList("SELECT username FROM users WHERE id=?",String.class,(long)call.getArgument(0));return rows.isEmpty()?null:rows.get(0);});return lookup;}
        @Bean DetectionIdentityReviewService identityReview(){return mock(DetectionIdentityReviewService.class);}
        @Bean DetectionIdentityService identity(JdbcTemplate jdbc,BusinessUserDirectory users,OperationsAuditApi audit,ObjectMapper json){return new DetectionIdentityService(jdbc,mock(BusinessAccountLookupApi.class),users,audit,json);}
        @Bean DetectionTaskService views(JdbcTemplate jdbc){var views=mock(DetectionTaskService.class);when(views.getTaskProgress(any())).thenAnswer(call->{var row=jdbc.queryForMap("SELECT task_id,status,version FROM detection_task WHERE task_id=?",(String)call.getArgument(0));return DetectionTaskProgressResponse.builder().taskId((String)row.get("task_id")).status((String)row.get("status")).version(row.get("version").toString()).build();});return views;}
        @Bean DetectionTaskClaimService claims(DetectionTaskMapper tasks,DetectionTaskService views,DetectionTaskAccessPolicy policy,BusinessUserDirectory users,AgentUserDirectory inspectors,JdbcTemplate jdbc,ObjectProvider<DetectionIdentityService> identities){return new DetectionTaskClaimService(tasks,views,policy,users,inspectors,jdbc,identities);}
        @Bean QualityReportRepository reportRepository(JdbcTemplate jdbc){return new QualityReportRepository(jdbc);}
        @Bean ReportDocumentRenderer renderer(){return new ReportDocumentRenderer();}
        @Bean QualityReportService reports(QualityReportRepository repository,DetectionTaskMapper tasks,BusinessUserDirectory users,DetectionTaskAccessPolicy policy,ObjectMapper json){return new QualityReportService(repository,tasks,users,policy,json);}
    }
    @BeforeEach void setup(){
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(),""),DetectionTask.class);
        rejectAudit.set(false);context=new AnnotationConfigApplicationContext();
        context.getEnvironment().getPropertySources().addFirst(new MapPropertySource("collaboration",Map.of(
                "operations.audit.enabled","true","collaboration.mutations.enabled","true","collaboration.change-history.enabled","true",
                "detection.identity.assignment-binding-enabled","true")));
        context.register(Config.class);context.refresh();jdbc=context.getBean(JdbcTemplate.class);claims=context.getBean(DetectionTaskClaimService.class);reports=context.getBean(QualityReportService.class);
        jdbc.update("INSERT INTO users(id,username,password,role) VALUES(1,'alice','fixture','INSPECTOR'),(2,'other','fixture','INSPECTOR'),(3,'boss','fixture','SUPERVISOR')");
        jdbc.update("INSERT INTO detection_task(task_id,created_by,created_user_id,created_identity_name,claim_candidate_ids,status,flow_status,total_images,processed_images,successful_images,failed_images,defect_count,review_status,review_conclusion,recheck_required,source_oss_prefix) VALUES('claim-task','alice',1,'alice','[\"1\"]','COMPLETED','PENDING_REVIEW',12,12,12,0,2,'PENDING','PENDING',false,'private-source')");
        jdbc.update("INSERT INTO detection_task(task_id,created_by,assignee,status,flow_status,total_images,processed_images,successful_images,failed_images,defect_count,review_status,review_conclusion,recheck_required,source_oss_prefix) VALUES('report-task','alice','alice','COMPLETED','REVIEWED',12,12,12,0,2,'REVIEWED','DEFECT',false,'private-source')");
        request(1,"claim-initial");
    }
    @AfterEach void close(){SecurityContextHolder.clearContext();RequestContextHolder.resetRequestAttributes();if(context!=null)context.close();}
    private MockHttpServletResponse request(long id,String key){var principal=new TenantPrincipal(id,id==1?"alice":id==2?"other":"boss","",List.of());SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(principal,null,List.of()));var request=new MockHttpServletRequest();request.addHeader("X-Request-ID",key);var response=new MockHttpServletResponse();RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request,response));return response;}
    private String key(){return UUID.randomUUID().toString();}
    private long count(String kind){return jdbc.queryForObject("SELECT COUNT(*) FROM "+(kind.equals("OPERATIONS")?"audit_event":"workflow_instance")+" WHERE kind=?",Long.class,kind);}
    private JsonNode change(String action,String domain) throws Exception {return context.getBean(ObjectMapper.class).readTree(jdbc.queryForObject("SELECT payload_json FROM audit_event WHERE kind='OPERATIONS' AND action=? AND operation_domain=?",String.class,action,domain));}
    @Test void claimPersistsStableIdentityDiffAndReplaysExactOriginalResponse() throws Exception {
        var firstHeaders=request(1,"claim-once");var first=claims.claim("claim-task",new DetectionTaskClaimService.Claim("0","claim-once"));
        assertThat(first.getVersion()).isEqualTo("1");
        var snapshot=jdbc.queryForMap("SELECT assignee_user_id,assigned_by_user_id,assignment_identity_revision,version FROM detection_task WHERE task_id='claim-task'");
        assertThat(((Number)snapshot.get("assignee_user_id")).longValue()).isEqualTo(1);assertThat(((Number)snapshot.get("assignment_identity_revision")).longValue()).isEqualTo(1);
        var payload=change("claimTask","DETECTION");assertThat(payload.path("beforeVersion").asLong()).isZero();assertThat(payload.path("resourceVersion").asLong()).isEqualTo(1);
        assertThat(payload.path("changes")).anySatisfy(field->{assertThat(field.path("field").asText()).isEqualTo("assignee_user_id");assertThat(field.path("before").isNull()).isTrue();assertThat(field.path("after").asText()).isEqualTo("1");});
        var secondHeaders=request(1,"claim-once");var repeated=claims.claim("claim-task",new DetectionTaskClaimService.Claim("0","claim-once"));
        assertThat(repeated.getVersion()).isEqualTo(first.getVersion());assertThat(repeated.getTaskId()).isEqualTo(first.getTaskId());assertThat(secondHeaders.getHeader("X-Audit-ID")).isEqualTo(firstHeaders.getHeader("X-Audit-ID"));
        assertThat(count("BUSINESS_COMMAND")).isEqualTo(1);assertThat(count("OPERATIONS")).isEqualTo(1);
    }
    @Test void twoDevicesClaimingOneTaskCommitOneIdentityAndOneReceipt() throws Exception {
        var gate=new CyclicBarrier(2);var pool=Executors.newFixedThreadPool(2);
        try {var results=new ArrayList<Future<Boolean>>();for(int number:List.of(1,2)){results.add(pool.submit(()->{String requestId="claim-race-"+number;request(1,requestId);try{gate.await(10,TimeUnit.SECONDS);claims.claim("claim-task",new DetectionTaskClaimService.Claim("0",requestId));return true;}catch(com.ruanzhu.doorhandle.common.BusinessException conflict){assertThat(conflict.getCode()).isEqualTo(409);return false;}finally{SecurityContextHolder.clearContext();RequestContextHolder.resetRequestAttributes();}}));}
            assertThat(List.of(results.get(0).get(20,TimeUnit.SECONDS),results.get(1).get(20,TimeUnit.SECONDS))).containsExactlyInAnyOrder(true,false);
        } finally {pool.shutdownNow();}
        assertThat(count("BUSINESS_COMMAND")).isEqualTo(1);assertThat(count("OPERATIONS")).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT assignment_identity_revision FROM detection_task WHERE task_id='claim-task'",Long.class)).isEqualTo(1);
    }
    @Test void inspectorCannotClaimAResourceOutsideTheirExistingScope(){
        request(2,"forbidden-claim");assertThatThrownBy(()->claims.claim("claim-task",new DetectionTaskClaimService.Claim("0","forbidden-claim"))).isInstanceOf(SecurityException.class);
        assertThat(count("BUSINESS_COMMAND")).isZero();assertThat(count("OPERATIONS")).isZero();assertThat(jdbc.queryForObject("SELECT assignee_user_id FROM detection_task WHERE task_id='claim-task'",Long.class)).isNull();
    }
    @Test void reportEditContainsRealPersistedDiffWithoutNarrativeOrSourceContents() throws Exception {
        var draft=reports.create(alice,new Create("report-task","Old title","private first narrative",key()));
        var request=new Edit(draft.version(),"New title","private replacement narrative",key());var edited=reports.edit(alice,draft.reportId(),request);
        var payload=change("EDIT","QUALITY_REPORT");assertThat(payload.path("beforeVersion").asInt()).isEqualTo(draft.version());assertThat(payload.path("resourceVersion").asInt()).isEqualTo(edited.version());
        assertThat(payload.toString()).doesNotContain("private first narrative","private replacement narrative","private-source");
        assertThat(payload.path("changes")).anySatisfy(field->{assertThat(field.path("field").asText()).isEqualTo("title");assertThat(field.path("before").asText()).isEqualTo("Old title");assertThat(field.path("after").asText()).isEqualTo("New title");});
        assertThat(reports.edit(alice,draft.reportId(),request)).isEqualTo(edited);assertThat(count("OPERATIONS")).isEqualTo(2);
    }
    @Test void reportApprovalAuditFailureRollsBackDecisionConfirmationAndCommand(){
        var draft=reports.create(alice,new Create("report-task","Report","private narrative",key()));var submitted=reports.submit(alice,draft.reportId(),new Command(draft.version(),key()));
        var preview=reports.preview(boss,submitted.reportId(),new DecisionPreview(submitted.version(),"APPROVE","confirmed"));
        var decision=new Decision(submitted.version(),preview.decision(),preview.reason(),preview.confirmationToken(),key());
        long commands=count("REPORT_COMMAND"),events=count("OPERATIONS");rejectAudit.set(true);
        assertThatThrownBy(()->reports.decide(boss,submitted.reportId(),decision)).hasMessage("audit unavailable");
        assertThat(reports.get(alice,submitted.reportId()).status()).isEqualTo("SUBMITTED");assertThat(count("REPORT_COMMAND")).isEqualTo(commands);assertThat(count("OPERATIONS")).isEqualTo(events);
        rejectAudit.set(false);assertThat(reports.decide(boss,submitted.reportId(),decision).status()).isEqualTo("APPROVED");
    }
    private void supervisorOwnedTask(){jdbc.update("UPDATE detection_task SET created_by='boss',created_user_id=3,created_identity_name='boss',claim_candidate_ids=NULL WHERE task_id='claim-task'");}
    private void authorize(String request){request(3,request);claims.authorize("claim-task",new DetectionTaskClaimService.Candidates(List.of("2","1"),"0",request));}
    private List<String> scopedIds(){var scope=context.getBean(DetectionTaskAccessPolicy.class).currentSqlScope("");return new org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate(jdbc).queryForList("SELECT task_id FROM detection_task WHERE "+scope.predicate(),scope.parameters(),String.class);}
    @Test void supervisorExplicitlyAuthorizesBoundedCandidatesWithCasAuditAndOriginalReceipt() throws Exception {
        supervisorOwnedTask();authorize("candidate-grant");
        assertThat(jdbc.queryForObject("SELECT version FROM detection_task WHERE task_id='claim-task'",Long.class)).isEqualTo(1);
        assertThat(com.ruanzhu.doorhandle.module.detection.security.DetectionClaimCandidates.read(jdbc.queryForObject("SELECT claim_candidate_ids FROM detection_task WHERE task_id='claim-task'",String.class))).containsExactly("1","2");
        var payload=change("authorizeClaimCandidates","DETECTION");assertThat(payload.path("changes")).anySatisfy(field->{assertThat(field.path("field").asText()).isEqualTo("claim_candidate_ids");assertThat(field.path("before").isNull()).isTrue();assertThat(field.path("after").asText()).isEqualTo("[\"1\",\"2\"]");});
        var replay=claims.authorize("claim-task",new DetectionTaskClaimService.Candidates(List.of("2","1"),"0","candidate-grant"));assertThat(replay.getVersion()).isEqualTo("1");assertThat(count("OPERATIONS")).isEqualTo(1);assertThat(count("BUSINESS_COMMAND")).isEqualTo(1);
        request(3,"stale-candidate-grant");assertThatThrownBy(()->claims.authorize("claim-task",new DetectionTaskClaimService.Candidates(List.of("1"),"0","stale-candidate-grant"))).isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);
    }
    @Test void twoDifferentExplicitCandidatesRaceOneCommitsAndLoserImmediatelyLosesReadScope() throws Exception {
        supervisorOwnedTask();authorize("race-grant");request(1,"candidate-read-a");assertThat(scopedIds()).contains("claim-task");request(2,"candidate-read-b");assertThat(scopedIds()).contains("claim-task");
        var pool=Executors.newFixedThreadPool(2);var ready=new CountDownLatch(2);var start=new CountDownLatch(1);var winners=new CopyOnWriteArrayList<Long>();
        try{
            var futures=new ArrayList<Future<?>>();for(long id:List.of(1L,2L))futures.add(pool.submit(()->{request(id,"candidate-race-"+id);ready.countDown();try{if(!start.await(10,TimeUnit.SECONDS))throw new AssertionError("race barrier timeout");claims.claim("claim-task",new DetectionTaskClaimService.Claim("1","candidate-race-"+id));winners.add(id);}catch(com.ruanzhu.doorhandle.common.BusinessException|SecurityException|org.springframework.security.access.AccessDeniedException expected){}catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new AssertionError(interrupted);}finally{SecurityContextHolder.clearContext();RequestContextHolder.resetRequestAttributes();}}));
            assertThat(ready.await(10,TimeUnit.SECONDS)).isTrue();start.countDown();for(var future:futures)future.get(30,TimeUnit.SECONDS);
        }finally{start.countDown();pool.shutdownNow();}
        assertThat(winners).hasSize(1);long winner=winners.get(0),loser=winner==1?2:1;
        assertThat(jdbc.queryForObject("SELECT assignee_user_id FROM detection_task WHERE task_id='claim-task'",Long.class)).isEqualTo(winner);assertThat(jdbc.queryForObject("SELECT claim_candidate_ids FROM detection_task WHERE task_id='claim-task'",String.class)).isNull();assertThat(jdbc.queryForObject("SELECT version FROM detection_task WHERE task_id='claim-task'",Long.class)).isEqualTo(2);
        request(loser,"loser-read");assertThat(scopedIds()).doesNotContain("claim-task");assertThat(context.getBean(DetectionMutationParticipant.class).mayRead(new AgentActor(loser,loser==1?"alice":"other",AgentActor.Role.INSPECTOR),"ENTERPRISE","DETECTION","DETECTION_TASK","claim-task")).isFalse();
        request(winner,"winner-read");assertThat(scopedIds()).contains("claim-task");assertThat(count("OPERATIONS")).isEqualTo(2);assertThat(count("BUSINESS_COMMAND")).isEqualTo(2);
    }
    @Test void candidateReadDoesNotGrantDirectServiceReviewRetryReportOrAgentRetryAndRevocationIsFresh(){
        supervisorOwnedTask();authorize("readonly-grant");request(2,"readonly-candidate");
        var policy=context.getBean(DetectionTaskAccessPolicy.class);var task=jdbc.queryForObject("SELECT * FROM detection_task WHERE task_id='claim-task'",BeanPropertyRowMapper.newInstance(DetectionTask.class));var actor=new AgentActor(2,"other",AgentActor.Role.INSPECTOR);
        assertThat(policy.canAccess(task,actor)).isTrue();assertThat(policy.canMutate(task,actor)).isFalse();
        var direct=new com.ruanzhu.doorhandle.module.detection.service.impl.DetectionTaskServiceImpl(context.getBean(DetectionTaskMapper.class),null,null,null,null,null,null,context.getBean(ObjectMapper.class),policy);
        assertThatThrownBy(()->direct.reviewTask("claim-task",null)).isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
        assertThatThrownBy(()->direct.retryTask("claim-task")).isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
        assertThatThrownBy(()->reports.create(new BusinessUserDirectory.Identity(2,"other",false),new Create("claim-task","No write","candidate narrative",key()))).isInstanceOf(SecurityException.class);
        var execution=new com.ruanzhu.doorhandle.module.detection.api.DetectionExecutionApiImpl(context.getBean(DetectionTaskMapper.class),context.getBean(DetectionTaskService.class),policy,context.getBean(BusinessUserDirectory.class),context.getBean(OperationsAuditApi.class),jdbc,context.getBean(ObjectMapper.class));
        assertThatThrownBy(()->execution.previewRetry(actor,"claim-task")).isInstanceOf(SecurityException.class);
        jdbc.update("UPDATE users SET enabled=FALSE WHERE id=2");assertThatThrownBy(()->policy.canAccess(task,actor)).isInstanceOf(SecurityException.class);assertThatThrownBy(this::scopedIds).isInstanceOf(SecurityException.class);assertThat(jdbc.queryForObject("SELECT assignee FROM detection_task WHERE task_id='claim-task'",String.class)).isNull();assertThat(count("OPERATIONS")).isEqualTo(1);
    }
    @Test void candidateGrantRejectsUnqualifiedMalformedAndUnapprovedAccountsAndCanBeRevoked(){
        supervisorOwnedTask();request(3,"invalid-candidates");
        for(var ids:List.of(List.of("01"),List.of("9223372036854775808"),List.of("1","1"),List.of("3"),List.of("99"))){String id=key();request(3,id);assertThatThrownBy(()->claims.authorize("claim-task",new DetectionTaskClaimService.Candidates(ids,"0",id))).isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);}
        jdbc.update("UPDATE users SET enabled=FALSE WHERE id=2");request(3,"disabled-grant");assertThatThrownBy(()->claims.authorize("claim-task",new DetectionTaskClaimService.Candidates(List.of("2"),"0","disabled-grant"))).isInstanceOf(SecurityException.class);jdbc.update("UPDATE users SET enabled=TRUE WHERE id=2");
        assertThat(count("OPERATIONS")).isZero();authorize("revoke-grant");request(2,"unauthorized-grant");assertThatThrownBy(()->claims.authorize("claim-task",new DetectionTaskClaimService.Candidates(List.of("2"),"1","unauthorized-grant"))).isInstanceOf(SecurityException.class);
        request(3,"revoke-candidates");claims.authorize("claim-task",new DetectionTaskClaimService.Candidates(List.of(),"1","revoke-candidates"));request(2,"revoked-read");assertThat(scopedIds()).doesNotContain("claim-task");assertThat(count("OPERATIONS")).isEqualTo(2);
    }
    @Test void directSupervisorAssignmentClearsCandidatesInTheSameVersionedAuditedTransaction() throws Exception {
        supervisorOwnedTask();authorize("assign-grant");request(3,"direct-assignment");((MockHttpServletRequest)((ServletRequestAttributes)RequestContextHolder.getRequestAttributes()).getRequest()).addHeader("X-Expected-Version","1");
        var service=new com.ruanzhu.doorhandle.module.detection.service.impl.DetectionTaskServiceImpl(context.getBean(DetectionTaskMapper.class),null,null,null,null,null,null,context.getBean(ObjectMapper.class),context.getBean(DetectionTaskAccessPolicy.class));
        service.setAssignmentDirectory(context.getBean(AgentUserDirectory.class),context.getBean(BusinessUserDirectory.class));
        var factory=new org.springframework.aop.aspectj.annotation.AspectJProxyFactory(service);factory.setProxyTargetClass(true);factory.addAspect(context.getBean(BusinessMutationAudit.class));
        com.ruanzhu.doorhandle.module.detection.service.impl.DetectionTaskServiceImpl proxied=factory.getProxy();
        var command=new com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskAssignmentRequest();command.setAssignee("alice");command.setQualityStation("review-station");
        var saved=proxied.assignQualityTask("claim-task",command);assertThat(saved.getVersion()).isEqualTo("2");assertThat(saved.getClaimCandidateUserIds()).isEmpty();
        assertThat(jdbc.queryForObject("SELECT claim_candidate_ids FROM detection_task WHERE task_id='claim-task'",String.class)).isNull();assertThat(jdbc.queryForObject("SELECT assignee FROM detection_task WHERE task_id='claim-task'",String.class)).isEqualTo("alice");
        assertThat(change("assignQualityTask","DETECTION").path("changes")).anySatisfy(field->{assertThat(field.path("field").asText()).isEqualTo("claim_candidate_ids");assertThat(field.path("after").isNull()).isTrue();});
        request(2,"assigned-loser-read");assertThat(scopedIds()).doesNotContain("claim-task");assertThat(count("OPERATIONS")).isEqualTo(2);
    }
    @Test void candidateStorageRejectsNonStringDuplicateOverflowAndOversizedLists(){
        for(String invalid:List.of("[1]","[\"01\"]","[\"1\",\"1\"]","[\"9223372036854775808\"]","[\"9999999999999999999\"]","{}",java.util.stream.LongStream.rangeClosed(1,17).mapToObj(id->"\""+id+"\"").collect(java.util.stream.Collectors.joining(",","[","]"))))
            assertThatThrownBy(()->jdbc.update("UPDATE detection_task SET claim_candidate_ids=? WHERE task_id='claim-task'",invalid)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        jdbc.update("UPDATE detection_task SET claim_candidate_ids='[\"9223372036854775807\"]' WHERE task_id='claim-task'");
        assertThat(com.ruanzhu.doorhandle.module.detection.security.DetectionClaimCandidates.read(jdbc.queryForObject("SELECT claim_candidate_ids FROM detection_task WHERE task_id='claim-task'",String.class))).containsExactly("9223372036854775807");
    }
}
