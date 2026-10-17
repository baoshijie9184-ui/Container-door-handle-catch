package com.ruanzhu.doorhandle.module.ai.model;

import java.util.Map;
import java.util.function.BiConsumer;

/** 订阅范围的模型路由元数据接收器；通过 Reactor Context 传递，不共享账号或运行状态。 */
public final class ModelAttemptTrace {
    public static final Object CONTEXT_KEY = new Object();
    public static final ModelAttemptTrace NONE = new ModelAttemptTrace((type, fields) -> {});
    private final BiConsumer<String, Map<String, Object>> recorder;

    public ModelAttemptTrace(BiConsumer<String, Map<String, Object>> recorder) {
        this.recorder = recorder;
    }

    void event(String type, Map<String, Object> fields) {
        try {
            recorder.accept(type, fields);
        } catch (RuntimeException error) {
            // 日志错误不是供应商故障，不能触发备用请求或改变供应商熔断状态。
            throw new RecordingException();
        }
    }

    static final class RecordingException extends RuntimeException {
        RecordingException() { super("模型调用轨迹保存失败"); }
    }
}
