package com.ruanzhu.doorhandle.module.app.testsupport;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.core.io.ByteArrayResource;
import javax.sql.DataSource;
import java.nio.file.*;
import java.util.Locale;

/** Only the caller-created loopback test server/database is eligible for destructive fixture cleanup. */
public final class FeatureMySql {
    private FeatureMySql(){}
    public static DataSource source(){
        String url=System.getenv("DOORHANDLE_FEATURE_MYSQL_URL");
        if(url==null||!url.matches("jdbc:mysql://127\\.0\\.0\\.1:13363/doorhandle_feature_[a-f0-9]{12}\\?.*"))throw new IllegalStateException("Explicit isolated feature database required");
        var source=new DriverManagerDataSource(url,"root","");var jdbc=new JdbcTemplate(source);
        String directory=jdbc.queryForObject("SELECT @@datadir",String.class).replace('\\','/').toLowerCase(Locale.ROOT);
        if(!directory.contains("/work/feature-tests-20261027/mysql-data/")||jdbc.queryForObject("SELECT @@port",Integer.class)!=13363)throw new IllegalStateException("Unexpected database target");
        return source;
    }
    public static void migrate(DataSource source,String name)throws Exception{
        byte[] sql=Files.readAllBytes(Path.of("../sql/mysql/"+name));
        try(var connection=source.getConnection()){ScriptUtils.executeSqlScript(connection,new ByteArrayResource(sql));}
    }
    public static void clear(JdbcTemplate jdbc,String... tables){for(String name:tables){if(!name.matches("[a-z_]+"))throw new IllegalArgumentException();jdbc.update("DELETE FROM "+name);}}
}
