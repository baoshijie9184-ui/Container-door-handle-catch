package com.ruanzhu.doorhandle.module.infra.security;

import java.nio.file.Path;

/** 文件基础设施的权限端口，由检测模块实现，身份取自服务端上下文。 */
public interface LocalDetectionFileAuthorization {
    enum Kind { IMAGE, ANNOTATED, RESULT }
    void authorize(Kind kind, Path path);
}
