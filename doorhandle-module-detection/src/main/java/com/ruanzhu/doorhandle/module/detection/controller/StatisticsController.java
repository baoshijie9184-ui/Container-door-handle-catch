package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.device.service.DeviceService;
import com.ruanzhu.doorhandle.module.device.service.DeviceUsageRecordService;
import com.ruanzhu.doorhandle.module.device.service.EmployeeService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.DashboardScope;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 统计数据控制器
 */
@RestController
@RequestMapping("/api/statistics")
@Slf4j
public class StatisticsController {
    private static final List<String> TREND_CLASSES = List.of("Normal", "Bent", "Deformed", "Rusty", "Missing", "Compromised");
    
    @Autowired
    private DeviceService deviceService;
    
    @Autowired
    private EmployeeService employeeService;
    
    @Autowired
    private DeviceUsageRecordService deviceUsageRecordService;
    
    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private DetectionTaskAccessPolicy accessPolicy;

    @Autowired
    private NamedParameterJdbcTemplate scopedJdbc;

    
    /**
     * 检查detection_task表是否存在以及是否有数据
     */
    @GetMapping("/check-detection-records")
    public Result checkDetectionRecords() {
        var scope = accessPolicy.currentSqlScope("");
        log.info("检查detection_task表状态");

        Map<String, Object> result = new HashMap<>();

        try {
            Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'detection_task'",
                Integer.class
            );

            result.put("tableExists", count != null && count > 0);

            if (count != null && count > 0) {
                Integer recordCount = scopedJdbc.queryForObject(
                    "SELECT COUNT(*) FROM detection_task WHERE " + scope.predicate(),
                    scope.parameters(), Integer.class
                );

                result.put("recordCount", recordCount);

                if (recordCount != null && recordCount > 0) {
                    List<Map<String, Object>> sampleData = scopedJdbc.queryForList(
                        "SELECT * FROM detection_task WHERE " + scope.predicate() + " LIMIT 1", scope.parameters()
                    );
                    result.put("sampleData", sampleData);
                }
            }

            log.info("检查detection_task表状态完成: {}", result);
            return Result.success(result);
        } catch (Exception e) {
            log.error("检查detection_task表出错", e);
            result.put("error", e.getMessage());
            return Result.error("检查detection_task表出错: " + e.getMessage());
        }
    }
    
    /**
     * 获取设备使用次数统计
     */
    @GetMapping("/device-usage-count")
    public Result getDeviceUsageCount() {
        log.info("获取设备使用次数统计");
        
        // 查询设备使用次数
        String sql = "SELECT d.device_code AS deviceCode, " +
                "d.model_name AS modelName, " +
                "d.device_type AS deviceType, " +
                "COUNT(dur.id) AS usageCount " +
                "FROM device_management d " +
                "LEFT JOIN device_usage dur ON d.id = dur.device_id " +
                "GROUP BY d.id, d.device_code, d.model_name, d.device_type " +
                "ORDER BY usageCount DESC";
        
        List<Map<String, Object>> result = jdbcTemplate.queryForList(sql);
        log.info("查询到设备使用次数统计: {}", result);
        
        return Result.success(result);
    }
    
    /**
     * 获取员工类型分布统计
     */
    @GetMapping("/employee-type-distribution")
    public Result getEmployeeTypeDistribution() {
        log.info("获取员工类型分布统计");
        
        String sql = "SELECT employee_type AS type, COUNT(*) AS count " +
                "FROM employee " +
                "GROUP BY employee_type";
        
        List<Map<String, Object>> result = jdbcTemplate.queryForList(sql);
        log.info("查询到员工类型分布统计: {}", result);
        
        return Result.success(result);
    }
    
    /**
     * 获取员工状态分布统计
     */
    @GetMapping("/employee-status-distribution")
    public Result getEmployeeStatusDistribution() {
        log.info("获取员工状态分布统计");
        
        String sql = "SELECT status, COUNT(*) AS count " +
                "FROM employee " +
                "GROUP BY status";
        
        List<Map<String, Object>> result = jdbcTemplate.queryForList(sql);
        log.info("查询到员工状态分布统计: {}", result);
        
        return Result.success(result);
    }
    
    /**
     * 获取设备状态分布统计
     */
    @GetMapping("/device-status-distribution")
    public Result getDeviceStatusDistribution() {
        log.info("获取设备状态分布统计");
        
        String sql = "SELECT status, COUNT(*) AS count " +
                "FROM device_management " +
                "GROUP BY status";
        
        List<Map<String, Object>> result = jdbcTemplate.queryForList(sql);
        log.info("查询到设备状态分布统计: {}", result);
        
        return Result.success(result);
    }
    
    /**
     * 获取检测记录趋势统计 — 从 detection_task 表
     */
    @GetMapping("/detection-trend")
    public Result<List<Map<String, Object>>> getDetectionTrend(@RequestParam(defaultValue = "month") String timeRange,
            @RequestParam(name = "scope", defaultValue = "ACCOUNT") DashboardScope audience) {
        var scope = audience.forCompletedResults(accessPolicy, "detection_task.");
        log.info("获取检测记录趋势统计，时间范围: {}", timeRange);

        String dateFormat;
        String interval;
        String groupBy;

        if ("week".equals(timeRange) || "day".equals(timeRange)) {
            dateFormat = "'%Y-%m-%d'";
            interval = "7 DAY";
            groupBy = "DATE_FORMAT(created_at, '%Y-%m-%d')";
        } else if ("month".equals(timeRange)) {
            dateFormat = "'%Y-%m'";
            interval = "12 MONTH";
            groupBy = "DATE_FORMAT(created_at, '%Y-%m')";
        } else if ("year".equals(timeRange)) {
            dateFormat = "'%Y'";
            interval = "5 YEAR";
            groupBy = "DATE_FORMAT(created_at, '%Y')";
        } else {
            dateFormat = "'%Y-%m-%d'";
            interval = "7 DAY";
            groupBy = "DATE_FORMAT(created_at, '%Y-%m-%d')";
        }

        try {
            boolean company = audience == DashboardScope.COMPANY;
            String where = "status IN ('COMPLETED', 'PARTIAL_FAILED') AND created_at IS NOT NULL AND " + scope.predicate();

            if (!"year".equals(timeRange)) {
                if (company) {
                    String firstDay = "month".equals(timeRange)
                            ? "DATE_SUB(DATE_FORMAT(CURRENT_DATE(), '%Y-%m-01'), INTERVAL 11 MONTH)"
                            : "DATE_SUB(CURRENT_DATE(), INTERVAL 6 DAY)";
                    where += " AND created_at >= " + firstDay + " AND created_at < CURRENT_DATE() + INTERVAL 1 DAY";
                } else {
                    where += " AND created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL " + interval + ")";
                }
            }

            String sql = company ? companyTrendSql(dateFormat, where) : accountTrendSql(dateFormat, where);
            sql += " GROUP BY " + groupBy + " ORDER BY MIN(created_at)";

            List<Map<String, Object>> result = scopedJdbc.queryForList(sql, scope.parameters());

            List<Map<String, Object>> processedResult = new ArrayList<>();
            for (Map<String, Object> row : result) {
                Map<String, Object> newRow = new HashMap<>();

                String date = (String) row.get("date");
                if (company) {
                    newRow.put("date", date);
                    newRow.put("taskCount", row.get("taskCount"));
                    newRow.put("classifiedTasks", row.get("classifiedTasks"));
                } else if ("month".equals(timeRange)) {
                    String[] parts = date.split("-");
                    if (parts.length == 2) {
                        newRow.put("date", parts[1] + "月");
                    } else {
                        newRow.put("date", date);
                    }
                } else if ("year".equals(timeRange)) {
                    newRow.put("date", date + "年");
                } else {
                    String[] parts = date.split("-");
                    if (parts.length == 3) {
                        newRow.put("date", parts[1] + "月" + parts[2] + "日");
                    } else {
                        newRow.put("date", date);
                    }
                }

                newRow.put("total", row.get("total") != null ? ((Number) row.get("total")).longValue() : 0L);
                for (String name : TREND_CLASSES) {
                    String key = name.toLowerCase(Locale.ROOT);
                    Number value = (Number) row.get(key);
                    newRow.put(key, company ? value : (value == null ? 0L : value.longValue()));
                }

                processedResult.add(newRow);
            }

            log.info("查询到检测记录趋势统计: {}", processedResult);

            return Result.success(processedResult);
        } catch (Exception e) {
            log.error("获取检测记录趋势统计失败", e);
            return Result.error("获取检测记录趋势统计失败: " + e.getMessage());
        }
    }

    private static String accountTrendSql(String dateFormat, String where) {
        String sums = TREND_CLASSES.stream().map(name ->
                "SUM(COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.%s')) AS UNSIGNED), 0)) AS %s"
                        .formatted(name, name.toLowerCase(Locale.ROOT)))
                .collect(Collectors.joining(", "));
        return "SELECT DATE_FORMAT(created_at, %s) AS date, SUM(total_images) AS total, %s FROM detection_task WHERE %s"
                .formatted(dateFormat, sums, where);
    }

    private static String companyTrendSql(String dateFormat, String where) {
        List<String> keys = TREND_CLASSES.stream().map(name -> name.toLowerCase(Locale.ROOT)).toList();
        String extracted = TREND_CLASSES.stream().map(name ->
                "JSON_EXTRACT(stats, '$.classCounts.%s') AS %s".formatted(name, name.toLowerCase(Locale.ROOT)))
                .collect(Collectors.joining(", "));
        // Compare each counter before casting so absent, fractional or malformed data cannot become zero.
        String complete = keys.stream().map(key -> "JSON_TYPE(%1$s) = 'INTEGER' AND JSON_UNQUOTE(%1$s) NOT LIKE '-%%'".formatted(key))
                .collect(Collectors.joining(" AND "));
        String sums = keys.stream().map(key -> "SUM(CASE WHEN classified THEN CAST(JSON_UNQUOTE(%1$s) AS DECIMAL(20,0)) END) AS %1$s".formatted(key))
                .collect(Collectors.joining(", "));
        return """
                WITH scoped_tasks AS (
                    SELECT created_at, total_images, successful_images, IF(JSON_VALID(statistics_json), statistics_json, '{}') AS stats
                    FROM detection_task WHERE %s
                ), class_counts AS (
                    SELECT created_at, total_images, successful_images, %s FROM scoped_tasks
                ), coverage AS (
                    SELECT class_counts.*, ((successful_images IS NULL OR successful_images <> 0) AND %s) AS classified
                    FROM class_counts
                )
                SELECT DATE_FORMAT(created_at, %s) AS date, SUM(total_images) AS total,
                       COUNT(*) AS taskCount, COUNT(CASE WHEN classified THEN 1 END) AS classifiedTasks,
                       %s
                FROM coverage
                """.formatted(where, extracted, complete, dateFormat, sums);
    }
    
    /**
     * 获取检测结果分布统计 — 从 detection_task 的 statistics_json 提取
     */
    @GetMapping("/detection-distribution")
    public Result getDetectionDistribution(@RequestParam(name = "scope", defaultValue = "ACCOUNT") DashboardScope audience) {
        var scope = audience.forCompletedResults(accessPolicy, "detection_task.");
        log.info("获取检测结果分布统计");

        String jc = "COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.%s')) AS UNSIGNED), 0)";
        String sql = """
                WITH totals AS (
                    SELECT SUM(%s) AS normal, SUM(%s) AS bent, SUM(%s) AS deformed,
                           SUM(%s) AS rusty, SUM(%s) AS missing, SUM(%s) AS compromised
                    FROM detection_task WHERE status IN ('COMPLETED','PARTIAL_FAILED') AND %s
                )
                SELECT '正常' AS result, normal AS count FROM totals
                UNION ALL SELECT '弯曲', bent FROM totals
                UNION ALL SELECT '形变', deformed FROM totals
                UNION ALL SELECT '锈蚀', rusty FROM totals
                UNION ALL SELECT '缺失', missing FROM totals
                UNION ALL SELECT '结构损伤', compromised FROM totals
                """.formatted(jc.formatted("Normal"), jc.formatted("Bent"), jc.formatted("Deformed"),
                jc.formatted("Rusty"), jc.formatted("Missing"), jc.formatted("Compromised"), scope.predicate());

        List<Map<String, Object>> result = scopedJdbc.queryForList(sql, scope.parameters());
        log.info("查询到检测结果分布统计: {}", result);

        return Result.success(result);
    }
} 
