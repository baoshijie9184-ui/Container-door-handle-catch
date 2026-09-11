package com.ruanzhu.doorhandle.common;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class SafePathResolverTest {

    private final SafePathResolver safePathResolver = new SafePathResolver();

    @TempDir
    Path tempDir;

    @Test
    void resolveUnderBaseAllowsNormalChildPath() {
        Path resolved = safePathResolver.resolveUnderBase(tempDir.toString(), "folder", "file.jpg");
        assertEquals(tempDir.resolve("folder").resolve("file.jpg").toAbsolutePath().normalize(), resolved);
    }

    @Test
    void resolveUnderBaseRejectsTraversalSegment() {
        assertThrows(BusinessException.class,
                () -> safePathResolver.resolveUnderBase(tempDir.toString(), "..", "file.jpg"));
    }

    @Test
    void resolveUnderBaseRejectsNestedInjectedSegment() {
        assertThrows(BusinessException.class,
                () -> safePathResolver.resolveUnderBase(tempDir.toString(), "folder/other", "file.jpg"));
    }

    @Test
    void resolveUnderBaseRejectsWindowsSeparatorInSegment() {
        assertThrows(BusinessException.class,
                () -> safePathResolver.resolveUnderBase(tempDir.toString(), "folder\\other", "file.jpg"));
    }

    @Test
    void resolveUnderBaseRejectsDriveLikeSegment() {
        assertThrows(BusinessException.class,
                () -> safePathResolver.resolveUnderBase(tempDir.toString(), "C:file.jpg"));
    }

    @Test
    void resolveUnderBaseRejectsControlCharacters() {
        assertThrows(BusinessException.class,
                () -> safePathResolver.resolveUnderBase(tempDir.toString(), "file\u0000.jpg"));
    }
}
