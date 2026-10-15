package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

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

    @Autowired
    private DetectionTaskAccessPolicy accessPolicy;

    @Autowired
    private NamedParameterJdbcTemplate scopedJdbc;


    /**
     * 获取检测记录列表
     */
    @GetMapping("")
    public Result getDetectionRecords(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size
    ) {
        log.info("获取检测记录列表, page: {}, size: {}", page, size);

        var scope = accessPolicy.currentSqlScope("");
        if (page < 1 || page > 10000 || size < 1 || size > 200) return Result.error(400, "分页参数无效");
        try {
            int offset = (page - 1) * size;

            String countSql = "SELECT COUNT(*) FROM detection_task WHERE " + scope.predicate();
            Integer total = scopedJdbc.queryForObject(countSql, scope.parameters(), Integer.class);

            String sql = "SELECT * FROM detection_task WHERE " + scope.predicate() + " ORDER BY created_at DESC LIMIT :size OFFSET :offset";
            Map<String, Object> parameters = new HashMap<>(scope.parameters());
            parameters.put("size", size);
            parameters.put("offset", offset);
            List<Map<String, Object>> records = scopedJdbc.queryForList(sql, parameters);

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

        var scope = accessPolicy.currentSqlScope("");
        try {
            String sql = "SELECT * FROM detection_task WHERE id = :id AND " + scope.predicate();
            Map<String, Object> parameters = new HashMap<>(scope.parameters());
            parameters.put("id", id);
            List<Map<String, Object>> records = scopedJdbc.queryForList(sql, parameters);
            if (records.isEmpty()) throw new org.springframework.security.access.AccessDeniedException("任务不存在或无访问权限");
            Map<String, Object> record = records.get(0);

            log.info("查询到检测记录详情: {}", record);

            return Result.success(record);
        } catch (org.springframework.security.access.AccessDeniedException e) {
            throw e;
        } catch (Exception e) {
            log.error("获取检测记录详情失败", e);
            return Result.error("获取检测记录详情失败");
        }
    }
}
