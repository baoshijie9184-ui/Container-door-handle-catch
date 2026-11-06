package com.ruanzhu.doorhandle.module.app.config.properties;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class BusinessSeedDataPropertiesTest {

    @Test
    void defaultsKeepRetiredStartupImporterDisabledWithoutLegacyScripts() {
        BusinessSeedDataProperties properties = new BusinessSeedDataProperties();

        assertThat(properties.getEnabled()).isFalse();
        assertThat(properties.getContinueOnError()).isFalse();
        assertThat(properties.getScripts()).isEmpty();
    }
}
