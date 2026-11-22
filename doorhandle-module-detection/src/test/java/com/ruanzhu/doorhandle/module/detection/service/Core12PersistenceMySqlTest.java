package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql;
import com.ruanzhu.doorhandle.contracts.security.BusinessPrincipal;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionDuplicateTicket;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnitImage;
import com.ruanzhu.doorhandle.module.detection.entity.ImageDetectionData;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionDuplicateTicketMapper;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitImageMapper;
import com.ruanzhu.doorhandle.module.detection.mapper.ImageDetectionDataMapper;
import com.ruanzhu.doorhandle.module.detection.repository.QualityReportRepository;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.core.io.FileSystemResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;
import java.util.List;
import java.util.concurrent.*;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql.assertCheckViolation;

/** Historical class name retained; verifies the current 13-table core only on an admitted empty ECS schema. */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@EnabledIfSystemProperty(named = "doorhandle.core.mysql.config", matches = ".+")
class Core12PersistenceMySqlTest {
    JdbcTemplate jdbc;
    DetectionTaskMapper tasks;
    DetectionDuplicateTicketMapper duplicates;
    DetectionWorkUnitImageMapper inputs;
    ImageDetectionDataMapper history;

    @BeforeAll void createEmptyBaseline() throws Exception {
        var source = EcsIsolatedMysql.open(System.getProperty("doorhandle.core.mysql.config"), "doorhandle_detection_verify_");
        jdbc = new JdbcTemplate(source);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()", Long.class))
                .as("this contract requires its own empty ECS schema").isZero();
        try (var connection = source.getConnection()) {
            ScriptUtils.executeSqlScript(connection, new FileSystemResource("../sql/mysql/compact/baseline/10-core.sql"));
        }
        var config = new MybatisConfiguration();
        config.setMapUnderscoreToCamelCase(true);
        config.addMapper(DetectionTaskMapper.class);
        config.addMapper(DetectionDuplicateTicketMapper.class);
        config.addMapper(DetectionWorkUnitImageMapper.class);
        var factory = new MybatisSqlSessionFactoryBean();
        factory.setDataSource(source);
        factory.setConfiguration(config);
        factory.setMapperLocations(new FileSystemResource("src/main/resources/mapper/ImageDetectionDataMapper.xml"));
        var session = new SqlSessionTemplate(factory.getObject());
        tasks = session.getMapper(DetectionTaskMapper.class);
        duplicates = session.getMapper(DetectionDuplicateTicketMapper.class);
        inputs = session.getMapper(DetectionWorkUnitImageMapper.class);
        history = session.getMapper(ImageDetectionDataMapper.class);
    }

    @Test void physicalTablesAreDedicatedAndHaveNoWithdrawnDiscriminators() {
        assertThat(jdbc.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()", String.class))
                .containsExactlyInAnyOrder("users", "employee", "organization_department", "device_management", "device_usage", "device_alert",
                        "model_management", "detection_task", "detection_work_unit", "detection_input", "quality_report", "historical_detection_summary", "detection_duplicate_ticket");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND column_name IN ('record_kind','document_kind','image_kind','legacy_record_id')", Long.class)).isZero();
    }

    @Test void historicalCrudKeepsOriginalSemanticsAndCannotDeleteEqualTaskId() {
        var row = new ImageDetectionData();
        row.setFolderPath(""); row.setResultPath("old/results"); row.setAnnotatedImagesPath("old/annotations");
        row.setDetectedImagesCount(5077456); row.setDetectionInstancesCount(null);
        row.setMissDetectionRate(12.34); row.setStartTime(LocalDateTime.of(2021, 1, 1, 1, 2, 3));
        assertThat(history.insert(row)).isEqualTo(1);
        var task = new DetectionTask(); task.setId(row.getId()); task.setTaskId("core-history-isolation");
        task.setTaskType("BATCH"); task.setStatus("FAILED");
        assertThat(tasks.insert(task)).isEqualTo(1);
        var loaded = history.selectById(row.getId());
        assertThat(loaded.getDetectedImagesCount()).isEqualTo(5077456);
        assertThat(loaded.getDetectionInstancesCount()).isNull();
        assertThat(loaded.getMissDetectionRate()).isEqualTo(12.34);
        assertThat(loaded.getStartTime()).isEqualTo(row.getStartTime());
        loaded.setResultPath("corrected/results");
        assertThat(history.updateDetectionDataRecord(loaded)).isEqualTo(1);
        assertThat(history.selectAll()).extracting(ImageDetectionData::getResultPath).contains("corrected/results");
        assertThat(history.deleteById(row.getId())).isEqualTo(1);
        assertThat(tasks.selectById(task.getId()).getTaskId()).isEqualTo("core-history-isolation");
    }

    @Test void repeatedContentRemainsSeparateInputOccurrences() {
        String hash = "a".repeat(64);
        for (int index = 1; index <= 2; index++) {
            var row = new DetectionWorkUnitImage(); row.setImageId("core-input-" + index);
            row.setWorkUnitId("core-work-" + index); row.setFileName("same.jpg"); row.setSha256(hash);
            row.setObjectKey("originals/same.jpg"); row.setStatus("PENDING"); row.setVersion(0);
            assertThat(inputs.insert(row)).isEqualTo(1);
        }
        var first = inputs.findByWorkUnitId("core-work-1").get(0);
        assertThat(first.getContentAssetId()).isNull();
        first.setStatus("SUCCESS"); assertThat(inputs.updateById(first)).isEqualTo(1);
        assertThat(inputs.findByWorkUnitId("core-work-2").get(0).getStatus()).isEqualTo("PENDING");
    }

    @Test void qualityReportReadsUseDedicatedTableAndRetainApprovalFields() {
        jdbc.update("INSERT INTO quality_report(report_id,owner_user_id,owner_username,task_id,title,narrative,status,version,source_json,source_sha256,created_at,updated_at) VALUES('core-report',1,'owner','task-1','title','body','DRAFT',1,'{}',?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)", "b".repeat(64));
        var report = new QualityReportRepository(jdbc).get("core-report", false);
        assertThat(report.status()).isEqualTo("DRAFT");
        assertThat(report.snapshotSha256()).isNull();
        assertThat(report.taskId()).isEqualTo("task-1");
    }

    @Test void tracePagesPastFiftyUseTheSameScopeForTotalAndDetail() {
        for (int index=1; index<=53; index++) {
            insertTraceTask("paged-trace-task-"+index,"BATCH","paged-trace-batch","paged-trace-order",null,
                    index<=52 ? "trace-inspector" : "trace-other");
        }
        insertTraceTask("paged-trace-single","SINGLE","paged-trace-batch","paged-trace-order",null,"trace-inspector");
        var trace = traceRepository();
        try {
            authenticateTrace("trace-inspector",801L,false);
            for (boolean batch : new boolean[]{true,false}) {
                String reference = batch ? "paged-trace-batch" : "paged-trace-order";
                var first = trace.read(batch,reference,1,50);
                var second = trace.read(batch,reference,2,50);
                assertThat(first.summaryRows()).hasSize(52);
                assertThat(first.pageRows()).hasSize(50);
                assertThat(second.summaryRows()).hasSize(52);
                assertThat(second.pageRows()).extracting(row -> row.task().getTaskId())
                        .containsExactly("paged-trace-task-51","paged-trace-task-52");
                assertThat(trace.read(batch,reference,3,50).pageRows()).isEmpty();
            }
            authenticateTrace("trace-supervisor",800L,true);
            var department = trace.read(false,"paged-trace-order",2,50);
            assertThat(department.summaryRows()).hasSize(53);
            assertThat(department.pageRows()).extracting(row -> row.task().getTaskId()).containsExactly(
                    "paged-trace-task-51","paged-trace-task-52","paged-trace-task-53");
        } finally {
            SecurityContextHolder.clearContext();
        }
    }

    @Test void traceFollowsExplicitLineageWithoutExposingUnreadableSourcesAndRejectsAmbiguousLegacyLinks() {
        insertTraceTask("lineage-upload","BATCH","lineage-batch","lineage-source-order","detection/trace/original/","trace-other");
        insertTraceTask("lineage-formal","OSS_FOLDER",null,"lineage-formal-order","detection/trace/renamed/","trace-other");
        insertTraceFolderAssignment("lineage-formal","801");
        jdbc.update("""
                INSERT INTO detection_work_unit(work_unit_id,source_batch_id,batch_id,applicant_user_id,image_count,strategy,status)
                VALUES('lineage-request','lineage-upload','lineage-formal','trace-inspector',2,'ALL','ASSIGNED')
                """);
        insertTraceTask("legacy-trace-upload","BATCH","legacy-trace-batch",null,"detection/trace/legacy/","trace-inspector");
        insertTraceTask("legacy-trace-formal","OSS_FOLDER",null,null,"detection/trace/legacy/","trace-other");
        insertTraceFolderAssignment("legacy-trace-formal","801");
        insertTraceTask("ambiguous-trace-upload","BATCH","ambiguous-trace-batch",null,"detection/trace/ambiguous/","trace-inspector");
        insertTraceTask("ambiguous-other-upload","BATCH","ambiguous-other-batch",null,"detection/trace/ambiguous/","trace-other");
        insertTraceTask("ambiguous-trace-formal","OSS_FOLDER",null,null,"detection/trace/ambiguous/","trace-other");
        insertTraceFolderAssignment("ambiguous-trace-formal","801");
        var trace = traceRepository();
        try {
            authenticateTrace("trace-inspector",801L,false);
            var formalOnly = trace.read(true,"lineage-batch",1,10);
            assertThat(formalOnly.summaryRows()).hasSize(1);
            assertThat(formalOnly.pageRows()).singleElement().satisfies(row -> {
                assertThat(row.task().getTaskId()).isEqualTo("lineage-formal");
                assertThat(row.traceRole()).isEqualTo("FORMAL_TASK");
                assertThat(row.sourceTaskId()).isNull();
            });
            assertThat(trace.read(true,"legacy-trace-batch",1,10).pageRows()).extracting(DetectionTraceQuery.Row::traceRole)
                    .containsExactly("FORMAL_TASK","SOURCE_UPLOAD");
            assertThat(trace.read(true,"ambiguous-trace-batch",1,10).pageRows()).extracting(row -> row.task().getTaskId())
                    .containsExactly("ambiguous-trace-upload");
            authenticateTrace("trace-supervisor",800L,true);
            assertThat(trace.read(true,"lineage-batch",1,10).pageRows()).extracting(DetectionTraceQuery.Row::sourceTaskId)
                    .containsExactly("lineage-upload",null);
        } finally {
            SecurityContextHolder.clearContext();
        }
    }

    private DetectionTraceQuery traceRepository() {
        var access = new DetectionTaskAccessPolicy();
        var users = mock(BusinessUserDirectory.class);
        when(users.current(801L,"trace-inspector")).thenReturn(new BusinessUserDirectory.Identity(801L,"trace-inspector",false));
        when(users.current(800L,"trace-supervisor")).thenReturn(new BusinessUserDirectory.Identity(800L,"trace-supervisor",true));
        access.setUsers(users);
        ReflectionTestUtils.setField(access,"folderAssignments",jdbc);
        return new DetectionTraceQuery(new NamedParameterJdbcTemplate(jdbc),access);
    }

    private static void authenticateTrace(String username,long userId,boolean supervisor) {
        record TracePrincipal(Long userId,String username) implements BusinessPrincipal,java.security.Principal {
            @Override public String getName() { return username; }
        }
        var role = new SimpleGrantedAuthority(supervisor ? "ROLE_SUPERVISOR" : "ROLE_INSPECTOR");
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(new TracePrincipal(userId,username),null,List.of(role)));
    }

    private void insertTraceTask(String id,String type,String batch,String order,String prefix,String owner) {
        jdbc.update("""
                INSERT INTO detection_task(task_id,task_type,batch_no,work_order_no,source_oss_prefix,created_by,status)
                VALUES(?,?,?,?,?,?,'COMPLETED')
                """,id,type,batch,order,prefix,owner);
    }

    private void insertTraceFolderAssignment(String taskId,String assignee) {
        jdbc.update("""
                INSERT INTO detection_work_unit(work_unit_id,applicant_user_id,assignee_user_id,image_count,strategy,status)
                VALUES(?,'trace-supervisor',?,2,'OSS_FOLDER','COMPLETED')
                """,taskId,assignee);
    }

    private DetectionDuplicateTicket duplicate(String ticketId) {
        var row=new DetectionDuplicateTicket();row.setTicketId(ticketId);row.setSha256("A".repeat(64));
        row.setLeftTaskId("old-task-left");row.setRightTaskId("old-task-right");row.setAssignedTo("inspector-a");
        row.setStatus("OPEN");row.setVersion(0);row.setCreatedAt(LocalDateTime.of(2022,1,2,8,30));row.setUpdatedAt(row.getCreatedAt());
        return row;
    }
    @Test void duplicateTicketsKeepIndependentIdentitiesAndHistoricalEvidence(){
        var first=duplicate("duplicate-evidence-one");first.setId(9001L);first.setLeftEmployeeId("old-employee-code");
        first.setRightEmployeeId(null);first.setLeftFolderName("旧目录");first.setLeftImagesJson("[{\"objectKey\":\"evidence/left.jpg\"}]");
        first.setRightImagesJson("null");assertThat(duplicates.insert(first)).isEqualTo(1);
        var second=duplicate("duplicate-evidence-two");assertThat(duplicates.insert(second)).isEqualTo(1);
        var loaded=duplicates.selectById(9001L);
        assertThat(loaded.getTicketId()).isEqualTo(first.getTicketId());assertThat(loaded.getSha256()).isEqualTo("A".repeat(64));
        assertThat(loaded.getLeftEmployeeId()).isEqualTo("old-employee-code");assertThat(loaded.getRightEmployeeId()).isNull();
        assertThat(loaded.getLeftImagesJson()).contains("evidence/left.jpg");assertThat(loaded.getRightImagesJson()).isEqualTo("null");
        assertThat(duplicates.selectById(second.getId()).getRightImagesJson()).isNull();
        assertThat(loaded.getCreatedAt()).isEqualTo(first.getCreatedAt());
        assertThat(duplicates.findPending()).extracting(DetectionDuplicateTicket::getTicketId).contains(first.getTicketId(),second.getTicketId());
        assertThat(duplicates.countAssignedStatuses("inspector-a")).anySatisfy(item->{
            assertThat(item.get("status")).isEqualTo("OPEN");assertThat(((Number)item.get("total")).longValue()).isGreaterThanOrEqualTo(2);
        });
        // A repeated hash/task pair is legitimate; the original ticket identifier alone is unique.
        assertThatThrownBy(()->duplicates.insert(duplicate("DUPLICATE-EVIDENCE-ONE"))).isInstanceOf(org.springframework.dao.DuplicateKeyException.class);
    }
    @Test void duplicateConstraintsRejectIncompleteApprovalAndUnknownState(){
        var row=duplicate("duplicate-constraints");assertThat(duplicates.insert(row)).isEqualTo(1);
        assertCheckViolation(()->jdbc.update("UPDATE detection_duplicate_ticket SET status='RESOLVED' WHERE id=?",row.getId()), "ck_detection_duplicate_approval");
        assertCheckViolation(()->jdbc.update("UPDATE detection_duplicate_ticket SET status='UNKNOWN' WHERE id=?",row.getId()), "ck_detection_duplicate_status");
        assertCheckViolation(()->jdbc.update("UPDATE detection_duplicate_ticket SET version=-1 WHERE id=?",row.getId()), "ck_detection_duplicate_version");
        assertThat(duplicates.selectById(row.getId()).getStatus()).isEqualTo("OPEN");
    }
    @Test void duplicateApprovalUsesVersionCasAndDoesNotRewriteDetectionResults() throws Exception {
        var task=new DetectionTask();task.setTaskId("duplicate-left-protected");task.setTaskType("BATCH");task.setStatus("COMPLETED");
        assertThat(tasks.insert(task)).isEqualTo(1);
        var row=duplicate("duplicate-competing-approval");row.setLeftTaskId(task.getTaskId());assertThat(duplicates.insert(row)).isEqualTo(1);
        var service=new com.ruanzhu.doorhandle.module.detection.service.impl.DetectionDuplicateTicketServiceImpl(duplicates);
        var request=new com.ruanzhu.doorhandle.module.detection.dto.detection.DuplicateTicketResolveRequest();
        request.setExpectedVersion(0);request.setResolution(" ACCEPT_LEFT ");request.setComparisonResult("人工对比记录");
        var start=new CountDownLatch(1);var workers=Executors.newFixedThreadPool(2);
        try {
            Callable<Boolean> approval=()->{start.await();try{service.resolve(row.getTicketId(),request,"supervisor-a");return true;}
                catch(com.ruanzhu.doorhandle.common.BusinessException conflict){assertThat(conflict.getCode()).isEqualTo(409);return false;}};
            var left=workers.submit(approval);var right=workers.submit(approval);start.countDown();
            assertThat((left.get(10,TimeUnit.SECONDS)?1:0)+(right.get(10,TimeUnit.SECONDS)?1:0)).isEqualTo(1);
        } finally {workers.shutdownNow();}
        var resolved=duplicates.selectById(row.getId());assertThat(resolved.getVersion()).isEqualTo(1);
        assertThat(resolved.getStatus()).isEqualTo("RESOLVED");assertThat(resolved.getResolution()).isEqualTo("ACCEPT_LEFT");
        assertThat(resolved.getApprovedBy()).isEqualTo("supervisor-a");assertThat(resolved.getApprovedAt()).isNotNull();
        assertThat(tasks.selectById(task.getId()).getStatus()).isEqualTo("COMPLETED");
    }
}
