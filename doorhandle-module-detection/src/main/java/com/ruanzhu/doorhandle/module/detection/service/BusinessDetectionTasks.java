package com.ruanzhu.doorhandle.module.detection.service;

/** Formal detection work includes one-image batches and legacy tasks with no recorded type. */
public final class BusinessDetectionTasks {
    public static final String FILTER = filter("");
    private static final String RESULT_STATUSES = "('COMPLETED','PARTIAL_FAILED')";

    private BusinessDetectionTasks() {}

    public static String filter(String alias) {
        validateAlias(alias);
        String column = alias + "task_type";
        return "(" + column + " IS NULL OR " + column + " <> 'SINGLE')";
    }

    public static String verificationTaskFilter(String alias) {
        return "NOT EXISTS (" + dispatchedFolderForUpload(alias) + ")";
    }

    public static String completedResultFilter(String alias, String folderScope) {
        return "NOT EXISTS (" + dispatchedFolderForUpload(alias) + " AND f.status IN " + RESULT_STATUSES
                + " AND (" + folderScope + "))";
    }

    /** The upload owns capture location; a completed folder run is the fallback for standalone folders. */
    public static String completedCollectionFilter(String alias, String uploadScope) {
        requireQualifiedAlias(alias);
        return """
            NOT EXISTS (
              SELECT 1 FROM detection_work_unit fw
              JOIN detection_task o ON o.task_type IN ('BATCH','BATCH_DIRECT') AND o.status IN %2$s
              WHERE %1$stask_type='OSS_FOLDER' AND fw.work_unit_id=%1$stask_id COLLATE utf8mb4_0900_ai_ci
                AND fw.strategy='OSS_FOLDER' AND COALESCE(fw.assignee_user_id,'')<>''
                AND (%3$s) AND (%4$s)
            )
            """.formatted(alias, RESULT_STATUSES, uploadScope, uploadLineage("o.", alias));
    }

    /** Explicit source lineage takes precedence over the exact prefix used by older assignments. */
    public static String dispatchedFolderForUpload(String alias) {
        requireQualifiedAlias(alias);
        return """
            SELECT f.task_id FROM detection_task f
            JOIN detection_work_unit fw ON fw.work_unit_id=f.task_id COLLATE utf8mb4_0900_ai_ci
              AND fw.strategy='OSS_FOLDER' AND COALESCE(fw.assignee_user_id,'')<>''
            WHERE %1$stask_type IN ('BATCH','BATCH_DIRECT') AND f.task_type='OSS_FOLDER' AND f.status<>'CANCELLED'
              AND (%2$s)
            """.formatted(alias, uploadLineage(alias, "f."));
    }

    private static String uploadLineage(String uploadAlias, String folderAlias) {
        return uploadLineage(uploadAlias, folderAlias, "");
    }

    /** Trace queries check read access to both source and formal task and reject ambiguous legacy matches. */
    public static String traceUploadLineage(String uploadAlias, String folderAlias) {
        requireQualifiedAlias(uploadAlias);
        requireQualifiedAlias(folderAlias);
        String unambiguous = """
             AND NOT EXISTS (SELECT 1 FROM detection_task other_upload
                 WHERE other_upload.task_type IN ('BATCH','BATCH_DIRECT') AND other_upload.status<>'CANCELLED'
                   AND other_upload.id<>%1$sid AND BINARY other_upload.source_oss_prefix=BINARY %1$ssource_oss_prefix)
            """.formatted(uploadAlias);
        return uploadLineage(uploadAlias, folderAlias, unambiguous);
    }

    private static String uploadLineage(String uploadAlias, String folderAlias, String legacyConstraint) {
        return """
            EXISTS (SELECT 1 FROM detection_work_unit a WHERE a.batch_id=fw.work_unit_id
                        AND a.source_batch_id=%1$stask_id COLLATE utf8mb4_0900_ai_ci)
                OR (COALESCE(%1$ssource_oss_prefix,'')<>'' AND BINARY %1$ssource_oss_prefix=BINARY %2$ssource_oss_prefix
                    AND NOT EXISTS (SELECT 1 FROM detection_work_unit a WHERE a.batch_id=fw.work_unit_id
                                   AND COALESCE(a.source_batch_id,'')<>'') %3$s)
            """.formatted(uploadAlias, folderAlias, legacyConstraint);
    }

    private static void requireQualifiedAlias(String alias) {
        validateAlias(alias);
        if (alias.isEmpty()) throw new IllegalArgumentException("原图去重需要任务表别名");
    }

    private static void validateAlias(String alias) {
        if (!alias.matches("(?:[A-Za-z][A-Za-z0-9_]*\\.)?")) {
            throw new IllegalArgumentException("非法任务表别名");
        }
    }
}
