package com.ruanzhu.doorhandle.module.detection.testsupport;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.core.io.ByteArrayResource;
import javax.sql.DataSource;
import java.nio.file.*;

/** Only the caller-created loopback test server/database is eligible for destructive fixture cleanup. */
public final class FeatureMySql {
    private FeatureMySql(){}
    public static DataSource source(){
        try {
            return com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql.open(
                    System.getProperty("doorhandle.feature.mysql.config"), "doorhandle_feature_");
        } catch (Exception error) {
            throw new IllegalStateException("Cannot initialize the explicit ECS feature fixture", error);
        }
    }
    public static void migrate(DataSource source,String name)throws Exception{
        byte[] sql=Files.readAllBytes(Path.of("../sql/mysql/"+name));
        try(var connection=source.getConnection()){ScriptUtils.executeSqlScript(connection,new ByteArrayResource(sql));}
    }
    public static void clear(JdbcTemplate jdbc,String... tables){for(String name:tables){if(!name.matches("[a-z_]+"))throw new IllegalArgumentException();jdbc.update("DELETE FROM "+name);}}
}
