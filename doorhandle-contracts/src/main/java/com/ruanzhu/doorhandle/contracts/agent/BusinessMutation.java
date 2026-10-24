package com.ruanzhu.doorhandle.contracts.agent;

import java.lang.annotation.*;

/** Business write and its metadata audit must commit in one local transaction. */
@Retention(RetentionPolicy.RUNTIME) @Target(ElementType.METHOD)
public @interface BusinessMutation {
    String domain();String action();
    /** Trusted metadata selector: auto, arg0.id, result.modelId, or literal:collection for deliberate bulk operations. */
    String resource() default "auto";
    String version() default "";
    String request() default "";
    String scope() default "ENTERPRISE";
    boolean supervisorOnly() default false;
}
