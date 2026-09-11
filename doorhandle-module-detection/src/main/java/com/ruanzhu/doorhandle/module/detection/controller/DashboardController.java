package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.detection.service.DashboardService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 仪表盘控制器
 * 提供仪表盘统计数据、趋势数据和分布数据
 */
@RestController
@RequestMapping("/api/dashboard")
public class DashboardController {

    @Autowired
    private DashboardService dashboardService;

    @Autowired
    private com.ruanzhu.doorhandle.module.detection.service.DetectionWorkloadDashboardService workloadDashboardService;

    @GetMapping("/work-unit-summary")
    @org.springframework.security.access.prepost.PreAuthorize("hasAnyRole('INSPECTOR', 'SUPERVISOR', 'ADMIN')")
    public Result<Map<String, Object>> getWorkUnitSummary() {
        return Result.success(workloadDashboardService.summary());
    }

    @GetMapping("/duplicate-summary")
    @org.springframework.security.access.prepost.PreAuthorize("hasAnyRole('INSPECTOR', 'SUPERVISOR', 'ADMIN')")
    public Result<Map<String, Object>> getDuplicateSummary() {
        return Result.success(workloadDashboardService.duplicateSummary());
    }
    
    @Autowired
    private JdbcTemplate jdbcTemplate;

    /**
     * 获取仪表盘统计数据
     * @return 统计数据
     */
    @GetMapping("/stats")
    public Result getStats() {
        Map<String, Object> stats = dashboardService.getStats();
        return Result.success(stats);
    }

    /**
     * 获取检测记录趋势数据
     * @param timeRange 时间范围：week/month/year
     * @return 趋势数据
     */
    @GetMapping("/detection-trend")
    public Result getDetectionTrend(@RequestParam(defaultValue = "month") String timeRange) {
        Map<String, Object> trendData = dashboardService.getDetectionTrend(timeRange);
        return Result.success(trendData);
    }

    /**
     * 获取检测结果分布数据
     * @return 分布数据
     */
    @GetMapping("/detection-distribution")
    public Result getDetectionDistribution() {
        Map<String, Object> distributionData = dashboardService.getDetectionDistribution();
        return Result.success(distributionData);
    }

    /**
     * 获取各地区图片采集量统计
     * @return 各地区的采集图片数量和任务数
     */
    @GetMapping("/region-stats")
    public Result getRegionStats() {
        return Result.success(dashboardService.getRegionStats());
    }

    /**
     * 获取模型使用统计
     * @return 各模型的使用次数、检测图片数、平均漏检率
     */
    @GetMapping("/model-stats")
    public Result getModelStats() {
        return Result.success(dashboardService.getModelStats());
    }

    /**
     * 获取质检处置统计
     * @return 待处置、已处置、复检和处置动作分布
     */
    @GetMapping("/quality-disposition-stats")
    public Result getQualityDispositionStats() {
        return Result.success(dashboardService.getQualityDispositionStats());
    }

    /**
     * 获取质检待办工作量
     * @return 待复核、待处置、需复检、返工、隔离和失败任务队列
     */
    @GetMapping("/quality-workload")
    public Result getQualityWorkload() {
        return Result.success(dashboardService.getQualityWorkload());
    }
    
    /**
     * 检查实际的员工和设备数量
     * @return 员工和设备数量
     */
    @GetMapping("/check-counts")
    public Result checkCounts() {
        Map<String, Object> counts = new HashMap<>();
        
        Integer employeeCount = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM employee", 
            Integer.class
        );
        
        Integer deviceCount = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM device_management", 
            Integer.class
        );
        
        counts.put("employeeCount", employeeCount != null ? employeeCount : 0);
        counts.put("deviceCount", deviceCount != null ? deviceCount : 0);
        
        return Result.success(counts);
    }
} 
