package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.ruanzhu.doorhandle.module.detection.service.DashboardService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 仪表盘服务实现类
 */
@Service
public class DashboardServiceImpl implements DashboardService {

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ofPattern("MM-dd");

    @Override
    @Cacheable(cacheNames = "dashboard", key = "'stats'")
    public Map<String, Object> getStats() {
        Map<String, Object> stats = new HashMap<>();

        // 从 detection_task 表统计 COMPLETED / PARTIAL_FAILED 的任务数
        List<Integer> detectionCounts = jdbcTemplate.queryForList(
            "SELECT COUNT(*) FROM detection_task WHERE status IN ('COMPLETED', 'PARTIAL_FAILED')", Integer.class);
        Integer detectionCount = detectionCounts.isEmpty() ? 0 : detectionCounts.get(0);

        // 从 statistics_json 提取平均漏检率
        List<Double> missRates = jdbcTemplate.queryForList(
            "SELECT AVG(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.missDetectionRate')) AS DECIMAL(10,4))) " +
            "FROM detection_task WHERE status IN ('COMPLETED', 'PARTIAL_FAILED') AND statistics_json IS NOT NULL", Double.class);
        Double avgMissRate = missRates.isEmpty() ? null : missRates.get(0);

        List<Integer> employeeCounts = jdbcTemplate.queryForList(
            "SELECT COUNT(*) FROM employee", Integer.class);
        Integer employeeCount = employeeCounts.isEmpty() ? 0 : employeeCounts.get(0);

        List<Integer> deviceCounts = jdbcTemplate.queryForList(
            "SELECT COUNT(*) FROM device_management", Integer.class);
        Integer deviceCount = deviceCounts.isEmpty() ? 0 : deviceCounts.get(0);

        stats.put("detectionCount", detectionCount != null ? detectionCount : 0);
        stats.put("employeeCount", employeeCount != null ? employeeCount : 0);
        stats.put("deviceCount", deviceCount != null ? deviceCount : 0);
        stats.put("avgMissRate", avgMissRate != null ? avgMissRate : 0.0);

        return stats;
    }

    @Override
    @Cacheable(cacheNames = "dashboard", key = "'trend:' + #timeRange")
    public Map<String, Object> getDetectionTrend(String timeRange) {
        Map<String, Object> result = new HashMap<>();
        
        // 设置查询参数
        String dateFormat;
        String interval;
        String groupBy;
        
        // 根据不同的时间范围参数设置查询条件
        if ("week".equals(timeRange) || "day".equals(timeRange)) {
            // 日视图：显示最近7天的数据，按天分组
            dateFormat = "'%Y-%m-%d'";
            interval = "7 DAY";
            groupBy = "DATE_FORMAT(created_at, '%Y-%m-%d')";
        } else if ("month".equals(timeRange)) {
            // 月视图：显示当年每月的数据，按月分组
            dateFormat = "'%Y-%m'";
            interval = "12 MONTH";
            groupBy = "DATE_FORMAT(created_at, '%Y-%m')";
        } else if ("year".equals(timeRange)) {
            // 年视图：显示近几年的数据，按年分组
            dateFormat = "'%Y'";
            interval = "5 YEAR";
            groupBy = "DATE_FORMAT(created_at, '%Y')";
        } else {
            // 默认为日视图
            dateFormat = "'%Y-%m-%d'";
            interval = "7 DAY";
            groupBy = "DATE_FORMAT(created_at, '%Y-%m-%d')";
        }

        // JSON_EXTRACT 辅助表达式
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

        // 添加时间过滤条件，"year"视图不限制时间范围
        if (!"year".equals(timeRange)) {
            sql += "AND created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL " + interval + ") ";
        }

        // 添加分组和排序
        sql += "GROUP BY " + groupBy + " " +
                "ORDER BY MIN(created_at)";
        
        // 执行查询
        List<Map<String, Object>> queryResult = jdbcTemplate.queryForList(sql);
        
        // 处理查询结果
        List<Map<String, Object>> seriesData = new ArrayList<>();
        List<String> labels = new ArrayList<>();
        List<Integer> totalData = new ArrayList<>();
        List<Integer> normalData = new ArrayList<>();
        List<Integer> bentData = new ArrayList<>();
        List<Integer> deformedData = new ArrayList<>();
        List<Integer> rustyData = new ArrayList<>();
        List<Integer> missingData = new ArrayList<>();
        List<Integer> compromisedData = new ArrayList<>();
        
        // 处理结果，提取数据系列和标签
        for (Map<String, Object> row : queryResult) {
            // 处理日期显示格式
            String date = (String) row.get("date");
            String formattedDate;
            
            if ("month".equals(timeRange)) {
                // 转换为 "年-月" 格式为 "x月"
                String[] parts = date.split("-");
                if (parts.length == 2) {
                    formattedDate = parts[1] + "月";
                } else {
                    formattedDate = date;
                }
            } else if ("year".equals(timeRange)) {
                // 添加"年"后缀
                formattedDate = date + "年";
            } else {
                // 对于日视图，转换为 "月-日" 格式
                String[] parts = date.split("-");
                if (parts.length == 3) {
                    formattedDate = parts[1] + "月" + parts[2] + "日";
                } else {
                    formattedDate = date;
                }
            }
            
            labels.add(formattedDate);
            
            // 提取数值并确保是整数
            int total = row.get("total") != null ? ((Number) row.get("total")).intValue() : 0;
            int normal = row.get("normal") != null ? ((Number) row.get("normal")).intValue() : 0;
            int bent = row.get("bent") != null ? ((Number) row.get("bent")).intValue() : 0;
            int deformed = row.get("deformed") != null ? ((Number) row.get("deformed")).intValue() : 0;
            int rusty = row.get("rusty") != null ? ((Number) row.get("rusty")).intValue() : 0;
            int missing = row.get("missing") != null ? ((Number) row.get("missing")).intValue() : 0;
            int compromised = row.get("compromised") != null ? ((Number) row.get("compromised")).intValue() : 0;
            
            totalData.add(total);
            normalData.add(normal);
            bentData.add(bent);
            deformedData.add(deformed);
            rustyData.add(rusty);
            missingData.add(missing);
            compromisedData.add(compromised);
            
            // 也添加原始格式的数据，供前端选用
            Map<String, Object> item = new HashMap<>();
            item.put("date", formattedDate);
            item.put("total", total);
            item.put("normal", normal);
            item.put("bent", bent);
            item.put("deformed", deformed);
            item.put("rusty", rusty);
            item.put("missing", missing);
            item.put("compromised", compromised);
            seriesData.add(item);
        }
        
        // 构建前端所需的完整数据结构
        result.put("labels", labels);
        
        // 构建系列数据
        List<Map<String, Object>> series = new ArrayList<>();
        
        Map<String, Object> totalSeries = new HashMap<>();
        totalSeries.put("name", "检测图片数");
        totalSeries.put("data", totalData);
        series.add(totalSeries);
        
        Map<String, Object> normalSeries = new HashMap<>();
        normalSeries.put("name", "正常");
        normalSeries.put("data", normalData);
        series.add(normalSeries);
        
        Map<String, Object> bentSeries = new HashMap<>();
        bentSeries.put("name", "弯曲");
        bentSeries.put("data", bentData);
        series.add(bentSeries);

        Map<String, Object> deformedSeries = new HashMap<>();
        deformedSeries.put("name", "形变");
        deformedSeries.put("data", deformedData);
        series.add(deformedSeries);

        Map<String, Object> rustySeries = new HashMap<>();
        rustySeries.put("name", "锈蚀");
        rustySeries.put("data", rustyData);
        series.add(rustySeries);

        Map<String, Object> missingSeries = new HashMap<>();
        missingSeries.put("name", "缺失");
        missingSeries.put("data", missingData);
        series.add(missingSeries);

        Map<String, Object> compromisedSeries = new HashMap<>();
        compromisedSeries.put("name", "结构损伤");
        compromisedSeries.put("data", compromisedData);
        series.add(compromisedSeries);
        
        result.put("series", series);
        result.put("rawData", seriesData);
        
        return result;
    }

    @Override
    @Cacheable(cacheNames = "dashboard", key = "'distribution'")
    public Map<String, Object> getDetectionDistribution() {
        Map<String, Object> result = new HashMap<>();
        List<Map<String, Object>> seriesList = new ArrayList<>();
        
        // 查询检测结果分布 — 从 detection_task 的 statistics_json 提取
        String sql = "SELECT " +
                    "SUM(COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Normal')) AS UNSIGNED), 0)) as normal, " +
                    "SUM(COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Bent')) AS UNSIGNED), 0)) as bent, " +
                    "SUM(COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Deformed')) AS UNSIGNED), 0)) as deformed, " +
                    "SUM(COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Rusty')) AS UNSIGNED), 0)) as rusty, " +
                    "SUM(COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Missing')) AS UNSIGNED), 0)) as missing, " +
                    "SUM(COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(statistics_json, '$.classCounts.Compromised')) AS UNSIGNED), 0)) as compromised " +
                    "FROM detection_task WHERE status IN ('COMPLETED', 'PARTIAL_FAILED')";
        
        Map<String, Object> data = jdbcTemplate.queryForMap(sql);
        
        // 使用数据库查询结果
        Map<String, Object> normal = new HashMap<>();
        normal.put("name", "正常");
        normal.put("value", data.get("normal") != null ? data.get("normal") : 0);
        
        Map<String, Object> bent = new HashMap<>();
        bent.put("name", "弯曲");
        bent.put("value", data.get("bent") != null ? data.get("bent") : 0);

        Map<String, Object> deformed = new HashMap<>();
        deformed.put("name", "形变");
        deformed.put("value", data.get("deformed") != null ? data.get("deformed") : 0);

        Map<String, Object> rusty = new HashMap<>();
        rusty.put("name", "锈蚀");
        rusty.put("value", data.get("rusty") != null ? data.get("rusty") : 0);

        Map<String, Object> missing = new HashMap<>();
        missing.put("name", "缺失");
        missing.put("value", data.get("missing") != null ? data.get("missing") : 0);

        Map<String, Object> compromised = new HashMap<>();
        compromised.put("name", "结构损伤");
        compromised.put("value", data.get("compromised") != null ? data.get("compromised") : 0);
        
        seriesList.add(normal);
        seriesList.add(bent);
        seriesList.add(deformed);
        seriesList.add(rusty);
        seriesList.add(missing);
        seriesList.add(compromised);
        
        result.put("series", seriesList);
        
        return result;
    }

    @Override
    @Cacheable(cacheNames = "dashboard", key = "'region-stats'")
    public List<Map<String, Object>> getRegionStats() {
        String sql = "SELECT " +
                "CASE " +
                "  WHEN region LIKE '%区' THEN '北京' " +
                "  ELSE COALESCE(region, '未知地区') " +
                "END AS city, " +
                "SUM(total_images) AS imageCount, " +
                "COUNT(*) AS taskCount " +
                "FROM detection_task " +
                "WHERE status IN ('COMPLETED', 'PARTIAL_FAILED') " +
                "GROUP BY city " +
                "ORDER BY imageCount DESC";

        List<Map<String, Object>> queryResult = jdbcTemplate.queryForList(sql);
        List<Map<String, Object>> result = new ArrayList<>();

        for (Map<String, Object> row : queryResult) {
            Map<String, Object> item = new HashMap<>();
            item.put("region", row.get("city"));
            item.put("imageCount", row.get("imageCount") != null ? ((Number) row.get("imageCount")).intValue() : 0);
            item.put("taskCount", row.get("taskCount") != null ? ((Number) row.get("taskCount")).intValue() : 0);
            result.add(item);
        }

        return result;
    }

    @Override
    @Cacheable(cacheNames = "dashboard", key = "'model-stats'")
    public List<Map<String, Object>> getModelStats() {
        String sql = "SELECT " +
                "m.model_id AS modelId, " +
                "CONCAT(m.model_name, ' ', m.version) AS modelName, " +
                "COUNT(t.id) AS taskCount, " +
                "COALESCE(SUM(t.total_images), 0) AS totalImages, " +
                "COALESCE(AVG(CAST(JSON_UNQUOTE(JSON_EXTRACT(t.statistics_json, '$.missDetectionRate')) AS DECIMAL(10,4))), 0) AS avgMissRate " +
                "FROM model_management m " +
                "LEFT JOIN detection_task t ON m.model_id = t.model_id AND t.status IN ('COMPLETED', 'PARTIAL_FAILED') " +
                "GROUP BY m.model_id, m.model_name, m.version " +
                "HAVING taskCount > 0 " +
                "ORDER BY taskCount DESC";

        List<Map<String, Object>> queryResult = jdbcTemplate.queryForList(sql);
        List<Map<String, Object>> result = new ArrayList<>();

        for (Map<String, Object> row : queryResult) {
            Map<String, Object> item = new HashMap<>();
            item.put("modelId", row.get("modelId"));
            item.put("modelName", row.get("modelName"));
            item.put("taskCount", row.get("taskCount") != null ? ((Number) row.get("taskCount")).intValue() : 0);
            item.put("totalImages", row.get("totalImages") != null ? ((Number) row.get("totalImages")).longValue() : 0);
            item.put("avgMissRate", row.get("avgMissRate") != null ? ((Number) row.get("avgMissRate")).doubleValue() : 0.0);
            result.add(item);
        }

        return result;
    }

    @Override
    @Cacheable(cacheNames = "dashboard", key = "'quality-disposition-stats'")
    public Map<String, Object> getQualityDispositionStats() {
        String summarySql = "SELECT 'summary' AS summary, " +
                "COUNT(*) AS reviewedCount, " +
                "SUM(CASE WHEN review_status = 'REVIEWED' AND (disposition_status IS NULL OR disposition_status = 'PENDING') THEN 1 ELSE 0 END) AS pendingDispositionCount, " +
                "SUM(CASE WHEN disposition_status = 'DISPOSED' THEN 1 ELSE 0 END) AS disposedCount, " +
                "SUM(CASE WHEN recheck_required = 1 THEN 1 ELSE 0 END) AS recheckRequiredCount " +
                "FROM detection_task WHERE review_status = 'REVIEWED'";
        List<Map<String, Object>> summaryRows = jdbcTemplate.queryForList(summarySql);
        Map<String, Object> summary = summaryRows.isEmpty() ? Map.of() : summaryRows.get(0);

        String actionSql = "SELECT disposition_action AS action, COUNT(*) AS count " +
                "FROM detection_task " +
                "WHERE disposition_status = 'DISPOSED' AND disposition_action IS NOT NULL " +
                "GROUP BY disposition_action";
        List<Map<String, Object>> actionRows = jdbcTemplate.queryForList(actionSql);
        Map<String, Integer> actionCounts = new HashMap<>();
        for (Map<String, Object> row : actionRows) {
            Object action = row.get("action");
            Object count = row.get("count");
            if (action != null) {
                actionCounts.put(action.toString(), count == null ? 0 : ((Number) count).intValue());
            }
        }

        Map<String, Object> result = new HashMap<>();
        result.put("reviewedCount", toInt(summary.get("reviewedCount")));
        result.put("pendingDispositionCount", toInt(summary.get("pendingDispositionCount")));
        result.put("disposedCount", toInt(summary.get("disposedCount")));
        result.put("recheckRequiredCount", toInt(summary.get("recheckRequiredCount")));
        result.put("series", buildDispositionSeries(actionCounts));
        return result;
    }

    @Override
    @Cacheable(cacheNames = "dashboard", key = "'quality-workload'")
    public Map<String, Object> getQualityWorkload() {
        String sql = "SELECT 'quality_workload' AS workload, " +
                "SUM(CASE WHEN status IN ('COMPLETED', 'PARTIAL_FAILED') AND review_status = 'PENDING' THEN 1 ELSE 0 END) AS pendingReviewCount, " +
                "SUM(CASE WHEN review_status = 'REVIEWED' AND (disposition_status IS NULL OR disposition_status = 'PENDING') THEN 1 ELSE 0 END) AS pendingDispositionCount, " +
                "SUM(CASE WHEN flow_status = 'RECHECK_REQUIRED' OR recheck_required = 1 THEN 1 ELSE 0 END) AS recheckRequiredCount, " +
                "SUM(CASE WHEN flow_status = 'REWORK_REQUIRED' THEN 1 ELSE 0 END) AS reworkRequiredCount, " +
                "SUM(CASE WHEN flow_status = 'HOLD' THEN 1 ELSE 0 END) AS holdCount, " +
                "SUM(CASE WHEN status = 'FAILED' OR flow_status = 'FAILED' THEN 1 ELSE 0 END) AS failedCount " +
                "FROM detection_task";
        List<Map<String, Object>> rows = jdbcTemplate.queryForList(sql);
        Map<String, Object> row = rows.isEmpty() ? Map.of() : rows.get(0);

        int pendingReviewCount = toInt(row.get("pendingReviewCount"));
        int pendingDispositionCount = toInt(row.get("pendingDispositionCount"));
        int recheckRequiredCount = toInt(row.get("recheckRequiredCount"));
        int reworkRequiredCount = toInt(row.get("reworkRequiredCount"));
        int holdCount = toInt(row.get("holdCount"));
        int failedCount = toInt(row.get("failedCount"));

        Map<String, Object> result = new HashMap<>();
        result.put("pendingReviewCount", pendingReviewCount);
        result.put("pendingDispositionCount", pendingDispositionCount);
        result.put("recheckRequiredCount", recheckRequiredCount);
        result.put("reworkRequiredCount", reworkRequiredCount);
        result.put("holdCount", holdCount);
        result.put("failedCount", failedCount);
        result.put("totalActionableCount", pendingReviewCount + pendingDispositionCount + recheckRequiredCount
                + reworkRequiredCount + holdCount + failedCount);
        result.put("queues", buildQualityWorkloadQueues(
                pendingReviewCount,
                pendingDispositionCount,
                recheckRequiredCount,
                reworkRequiredCount,
                holdCount,
                failedCount
        ));
        return result;
    }

    private List<Map<String, Object>> buildQualityWorkloadQueues(int pendingReviewCount,
                                                                  int pendingDispositionCount,
                                                                  int recheckRequiredCount,
                                                                  int reworkRequiredCount,
                                                                  int holdCount,
                                                                  int failedCount) {
        List<Map<String, Object>> queues = new ArrayList<>();
        queues.add(queueItem("待复核", "PENDING_REVIEW", pendingReviewCount));
        queues.add(queueItem("待处置", "PENDING_DISPOSITION", pendingDispositionCount));
        queues.add(queueItem("需复检", "RECHECK_REQUIRED", recheckRequiredCount));
        queues.add(queueItem("需返工", "REWORK_REQUIRED", reworkRequiredCount));
        queues.add(queueItem("隔离中", "HOLD", holdCount));
        queues.add(queueItem("检测失败", "FAILED", failedCount));
        return queues;
    }

    private Map<String, Object> queueItem(String name, String status, int count) {
        Map<String, Object> item = new HashMap<>();
        item.put("name", name);
        item.put("status", status);
        item.put("count", count);
        return item;
    }

    private List<Map<String, Object>> buildDispositionSeries(Map<String, Integer> actionCounts) {
        List<Map<String, Object>> series = new ArrayList<>();
        series.add(dispositionItem("放行", actionCounts.getOrDefault("RELEASE", 0)));
        series.add(dispositionItem("返工", actionCounts.getOrDefault("REWORK", 0)));
        series.add(dispositionItem("复检", actionCounts.getOrDefault("RECHECK", 0)));
        series.add(dispositionItem("隔离", actionCounts.getOrDefault("HOLD", 0)));
        series.add(dispositionItem("报废", actionCounts.getOrDefault("SCRAP", 0)));
        return series;
    }

    private Map<String, Object> dispositionItem(String name, int value) {
        Map<String, Object> item = new HashMap<>();
        item.put("name", name);
        item.put("value", value);
        return item;
    }

    private int toInt(Object value) {
        return value == null ? 0 : ((Number) value).intValue();
    }
}
