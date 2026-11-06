package com.ruanzhu.doorhandle.module.app.testsupport;

import javax.sql.DataSource;

/** Only the caller-created loopback test server/database is eligible for destructive fixture cleanup. */
public final class FeatureMySql {
    private FeatureMySql(){}
    public static DataSource source(){
        try {
            return com.ruanzhu.doorhandle.module.app.EcsIsolatedMysql.open(
                    System.getProperty("doorhandle.feature.mysql.config"), "doorhandle_feature_");
        } catch (Exception error) {
            throw new IllegalStateException("Cannot initialize the explicit ECS feature fixture", error);
        }
    }
}
