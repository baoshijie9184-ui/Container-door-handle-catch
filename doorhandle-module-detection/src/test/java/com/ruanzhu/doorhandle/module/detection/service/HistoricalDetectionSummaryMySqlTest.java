package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.testsupport.FeatureMySql;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import java.time.LocalDateTime;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@EnabledIfEnvironmentVariable(named="DOORHANDLE_FEATURE_MYSQL_URL",matches="jdbc:mysql://127\\.0\\.0\\.1:13363/doorhandle_feature_.*")
class HistoricalDetectionSummaryMySqlTest {
    JdbcTemplate jdbc;HistoricalDetectionSummaryService service;DetectionTaskAccessPolicy access;
    @BeforeAll void start(){jdbc=new JdbcTemplate(FeatureMySql.source());jdbc.execute("CREATE TABLE IF NOT EXISTS image_detection_data(id BIGINT AUTO_INCREMENT PRIMARY KEY,detected_images_count BIGINT,detection_instances_count BIGINT,model_id BIGINT,start_time DATETIME,finished_at DATETIME,folder_path VARCHAR(255),result_path VARCHAR(255))");}
    @BeforeEach void reset(){FeatureMySql.clear(jdbc,"image_detection_data");access=mock(DetectionTaskAccessPolicy.class);when(access.isAdmin(any())).thenReturn(true);service=new HistoricalDetectionSummaryService(jdbc,access);SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken("fixture-boss","unused"));}
    @AfterEach void clear(){SecurityContextHolder.clearContext();}
    @Test void aggregateRowsWithBlankImagePathsRemainVisibleAndSeparateFromCurrentTasks(){
        jdbc.update("INSERT INTO image_detection_data(detected_images_count,detection_instances_count,model_id,start_time,finished_at,folder_path,result_path) VALUES(3000000,4000000,1,'2021-01-01 01:02:03','2021-01-01 02:03:04','',''),(2077456,1564308,2,'2025-12-31 10:00:00','2025-12-31 11:00:00','','')");
        var result=service.summary();assertThat(result.recordCount()).isEqualTo(2);assertThat(result.imageCount()).isEqualTo(5077456);assertThat(result.targetCount()).isEqualTo(5564308);assertThat(result.modelCount()).isEqualTo(2);assertThat(result.yearlyTotals()).extracting(row->row.year()).containsExactly(2021,2025);
        assertThat(result.yearlyTotals().stream().mapToLong(row->row.imageCount()).sum()).isEqualTo(result.imageCount());
    }
    @Test void legacyDatetimeIsReadAsStoredWithoutJvmTimezoneShift(){jdbc.update("INSERT INTO image_detection_data(detected_images_count,start_time,finished_at) VALUES(1,'2021-01-01 01:02:03','2025-12-31 11:00:00')");var result=service.summary();assertThat(result.firstRecordedAt()).isEqualTo(LocalDateTime.of(2021,1,1,1,2,3));assertThat(result.lastRecordedAt()).isEqualTo(LocalDateTime.of(2025,12,31,11,0));}
    @Test void absentTargetCountsStayUnknownAndEmptyHistoryDoesNotInventRecords(){var empty=service.summary();assertThat(empty.recordCount()).isZero();assertThat(empty.imageCount()).isZero();assertThat(empty.targetCount()).isNull();assertThat(empty.yearlyTotals()).isEmpty();jdbc.update("INSERT INTO image_detection_data(detected_images_count,start_time) VALUES(100,'2021-01-01')");assertThat(service.summary().targetCount()).isNull();assertThat(service.summary().yearlyTotals().get(0).targetCount()).isNull();}
    @Test void employeeCannotReadEnterpriseHistoricalAggregate(){when(access.isAdmin(any())).thenReturn(false);assertThatThrownBy(service::summary).isInstanceOf(AccessDeniedException.class);}
}
