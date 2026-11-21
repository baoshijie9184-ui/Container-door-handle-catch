package com.ruanzhu.doorhandle.module.detection.service;

/** Formal detection work includes one-image batches and legacy tasks with no recorded type. */
public final class BusinessDetectionTasks {
    public static final String FILTER = filter("");

    private BusinessDetectionTasks() {}

    public static String filter(String alias) {
        if (!alias.matches("(?:[A-Za-z][A-Za-z0-9_]*\\.)?")) {
            throw new IllegalArgumentException("非法任务表别名");
        }
        String column = alias + "task_type";
        return "(" + column + " IS NULL OR " + column + " <> 'SINGLE')";
    }
}
