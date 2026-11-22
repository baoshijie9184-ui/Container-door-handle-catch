package com.ruanzhu.doorhandle.module.detection.service;

/** Formal detection work includes one-image batches and legacy tasks with no recorded type. */
public final class BusinessDetectionTasks {
    public static final String FILTER = filter("");

    private BusinessDetectionTasks() {}

    public static String filter(String alias) {
        validateAlias(alias);
        String column = alias + "task_type";
        return "(" + column + " IS NULL OR " + column + " <> 'SINGLE')";
    }

    public static String verificationTaskFilter(String alias) {
        return "NOT EXISTS (" + dispatchedFolderForUpload(alias) + ")";
    }

    /** Explicit source lineage takes precedence over the exact prefix used by older assignments. */
    public static String dispatchedFolderForUpload(String alias) {
        validateAlias(alias);
        if (alias.isEmpty()) throw new IllegalArgumentException("原图去重需要任务表别名");
        return """
            SELECT f.task_id FROM detection_task f
            JOIN detection_work_unit fw ON fw.work_unit_id=f.task_id COLLATE utf8mb4_0900_ai_ci
              AND fw.strategy='OSS_FOLDER' AND COALESCE(fw.assignee_user_id,'')<>''
            WHERE %1$stask_type IN ('BATCH','BATCH_DIRECT') AND f.task_type='OSS_FOLDER' AND f.status<>'CANCELLED'
              AND (EXISTS (SELECT 1 FROM detection_work_unit a WHERE a.batch_id=fw.work_unit_id
                        AND a.source_batch_id=%1$stask_id COLLATE utf8mb4_0900_ai_ci)
                OR (COALESCE(%1$ssource_oss_prefix,'')<>'' AND BINARY %1$ssource_oss_prefix=BINARY f.source_oss_prefix
                    AND NOT EXISTS (SELECT 1 FROM detection_work_unit a WHERE a.batch_id=fw.work_unit_id
                                   AND COALESCE(a.source_batch_id,'')<>'')))
            """.formatted(alias);
    }

    private static void validateAlias(String alias) {
        if (!alias.matches("(?:[A-Za-z][A-Za-z0-9_]*\\.)?")) {
            throw new IllegalArgumentException("非法任务表别名");
        }
    }
}
