package com.ruanzhu.doorhandle.module.app.config.properties;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class BusinessSeedDataPropertiesTest {

    @Test
    void defaultsKeepSeedImportDisabledAndOrderScriptsSafely() {
        BusinessSeedDataProperties properties = new BusinessSeedDataProperties();

        assertThat(properties.getEnabled()).isFalse();
        assertThat(properties.getContinueOnError()).isFalse();
        assertThat(properties.getScripts()).containsExactly(
                "classpath:db/migration-V14-security-reliability-hardening.sql",
                "classpath:db/migration-V13-business-seed-data-normalization.sql",
                "classpath:db/business-seed-new-features.sql",
                "classpath:db/business-seed-more-features.sql",
                "classpath:db/business-seed-trace-rich.sql"
        );
    }
}
