package com.ruanzhu.doorhandle.module.system.security;

import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.regex.Pattern;

@Component
public class SensitiveDataSanitizer {

    private static final String MASK = "[REDACTED]";

    private final List<Pattern> patterns = List.of(
            Pattern.compile("-----BEGIN [A-Z ]*PRIVATE KEY-----[\\s\\S]*?-----END [A-Z ]*PRIVATE KEY-----", Pattern.CASE_INSENSITIVE),
            Pattern.compile("(?i)(password|passwd|pwd|db_password|redis_password|secret|token|api[_-]?key|access[_-]?key[_-]?secret)\\s*[:=]\\s*[^\\s,;\"']+"),
            Pattern.compile("(?i)(bearer\\s+)[A-Za-z0-9._\\-+/=]{16,}"),
            Pattern.compile("(?i)(jdbc:mysql://[^\\s]+?)(password=)[^&\\s]+"),
            Pattern.compile("AKIA[0-9A-Z]{16}"),
            Pattern.compile("eyJ[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}")
    );

    public String sanitize(String input) {
        if (!StringUtils.hasText(input)) {
            return input;
        }
        String sanitized = input;
        for (Pattern pattern : patterns) {
            sanitized = pattern.matcher(sanitized).replaceAll(MASK);
        }
        return sanitized;
    }

    public boolean containsSensitiveData(String input) {
        if (!StringUtils.hasText(input)) {
            return false;
        }
        return patterns.stream().anyMatch(pattern -> pattern.matcher(input).find());
    }
}
