package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

import javax.sql.DataSource;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.*;

@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class HistoricalDetectionSummaryTest {
    JdbcTemplate jdbc;
    HistoricalDetectionSummaryService service;

    DataSource dataSource() {
        return new DriverManagerDataSource("jdbc:h2:mem:historical-summary;MODE=MySQL;DB_CLOSE_DELAY=-1", "sa", "");
    }

    @BeforeAll void start() {
        jdbc = new JdbcTemplate(dataSource());
        jdbc.execute("CREATE TABLE IF NOT EXISTS historical_detection_summary(id BIGINT AUTO_INCREMENT PRIMARY KEY,detected_images_count BIGINT,detection_instances_count BIGINT,model_id BIGINT,start_time DATETIME,finished_at DATETIME,folder_path VARCHAR(255),result_path VARCHAR(255))");
        service = new HistoricalDetectionSummaryService(jdbc, new DetectionTaskAccessPolicy());
    }

    @BeforeEach void reset() {
        jdbc.update("DELETE FROM historical_detection_summary");
        signIn("SUPERVISOR");
    }

    private void signIn(String role) {
        var auth = UsernamePasswordAuthenticationToken.authenticated("fixture-" + role, null,
                List.of(new SimpleGrantedAuthority("ROLE_" + role)));
        SecurityContextHolder.getContext().setAuthentication(auth);
    }

    @AfterEach void clear() { SecurityContextHolder.clearContext(); }

    @Test void aggregateRowsWithBlankImagePathsRemainVisibleAndSeparateFromCurrentTasks() {
        jdbc.update("INSERT INTO historical_detection_summary(detected_images_count,detection_instances_count,model_id,start_time,finished_at,folder_path,result_path) VALUES(3000000,4000000,1,'2021-01-01 01:02:03','2021-01-01 02:03:04','',''),(2077456,1564308,2,'2025-12-31 10:00:00','2025-12-31 11:00:00','','')");
        var result = service.summary();
        assertThat(result.recordCount()).isEqualTo(2);
        assertThat(result.imageCount()).isEqualTo(5077456);
        assertThat(result.targetCount()).isEqualTo(5564308);
        assertThat(result.modelCount()).isEqualTo(2);
        assertThat(result.yearlyTotals()).extracting(row -> row.year()).containsExactly(2021, 2025);
        assertThat(result.yearlyTotals().stream().mapToLong(row -> row.imageCount()).sum()).isEqualTo(result.imageCount());
        signIn("INSPECTOR");
        assertThat(service.summary()).isEqualTo(result);
    }

    @Test void legacyDatetimeIsReadAsStoredWithoutJvmTimezoneShift() {
        jdbc.update("INSERT INTO historical_detection_summary(detected_images_count,start_time,finished_at) VALUES(1,'2021-01-01 01:02:03','2025-12-31 11:00:00')");
        var result = service.summary();
        assertThat(result.firstRecordedAt()).isEqualTo(LocalDateTime.of(2021,1,1,1,2,3));
        assertThat(result.lastRecordedAt()).isEqualTo(LocalDateTime.of(2025,12,31,11,0));
    }

    @Test void absentTargetCountsStayUnknownAndEmptyHistoryDoesNotInventRecords() {
        var empty = service.summary();
        assertThat(empty.recordCount()).isZero();
        assertThat(empty.imageCount()).isZero();
        assertThat(empty.targetCount()).isNull();
        assertThat(empty.yearlyTotals()).isEmpty();
        jdbc.update("INSERT INTO historical_detection_summary(detected_images_count,start_time) VALUES(100,'2021-01-01')");
        assertThat(service.summary().targetCount()).isNull();
        assertThat(service.summary().yearlyTotals().get(0).targetCount()).isNull();
    }

    @Test void anonymousCannotReadHistoricalAggregate() {
        SecurityContextHolder.clearContext();
        assertThatThrownBy(service::summary).isInstanceOf(BusinessException.class);
    }
}
