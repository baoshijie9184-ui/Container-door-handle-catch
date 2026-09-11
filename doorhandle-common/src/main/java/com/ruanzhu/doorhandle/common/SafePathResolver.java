package com.ruanzhu.doorhandle.common;

import org.springframework.stereotype.Component;

import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.text.Normalizer;

@Component
public class SafePathResolver {

    public Path resolveUnderBase(String baseDir, String... segments) {
        try {
            Path basePath = Paths.get(baseDir).toAbsolutePath().normalize();
            Path resolvedPath = basePath;
            for (String segment : segments) {
                String safeSegment = validateSegment(segment);
                resolvedPath = resolvedPath.resolve(safeSegment);
            }

            resolvedPath = resolvedPath.normalize();
            if (!resolvedPath.startsWith(basePath)) {
                throw new BusinessException("非法路径访问");
            }
            return resolvedPath;
        } catch (InvalidPathException e) {
            throw new BusinessException("非法路径参数");
        }
    }

    private String validateSegment(String segment) {
        if (segment == null || segment.isBlank()) {
            throw new BusinessException("路径参数不能为空");
        }
        String normalized = Normalizer.normalize(segment, Normalizer.Form.NFKC);
        if (normalized.contains("..")
                || normalized.contains("/")
                || normalized.contains("\\")
                || normalized.contains(":")
                || normalized.chars().anyMatch(Character::isISOControl)) {
            throw new BusinessException("非法路径访问");
        }

        Path path = Paths.get(normalized);
        if (path.isAbsolute() || path.getNameCount() != 1) {
            throw new BusinessException("非法路径访问");
        }
        return normalized;
    }
}
