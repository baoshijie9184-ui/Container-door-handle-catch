package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionQualityAction;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;

import java.util.List;
import java.util.Set;

/** Shared business-state rules for page hints and locked mutations; never grants account access. */
public final class DetectionQualityWorkflow {
    private static final Set<String> READY_STATUSES = Set.of("COMPLETED", "PARTIAL_FAILED");
    private static final Set<String> ASSIGNABLE_FLOWS = Set.of(
            "PENDING_REVIEW", "REVIEWING", "CONFIRMED", "REWORK_REQUIRED", "RECHECK_REQUIRED", "HOLD");
    private static final Set<String> RELEASE_CONCLUSIONS = Set.of("NORMAL_RELEASE", "FALSE_POSITIVE");

    private DetectionQualityWorkflow() {}

    public static List<DetectionQualityAction> actions(DetectionTask task) {
        return List.of(
                hint("ASSIGN", true, assignmentReason(task)),
                hint("REVIEW", false, reviewReason(task)),
                hint("DISPOSE", false, dispositionReason(task)),
                hint("SUBMIT_REWORK", false, reworkReason(task)),
                hint("ARCHIVE", true, archiveReason(task)));
    }

    private static DetectionQualityAction hint(String action, boolean supervisor, String reason) {
        return new DetectionQualityAction(action, reason.isEmpty(), supervisor, reason);
    }

    private static boolean ready(DetectionTask task) {
        return READY_STATUSES.contains(value(task.getStatus()));
    }

    private static String value(String value) {
        return value == null ? "" : value;
    }

    private static void require(String reason) {
        if (!reason.isEmpty()) throw new BusinessException(409, reason);
    }

    private static String assignmentReason(DetectionTask task) {
        if (!ready(task)) return "只有已完成检测的任务才能分派质检";
        if (!ASSIGNABLE_FLOWS.contains(value(task.getFlowStatus()))) return "当前业务阶段不允许重新分派";
        return "";
    }

    private static String reviewReason(DetectionTask task) {
        if (!ready(task)) return "检测尚未完成，不能进行人工复核";
        if (!Set.of("PENDING_REVIEW", "REVIEWING").contains(value(task.getFlowStatus()))) {
            return "仅待复核或复核中的任务可以提交结论；待复检任务须先完成实际检测";
        }
        if (!"PENDING".equals(task.getReviewStatus()) || "DISPOSED".equals(task.getDispositionStatus())) {
            return "本轮复核已提交或状态异常，请刷新核对";
        }
        return "";
    }

    private static boolean held(DetectionTask task) {
        return "HOLD".equals(task.getFlowStatus()) && "DISPOSED".equals(task.getDispositionStatus())
                && "HOLD".equals(task.getDispositionAction());
    }

    private static String dispositionReason(DetectionTask task) {
        if (!ready(task)) return "检测尚未完成，不能处置";
        if (!"REVIEWED".equals(task.getReviewStatus()) || task.getReviewedAt() == null
                || value(task.getReviewConclusion()).isBlank()) {
            return "须先通过人工复核保存完整结论，才能处置";
        }
        if (held(task)) return "";
        if (!"CONFIRMED".equals(task.getFlowStatus()) || "DISPOSED".equals(task.getDispositionStatus())) {
            return "当前阶段不允许处置或已经处置，请刷新核对";
        }
        return "";
    }

    private static String reworkReason(DetectionTask task) {
        if (!ready(task) || !"REWORK_REQUIRED".equals(task.getFlowStatus())
                || !"REVIEWED".equals(task.getReviewStatus()) || !"DISPOSED".equals(task.getDispositionStatus())
                || !"REWORK".equals(task.getDispositionAction())) {
            return "仅已明确决定返工的任务可以提交返工结果";
        }
        return "";
    }

    private static String archiveReason(DetectionTask task) {
        if (!ready(task) || !Set.of("RELEASED", "SCRAPPED").contains(value(task.getFlowStatus()))) {
            return "仅已放行或已报废的任务可以归档，未完成事项须先处理";
        }
        if (!"REVIEWED".equals(task.getReviewStatus()) || task.getReviewedAt() == null
                || !"DISPOSED".equals(task.getDispositionStatus()) || task.getDisposedAt() == null) {
            return "缺少完整复核或处置记录，不能归档";
        }
        if (Boolean.TRUE.equals(task.getRecheckRequired())) return "仍有复检要求，不能归档";
        if ("RELEASED".equals(task.getFlowStatus()) && (!"RELEASE".equals(task.getDispositionAction())
                || !RELEASE_CONCLUSIONS.contains(value(task.getReviewConclusion())))) {
            return "放行状态与复核、处置记录不一致，不能归档";
        }
        if ("SCRAPPED".equals(task.getFlowStatus()) && !"SCRAP".equals(task.getDispositionAction())) {
            return "报废状态与处置记录不一致，不能归档";
        }
        return "";
    }

    public static void assertAssignable(DetectionTask task) {
        require(assignmentReason(task));
    }

    public static String assignedFlow(DetectionTask task) {
        assertAssignable(task);
        return "PENDING_REVIEW".equals(task.getFlowStatus()) ? "REVIEWING" : task.getFlowStatus();
    }

    public static void assertReviewable(DetectionTask task) {
        require(reviewReason(task));
    }

    public static void assertDisposition(DetectionTask task, String action, boolean recheck) {
        require(dispositionReason(task));
        if (!Set.of("RELEASE", "REWORK", "RECHECK", "HOLD", "SCRAP").contains(value(action))) {
            throw new BusinessException(400, "处置动作无效");
        }
        if ("RELEASE".equals(action) && (!RELEASE_CONCLUSIONS.contains(value(task.getReviewConclusion()))
                || recheck || Boolean.TRUE.equals(task.getRecheckRequired()))) {
            throw new BusinessException(409, "确认缺陷或仍需复检的任务不能直接放行");
        }
        if ("SCRAP".equals(action) && recheck) {
            throw new BusinessException(409, "报废不能同时安排后续复检，请明确选择处置方式");
        }
        if (held(task) && "HOLD".equals(action)) {
            throw new BusinessException(409, "任务已经暂挂，请选择后续处置或继续保持现状");
        }
    }

    public static void assertRework(DetectionTask task, boolean recheck) {
        require(reworkReason(task));
        if (Boolean.TRUE.equals(task.getRecheckRequired()) && !recheck) {
            throw new BusinessException(409, "原处置已要求返工后复检，不能在回填结果时跳过");
        }
    }

    public static void assertGenericTransition(DetectionTask task, String target) {
        if (!"ARCHIVED".equals(target)) {
            throw new BusinessException(409, "状态必须由分派、复核、处置或实际复检动作产生，通用流转仅支持已闭环任务归档");
        }
        if (!"ARCHIVED".equals(task.getFlowStatus())) require(archiveReason(task));
    }
}
