package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 检测记录控制器 — 数据源为 detection_task 表
 */
@RestController
@RequestMapping("/api/detection-records")
@Slf4j
public class DetectionRecordController {

    @Autowired
    private JdbcTemplate jdbcTemplate;

    /**
     * 获取检测记录列表
     */
    @GetMapping("")
    public Result getDetectionRecords(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size
    ) {
        log.info("获取检测记录列表, page: {}, size: {}", page, size);

        try {
            int offset = (page - 1) * size;

            String countSql = "SELECT COUNT(*) FROM detection_task";
            Integer total = jdbcTemplate.queryForObject(countSql, Integer.class);

            String sql = "SELECT * FROM detection_task ORDER BY created_at DESC LIMIT ? OFFSET ?";
            List<Map<String, Object>> records = jdbcTemplate.queryForList(sql, size, offset);

            log.info("查询到检测记录数: {}", records.size());

            Map<String, Object> result = new HashMap<>();
            result.put("records", records);
            result.put("total", total);
            result.put("page", page);
            result.put("size", size);

            return Result.success(result);
        } catch (Exception e) {
            log.error("获取检测记录列表失败", e);
            return Result.error("获取检测记录列表失败");
        }
    }

    /**
     * 获取检测记录详情
     */
    @GetMapping("/detail")
    public Result getDetectionDetail(@RequestParam Long id) {
        log.info("获取检测记录详情, id: {}", id);

        try {
            String sql = "SELECT * FROM detection_task WHERE id = ?";
            Map<String, Object> record = jdbcTemplate.queryForMap(sql, id);

            log.info("查询到检测记录详情: {}", record);

            return Result.success(record);
        } catch (Exception e) {
            log.error("获取检测记录详情失败", e);
            return Result.error("获取检测记录详情失败");
        }
    }
}
