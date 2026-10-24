package com.ruanzhu.doorhandle.contracts.files;

import java.nio.file.Path;

/** Detection owns mapping and current account scope. Paths are internal, never browser DTOs. */
public interface LocalDetectionFilesApi {
    enum Kind { IMAGE, ANNOTATED, RESULT }
    BusinessFileGrant authorizeFile(Kind kind,Path path);
    default void authorize(Kind kind,Path path) { authorizeFile(kind,path); }
}
