package com.ruanzhu.doorhandle.contracts.agent;

import java.lang.annotation.*;

/** HTTP delivery metadata only. Does not grant access; the owning controller must authorize the resource first. */
@Retention(RetentionPolicy.RUNTIME) @Target(ElementType.METHOD)
public @interface FileDelivery {
    String domain();String resource();String file() default "";String version() default "";
    String scope() default "PRIVATE";
}
