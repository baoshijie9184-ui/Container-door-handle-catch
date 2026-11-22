package com.ruanzhu.doorhandle.module.detection.api;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.DetectionAgentReadApi;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.service.BusinessDetectionTasks;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Map;

@Service
public class DetectionAgentReadApiImpl implements DetectionAgentReadApi {
    private static final String[] SUMMARY_COLUMNS = {
            "task_id", "status", "flow_status", "device_name", "total_images", "processed_images",
            "defect_count", "review_status", "review_conclusion", "created_at"
    };
    private final DetectionTaskMapper mapper;
    private final DetectionTaskAccessPolicy accessPolicy;
    public DetectionAgentReadApiImpl(DetectionTaskMapper mapper) { this(mapper, new DetectionTaskAccessPolicy()); }
    @Autowired
    public DetectionAgentReadApiImpl(DetectionTaskMapper mapper, DetectionTaskAccessPolicy accessPolicy) {
        this.mapper = mapper;
        this.accessPolicy = accessPolicy;
    }

    @Override
    public TaskPage tasks(AgentActor actor, int page, int size, boolean qualityOnly) {
        checkPage(page, size);
        QueryWrapper<DetectionTask> query = scope(actor);
        // 质检查询包括待复核及已有复核状态的记录；不把此列表解释为仅待办。
        if (qualityOnly) query.apply(BusinessDetectionTasks.FILTER).isNotNull("review_status");
        long total = mapper.selectCount(query);
        query.select(SUMMARY_COLUMNS).orderByDesc("created_at").orderByDesc("id")
                .last("LIMIT " + size + " OFFSET " + ((page - 1) * size));
        return new TaskPage(mapper.selectList(query).stream().map(this::view).toList(), total, page, size);
    }

    @Override
    public TaskView task(AgentActor actor, String taskId) {
        if (taskId == null || !taskId.matches("[A-Za-z0-9_-]{1,128}")) {
            throw new IllegalArgumentException("任务编号格式不正确");
        }
        DetectionTask task = mapper.selectOne(scope(actor).select(SUMMARY_COLUMNS).eq("task_id", taskId));
        if (task == null) throw new SecurityException("任务不存在或无访问权限");
        return view(task);
    }

    @Override
    public Metrics metrics(AgentActor actor, int days) {
        if (days < 1 || days > 366) throw new IllegalArgumentException("统计天数必须在 1 到 366 之间");
        LocalDateTime to = LocalDateTime.now();
        LocalDateTime from = to.minusDays(days);
        var query = new QueryWrapper<DetectionTask>();
        boolean supervisor = accessPolicy.applyAgentReadScope(query, actor);
        query.apply(BusinessDetectionTasks.FILTER).ge("created_at", from).lt("created_at", to);
        query.select("COUNT(*) AS taskCount", "COALESCE(SUM(total_images),0) AS imageCount",
                "COALESCE(SUM(processed_images),0) AS processedImageCount",
                "COALESCE(SUM(defect_count),0) AS defectCount");
        var rows = mapper.selectMaps(query);
        Map<String, Object> counts = rows.isEmpty() ? Map.of() : rows.get(0);
        return new Metrics(counts, from, to, supervisor ? "SINGLE_ENTERPRISE" : "OWNED_OR_ASSIGNED");
    }

    private QueryWrapper<DetectionTask> scope(AgentActor actor) {
        QueryWrapper<DetectionTask> query = new QueryWrapper<>();
        accessPolicy.applyAgentReadScope(query, actor);
        return query;
    }

    private TaskView view(DetectionTask t) {
        return new TaskView(t.getTaskId(), t.getStatus(), t.getFlowStatus(), t.getDeviceName(),
                t.getTotalImages(), t.getProcessedImages(), t.getDefectCount(),
                t.getReviewStatus(), t.getReviewConclusion(), t.getCreatedAt());
    }

    private void checkPage(int page, int size) {
        if (page < 1 || page > 10000 || size < 1 || size > 100) {
            throw new IllegalArgumentException("分页范围：page 1..10000，size 1..100");
        }
    }
}
