package com.ruanzhu.doorhandle.module.infra.security;

/** @deprecated Historical port; production callers use the contracts-owned LocalDetectionFilesApi. */
@Deprecated
public interface LocalDetectionFileAuthorization {
    enum Kind { IMAGE, ANNOTATED, RESULT }
    void authorize(Kind kind,java.nio.file.Path path);
}
