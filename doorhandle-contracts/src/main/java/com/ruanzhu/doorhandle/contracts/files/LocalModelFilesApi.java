package com.ruanzhu.doorhandle.contracts.files;

import java.nio.file.Path;

/** Model registry owns the mapping. A readable filesystem entry does not itself grant access. */
public interface LocalModelFilesApi {
    BusinessFileGrant authorizeFile(Path path);
}
