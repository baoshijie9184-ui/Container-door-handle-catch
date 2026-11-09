package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionDuplicateTicket;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnitImage;
import com.ruanzhu.doorhandle.module.detection.entity.ImageDetectionData;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionDuplicateTicketMapper;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitImageMapper;
import com.ruanzhu.doorhandle.module.detection.mapper.ImageDetectionDataMapper;
import com.ruanzhu.doorhandle.module.detection.repository.QualityReportRepository;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.core.io.FileSystemResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ScriptUtils;

import java.time.LocalDateTime;
import java.util.concurrent.*;

import static org.assertj.core.api.Assertions.*;
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
