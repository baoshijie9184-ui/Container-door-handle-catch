package com.ruanzhu.doorhandle.module.app.config;

import com.ruanzhu.doorhandle.module.app.config.properties.BusinessSeedDataProperties;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class BusinessSeedRetirementTest {
    @Test
    void explicitLegacyOverrideCannotExecuteStartupSqlAgainstCompactDatabase() {
        var properties = new BusinessSeedDataProperties();
        properties.setEnabled(true);
        properties.setContinueOnError(true);
        properties.setScripts(List.of("classpath:db/migration-V13-business-seed-data-normalization.sql"));
        var runner = new BusinessSeedDataConfig(properties).importBusinessSeedData();
        var error = assertThrows(IllegalStateException.class, () -> runner.run());
        assertTrue(error.getMessage().contains("已退役"));
    }
}
