package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.support.CoreCopyMySqlFixture;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.api.parallel.Execution;
import org.junit.jupiter.api.parallel.ExecutionMode;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;

import static org.assertj.core.api.Assertions.*;

/** Actual copy SQL, captured historical source declarations and complete current target DDL; ECS execution only. */
@EnabledIfSystemProperty(named="doorhandle.core.copy.source.config",matches=".+")
@Execution(ExecutionMode.SAME_THREAD)
class CoreCopyMigrationMySqlTest {
    private static final List<String> CORE=List.of("organization_department","employee","users","model_management","device_management",
            "device_usage","device_alert","detection_work_unit","detection_task","detection_input","quality_report","historical_detection_summary");
    private static final String JSON_EVIDENCE=" { \"items\": [1, null], \"label\": \"证据\" } ";
    private CoreCopyMySqlFixture fixture;
    private JdbcTemplate source,target;

    @BeforeEach void setUp() throws Exception {
        fixture=new CoreCopyMySqlFixture();source=fixture.source();target=fixture.target();seed();
    }
    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}

    @Test void copiesAllCoreEntitiesWithBindingHistoryBytesDatesAndDeletedHighWater() throws Exception {
        long expectedNext=source.queryForObject("SELECT AUTO_INCREMENT FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='users'",Long.class);
        fixture.copy();
        for(String table:CORE)assertThat(target.queryForObject("SELECT COUNT(*) FROM `"+table+"`",Long.class)).as(table).isPositive();
        assertThat(source.queryForObject("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='users' AND column_name IN ('enabled','account_version')",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM users WHERE enabled<>TRUE OR account_version<>0",Integer.class)).isZero();
        assertThat(source.queryForObject("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='version'",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM detection_task WHERE version<>0",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT binding_history_present FROM users WHERE id=1",Boolean.class)).isTrue();
        assertThat(target.queryForObject("SELECT binding_version FROM users WHERE id=1",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT employee_id FROM users WHERE id=1",Long.class)).isNull();
        assertThat(target.queryForObject("SELECT binding_history_present FROM users WHERE id=3",Boolean.class)).isFalse();
        assertThat(target.queryForObject("SELECT binding_version FROM users WHERE id=2",Integer.class)).isEqualTo(7);
        assertThat(target.queryForObject("SELECT employee_id FROM users WHERE id=2",Long.class)).isEqualTo(11L);
        assertThat(target.queryForObject("SELECT runtime_metadata_json FROM device_management WHERE id=31",String.class)).isEqualTo(JSON_EVIDENCE);
        assertThat(target.queryForObject("SELECT source_json FROM quality_report WHERE id=91",String.class)).isEqualTo(JSON_EVIDENCE);
        assertThat(target.queryForObject("SELECT CAST(created_at AS CHAR) FROM users WHERE id=1",String.class)).isEqualTo("2022-01-02 03:04:05");
        assertThat(target.queryForObject("SELECT finished_at FROM historical_detection_summary WHERE id=200",String.class)).isNull();
        assertThat(target.queryForObject("SELECT detection_instances_count FROM historical_detection_summary WHERE id=200",Integer.class)).isNull();
        assertThat(target.queryForObject("SELECT detected_images_count FROM historical_detection_summary WHERE id=200",Integer.class)).isEqualTo(5077456);
        assertThat(target.queryForObject("SELECT content_asset_id FROM detection_input WHERE id=81",String.class)).isNull();
        target.update("INSERT INTO users(username,password) VALUES('after-copy','fixture-only')");
        assertThat(target.queryForObject("SELECT id FROM users WHERE username='after-copy'",Long.class)).isEqualTo(expectedNext);
        assertThat(source.queryForObject("SELECT COUNT(*) FROM users",Long.class)).isEqualTo(3L);
    }

    @Test void optionalHistoricalColumnsUseOnlyDocumentedNullAndZeroBranches() throws Exception {
        source.execute("ALTER TABLE model_management DROP COLUMN training_image_count, DROP COLUMN training_completed_at, "
                + "DROP COLUMN evaluation_image_count, DROP COLUMN no_detection_image_count, DROP COLUMN inference_fps");
        source.execute("ALTER TABLE detection_work_unit DROP COLUMN project_id, DROP COLUMN batch_id, DROP COLUMN assigned_user_name");
        source.execute("ALTER TABLE detection_task DROP COLUMN assignment_identity_revision");
        fixture.copy();
        assertThat(target.queryForObject("SELECT training_image_count FROM model_management WHERE model_id=21",Integer.class)).isNull();
        assertThat(target.queryForObject("SELECT project_id FROM detection_work_unit WHERE id=61",String.class)).isNull();
        assertThat(target.queryForObject("SELECT assignment_identity_revision FROM detection_task WHERE id=71",Long.class)).isZero();
    }

    @Test void explicitHistoricalZeroIdIsNotRegenerated() throws Exception {
        source.execute((ConnectionCallback<Void>)connection->{
            try(var statement=connection.createStatement()) {
                statement.execute("SET @fixture_original_mode=@@SESSION.sql_mode");
                statement.execute("SET SESSION sql_mode=CONCAT_WS(',',@@SESSION.sql_mode,'NO_AUTO_VALUE_ON_ZERO')");
                try {statement.executeUpdate("INSERT INTO users(id,username,password) VALUES(0,'zero-id','fixture-only')");}
                finally {statement.execute("SET SESSION sql_mode=@fixture_original_mode");}
            }
            return null;
        });
        fixture.copy();
        assertThat(target.queryForObject("SELECT id FROM users WHERE username='zero-id'",Long.class)).isZero();
    }

    @Test void unknownSourceColumnStopsBeforeCopyAndRetainsOriginalData() {
        source.execute("ALTER TABLE device_management ADD COLUMN unreviewed_payload TEXT NULL");
        assertThatThrownBy(fixture::copy).isInstanceOf(Exception.class);
        assertCoreEmpty();assertThat(source.queryForObject("SELECT COUNT(*) FROM device_management",Long.class)).isEqualTo(1L);
    }

    @Test void changedSourceTypeIsNotSilentlyConverted() {
        source.execute("ALTER TABLE device_management MODIFY COLUMN model_name VARCHAR(101) NOT NULL");
        assertThatThrownBy(fixture::copy).isInstanceOf(Exception.class);assertCoreEmpty();
    }

    @Test void orphanBindingIsRejectedWithoutDeletingTheUnresolvedSourceRow() {
        source.execute((ConnectionCallback<Void>)connection->{
            try(var statement=connection.createStatement()) {
                statement.execute("SET FOREIGN_KEY_CHECKS=0");
                try {statement.executeUpdate("UPDATE account_employee_binding SET employee_id=999 WHERE user_id=1");}
                finally {statement.execute("SET FOREIGN_KEY_CHECKS=1");}
            }
            return null;
        });
        assertThatThrownBy(fixture::copy).isInstanceOf(Exception.class);assertCoreEmpty();
        assertThat(source.queryForObject("SELECT employee_id FROM account_employee_binding WHERE user_id=1",Long.class)).isEqualTo(999L);
    }

    @Test void caseInsensitiveSourceSessionReferenceRequiresAnExplicitResolution() {
        // The source unicode_ci foreign key accepts this; the target bin key cannot preserve it by guessing a spelling.
        source.update("UPDATE detection_task SET session_id='SESSION-ONE' WHERE id=71");
        assertThatThrownBy(fixture::copy).isInstanceOf(Exception.class);assertCoreEmpty();
        assertThat(source.queryForObject("SELECT session_id FROM detection_task WHERE id=71",String.class)).isEqualTo("SESSION-ONE");
    }

    @Test void exactComparisonRollsBackAllRowsOnLateTargetMutation() {
        target.execute("CREATE TRIGGER fixture_mutate_input BEFORE INSERT ON detection_input FOR EACH ROW SET NEW.object_key='changed-after-copy'");
        assertThatThrownBy(fixture::copy).isInstanceOf(Exception.class);assertCoreEmpty();
        assertThat(source.queryForObject("SELECT object_key FROM detection_work_unit_image WHERE id=81",String.class)).isEqualTo("images/source-one.jpg");
        // AUTO_INCREMENT reservation is deliberately DDL outside the row transaction and must not be claimed rolled back.
        assertThat(target.queryForObject("SELECT AUTO_INCREMENT FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='users'",Long.class))
                .isGreaterThan(1000L);
    }

    @Test void finalRelationsPreserveIdentityAndSourceDeleteUpdateActions() throws Exception {
        fixture.copy();fixture.copyChatReferenceAndInstallRelations();
        assertThatThrownBy(()->target.update("DELETE FROM users WHERE id=1")).isInstanceOf(Exception.class);
        assertThatThrownBy(()->target.update("UPDATE users SET id=101 WHERE id=1")).isInstanceOf(Exception.class);
        assertThatThrownBy(()->target.update("UPDATE users SET binding_history_present=FALSE WHERE id=1")).isInstanceOf(Exception.class);
        assertThatThrownBy(()->target.update("UPDATE users SET binding_version=6 WHERE id=2")).isInstanceOf(Exception.class);
        assertThatThrownBy(()->target.update("DELETE FROM employee WHERE id=11")).isInstanceOf(Exception.class);
        assertThat(target.update("DELETE FROM users WHERE id=3")).isEqualTo(1);
        target.update("UPDATE chat_session SET session_id='session-renamed' WHERE session_id='session-one'");
        assertThat(target.queryForObject("SELECT session_id FROM detection_task WHERE id=71",String.class)).isEqualTo("session-renamed");
        target.update("DELETE FROM chat_session WHERE session_id='session-renamed'");
        assertThat(target.queryForObject("SELECT session_id FROM detection_task WHERE id=71",String.class)).isNull();
        target.update("DELETE FROM device_management WHERE id=31");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM device_usage",Long.class)).isZero();
        assertThat(target.queryForObject("SELECT device_id FROM device_alert WHERE id=51",Long.class)).isNull();
        target.update("UPDATE model_management SET model_id=22 WHERE model_id=21");
        assertThat(target.queryForObject("SELECT model_id FROM detection_task WHERE id=71",Integer.class)).isEqualTo(22);
        assertThat(target.queryForObject("SELECT model_id FROM historical_detection_summary WHERE id=200",Integer.class)).isEqualTo(22);
        target.update("DELETE FROM model_management WHERE model_id=22");
        assertThat(target.queryForObject("SELECT model_id FROM detection_task WHERE id=71",Integer.class)).isNull();
        assertThat(target.queryForObject("SELECT model_id FROM historical_detection_summary WHERE id=200",Integer.class)).isNull();
        assertThat(source.queryForObject("SELECT session_id FROM detection_task WHERE id=71",String.class)).isEqualTo("session-one");
        assertThat(source.queryForObject("SELECT COUNT(*) FROM device_usage_record",Long.class)).isEqualTo(1L);
    }

    private void assertCoreEmpty() {
        for(String table:CORE)assertThat(target.queryForObject("SELECT COUNT(*) FROM `"+table+"`",Long.class)).as(table).isZero();
    }
    private void seed() {
        source.update("INSERT INTO organization_department(id,name) VALUES(10,'测试部门')");
        source.update("INSERT INTO employee(id,name,employee_number,contact,department,employee_type,gender,hire_date,status,department_id) "
                + "VALUES(11,'测试员工','fixture-11','fixture-contact','测试部门','DETECTION','UNKNOWN','2020-01-01','ACTIVE',10)");
        source.update("INSERT INTO users(id,username,password,email,created_at,updated_at) VALUES "
                + "(1,'history-empty','fixture-only',NULL,'2022-01-02 03:04:05',NULL),(2,'bound-user','fixture-only','fixture@example.invalid','2022-02-03 04:05:06','2022-02-03 04:05:06'),"
                + "(3,'never-bound','fixture-only',NULL,'2022-03-04 05:06:07',NULL),(1000,'deleted-high-id','fixture-only',NULL,NULL,NULL)");
        source.update("DELETE FROM users WHERE id=1000");
        source.update("INSERT INTO account_employee_binding(user_id,employee_id,version) VALUES(1,NULL,0),(2,11,7)");
        source.update("INSERT INTO model_management(model_id,model_name,version,model_path,training_image_count) VALUES(21,'fixture-model','v1','models/test.onnx',123)");
        source.update("INSERT INTO device_management(id,device_code,device_type,model_name,serial_number,status,employee_id,runtime_metadata_json) "
                + "VALUES(31,'fixture-device','CAMERA','fixture-camera','fixture-serial','IN_USE',11,?)",JSON_EVIDENCE);
        source.update("INSERT INTO device_usage_record(id,device_id,device_code,device_type,model_name,serial_number,employee_id,employee_name,employee_number,contact,start_time) "
                + "VALUES(41,31,'fixture-device','CAMERA','fixture-camera','fixture-serial',11,'测试员工','fixture-11','fixture-contact','2022-01-02 03:04:05')");
        source.update("INSERT INTO device_capture_alert(id,alert_id,device_id,device_code,alert_type,alert_message) VALUES(51,'alert-one',31,'fixture-device','CAPTURE_EXCEPTION','测试告警')");
        source.update("INSERT INTO detection_work_unit(id,work_unit_id,applicant_user_id,image_count,project_id) VALUES(61,'work-one','bound-user',1,'project-evidence')");
        source.update("INSERT INTO chat_session(id,session_id,username,user_id,title) VALUES(62,'session-one','bound-user',2,'测试会话')");
        source.update("INSERT INTO detection_task(id,task_id,status,model_id,session_id,created_user_id,created_identity_name,assignment_identity_revision,statistics_json) "
                + "VALUES(71,'task-one','SUCCEEDED',21,'session-one',2,'原始显示名',4,?)",JSON_EVIDENCE);
        source.update("INSERT INTO detection_work_unit_image(id,work_unit_id,image_id,file_name,object_key) VALUES(81,'work-one','image-one','one.jpg','images/source-one.jpg')");
        source.update("INSERT INTO detection_quality_report(id,report_id,owner_user_id,owner_username,task_id,title,narrative,status,version,source_json,source_sha256,created_at,updated_at) "
                + "VALUES(91,'report-one',2,'bound-user','task-one','测试报告','原始正文','DRAFT',0,?,?,'2022-01-02 03:04:05','2022-01-02 03:04:05')",JSON_EVIDENCE,"a".repeat(64));
        source.update("INSERT INTO image_detection_data(id,model_id,detected_images_count,normal_count,miss_detection_rate,start_time,finished_at,folder_path,result_path,detection_instances_count) "
                + "VALUES(200,21,5077456,NULL,12.34,'2021-01-01 01:02:03',NULL,'','historical/results',NULL)");
    }
}
