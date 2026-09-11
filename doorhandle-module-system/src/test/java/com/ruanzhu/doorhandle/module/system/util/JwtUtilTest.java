package com.ruanzhu.doorhandle.module.system.util;

import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class JwtUtilTest {

    @Test
    void rejectsPlaceholderJwtSecretBeforeSigningToken() {
        JwtUtil jwtUtil = new JwtUtil();
        ReflectionTestUtils.setField(jwtUtil, "secret", "your-secret-key");
        ReflectionTestUtils.setField(jwtUtil, "expiration", 3600L);

        assertThatThrownBy(() -> jwtUtil.generateToken("admin"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("JWT_SECRET")
                .hasMessageContaining("secure");
    }

    @Test
    void tokenCarriesImmutableUserId() {
        JwtUtil jwtUtil = new JwtUtil();
        ReflectionTestUtils.setField(jwtUtil, "secret", "01234567890123456789012345678901");
        ReflectionTestUtils.setField(jwtUtil, "expiration", 3600L);

        String token = jwtUtil.generateToken(42L, "alice");

        assertThat(jwtUtil.getUserIdFromToken(token)).isEqualTo(42L);
        assertThat(jwtUtil.getUsernameFromToken(token)).isEqualTo("alice");
    }
}
