package com.ruanzhu.doorhandle.module.ai.model;

import java.util.Map;
import java.util.function.BiConsumer;

/** Subscription-scoped actual provider-attempt usage; never a global account context. */
public record ModelUsageTrace(BiConsumer<String,Map<String,Object>> recorder) {
    public static final Object CONTEXT_KEY=new Object();
    public static final ModelUsageTrace NONE=new ModelUsageTrace((id,fields)->{});
    public void record(String id,Map<String,Object> fields){try{recorder.accept(id,fields);}catch(RuntimeException error){throw new ModelAttemptTrace.RecordingException();}}
}
