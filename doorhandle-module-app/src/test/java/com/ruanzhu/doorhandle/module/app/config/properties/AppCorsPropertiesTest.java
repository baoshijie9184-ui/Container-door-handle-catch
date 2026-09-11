package com.ruanzhu.doorhandle.module.app.config.properties;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AppCorsPropertiesTest {

    @Test
    void defaultOriginsSupportLocalhostAndLoopbackFrontend() {
        AppCorsProperties properties = new AppCorsProperties();

        assertThat(properties.getAllowedOrigins())
                .contains("http://localhost:3001", "http://127.0.0.1:3001");
    }
}
