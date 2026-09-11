package com.ruanzhu.doorhandle.module.system.security;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SensitiveDataSanitizerTest {

    private final SensitiveDataSanitizer sanitizer = new SensitiveDataSanitizer();

    @Test
    void sanitizeMasksSecretsBeforeExternalUse() {
        String input = """
                token=eyJhbGciOiJIUzI1NiJ9.abcdefghijklmnop.qrstuvwxyz123456
                DB_PASSWORD=root123
                -----BEGIN PRIVATE KEY-----
                abcdefg
                -----END PRIVATE KEY-----
                """;

        String sanitized = sanitizer.sanitize(input);

        assertTrue(sanitized.contains("[REDACTED]"));
        assertFalse(sanitized.contains("root123"));
        assertFalse(sanitized.contains("BEGIN PRIVATE KEY"));
        assertFalse(sanitized.contains("eyJhbGciOiJIUzI1NiJ9"));
    }
}
