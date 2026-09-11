package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.device.service.DeviceService;
import com.ruanzhu.doorhandle.module.device.service.DeviceUsageRecordService;
import com.ruanzhu.doorhandle.module.device.service.EmployeeService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 统计数据控制器
 */
@RestController
@RequestMapping("/api/statistics")
@Slf4j
public class StatisticsController {
    
    @Autowired
    private DeviceService deviceService;
    
    @Autowired
    private EmployeeService employeeService;
    
    @Autowired
    private DeviceUsageRecordService deviceUsageRecordService;
    
    @Autowired
    private JdbcTemplate jdbcTemplate;
    
    /**
     * 检查detection_task表是否存在以及是否有数据
     */
    @GetMapping("/check-detection-records")
    public Result checkDetectionRecords() {
        log.info("检查detection_task表状态");

        Map<String, Object> result = new HashMap<>();

        try {
            Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'detection_task'",
                Integer.class
            );

            result.put("tableExists", count != null && count > 0);

            if (count != null && count > 0) {
                Integer recordCount = jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM detection_task",
                    Integer.class
                );

                result.put("recordCount", recordCount);

                if (recordCount != null && recordCount > 0) {
                    List<Map<String, Object>> sampleData = jdbcTemplate.queryForList(
                        "SELECT * FROM detection_task LIMIT 1"
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
                "LEFT JOIN device_usage_record dur ON d.id = dur.device_id " +
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
    public Result getDetectionTrend(@RequestParam(defaultValue = "month") String timeRange) {
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
            String jn = "COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Normal')) AS UNSIGNED), 0)";
            String jb = "COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Bent')) AS UNSIGNED), 0)";
            String jd = "COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Deformed')) AS UNSIGNED), 0)";
            String jr = "COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Rusty')) AS UNSIGNED), 0)";
            String jm = "COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Missing')) AS UNSIGNED), 0)";
            String jc = "COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Compromised')) AS UNSIGNED), 0)";

            String sql = "SELECT " +
                    "DATE_FORMAT(created_at, " + dateFormat + ") AS date, " +
                    "SUM(total_images) AS total, " +
                    "SUM(" + jn + ") AS normal, " +
                    "SUM(" + jb + ") AS bent, " +
                    "SUM(" + jd + ") AS deformed, " +
                    "SUM(" + jr + ") AS rusty, " +
                    "SUM(" + jm + ") AS missing, " +
                    "SUM(" + jc + ") AS compromised " +
                    "FROM detection_task " +
                    "WHERE status IN ('COMPLETED', 'PARTIAL_FAILED') AND created_at IS NOT NULL ";

            if (!"year".equals(timeRange)) {
                sql += "AND created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL " + interval + ") ";
            }

            sql += "GROUP BY " + groupBy + " " +
                    "ORDER BY MIN(created_at)";

            List<Map<String, Object>> result = jdbcTemplate.queryForList(sql);

            List<Map<String, Object>> processedResult = new ArrayList<>();
            for (Map<String, Object> row : result) {
                Map<String, Object> newRow = new HashMap<>();

                String date = (String) row.get("date");
                if ("month".equals(timeRange)) {
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

                newRow.put("total", row.get("total") != null ? ((Number) row.get("total")).intValue() : 0);
                newRow.put("normal", row.get("normal") != null ? ((Number) row.get("normal")).intValue() : 0);
                newRow.put("bent", row.get("bent") != null ? ((Number) row.get("bent")).intValue() : 0);
                newRow.put("deformed", row.get("deformed") != null ? ((Number) row.get("deformed")).intValue() : 0);
                newRow.put("rusty", row.get("rusty") != null ? ((Number) row.get("rusty")).intValue() : 0);
                newRow.put("missing", row.get("missing") != null ? ((Number) row.get("missing")).intValue() : 0);
                newRow.put("compromised", row.get("compromised") != null ? ((Number) row.get("compromised")).intValue() : 0);

                processedResult.add(newRow);
            }

            log.info("查询到检测记录趋势统计: {}", processedResult);

            return Result.success(processedResult);
        } catch (Exception e) {
            log.error("获取检测记录趋势统计失败", e);
            return Result.error("获取检测记录趋势统计失败: " + e.getMessage());
        }
    }
    
    /**
     * 获取检测结果分布统计 — 从 detection_task 的 statistics_json 提取
     */
    @GetMapping("/detection-distribution")
    public Result getDetectionDistribution() {
        log.info("获取检测结果分布统计");

        String jc = "COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.%s')) AS UNSIGNED), 0)";
        String filter = " FROM detection_task WHERE status IN ('COMPLETED', 'PARTIAL_FAILED')";

        String sql = "SELECT '正常' AS result, SUM(" + String.format(jc, "Normal") + ") AS count" + filter +
                " UNION ALL " +
                "SELECT '弯曲' AS result, SUM(" + String.format(jc, "Bent") + ") AS count" + filter +
                " UNION ALL " +
                "SELECT '形变' AS result, SUM(" + String.format(jc, "Deformed") + ") AS count" + filter +
                " UNION ALL " +
                "SELECT '锈蚀' AS result, SUM(" + String.format(jc, "Rusty") + ") AS count" + filter +
                " UNION ALL " +
                "SELECT '缺失' AS result, SUM(" + String.format(jc, "Missing") + ") AS count" + filter +
                " UNION ALL " +
                "SELECT '结构损伤' AS result, SUM(" + String.format(jc, "Compromised") + ") AS count" + filter;

        List<Map<String, Object>> result = jdbcTemplate.queryForList(sql);
        log.info("查询到检测结果分布统计: {}", result);

        return Result.success(result);
    }
} 
