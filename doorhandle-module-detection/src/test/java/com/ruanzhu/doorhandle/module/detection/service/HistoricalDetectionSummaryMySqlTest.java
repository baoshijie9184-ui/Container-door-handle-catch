package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.testsupport.FeatureMySql;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import javax.sql.DataSource;

@EnabledIfSystemProperty(named = "doorhandle.feature.mysql.config", matches = ".+")
class HistoricalDetectionSummaryMySqlTest extends HistoricalDetectionSummaryTest {
    @Override DataSource dataSource() { return FeatureMySql.source(); }
}
