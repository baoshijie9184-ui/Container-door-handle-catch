package com.ruanzhu.doorhandle.module.detection.support;

import com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ScriptUtils;

/** Real compact DDL, admitted empty ECS schema, and cleanup restricted to this fixture's tables. */
public final class CompactDetectionMySqlFixture implements AutoCloseable {
    private final DriverManagerDataSource source;
    private final Set<String> owned=new HashSet<>();
    private boolean admitted;
    public CompactDetectionMySqlFixture(String property) throws Exception {
        org.junit.jupiter.api.Assumptions.assumeTrue(System.getProperty(property)!=null,
                "An explicit disposable ECS compact-detection fixture is required");
        source=EcsIsolatedMysql.open(System.getProperty(property),"doorhandle_detection_verify_");
        source.setUrl(source.getUrl().replace("serverTimezone=Asia/Shanghai","connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true"));
        if(!tables().isEmpty())throw new SecurityException("Compact detection fixture must begin with an empty schema");
        admitted=true;
        try {
            for(String name:ListParts.NAMES){
                Path path=Path.of("../sql/mysql/compact/baseline",name);
                var matcher=Pattern.compile("(?im)^CREATE TABLE(?: IF NOT EXISTS)?\\s+([a-z_]+)\\s*\\(").matcher(Files.readString(path));
                while(matcher.find())owned.add(matcher.group(1));
                try(var connection=source.getConnection()){
                    ScriptUtils.executeSqlScript(connection,new EncodedResource(new FileSystemResource(path),StandardCharsets.UTF_8),
                            false,false,ScriptUtils.DEFAULT_COMMENT_PREFIX,name.endsWith("-guards.sql")?"$$":";",
                            ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
                }
            }
            if(tables().size()!=29)throw new IllegalStateException("Compact detection fixture must contain the reviewed 29-table model");
        }catch(Exception failure){close();throw failure;}
    }
    private static final class ListParts {
        static final String[] NAMES={"10-core.sql","20-content.sql","25-agent.sql","30-operations.sql",
                "35-runtime-guards.sql","36-identity-guards.sql","37-audit-guards.sql","38-quota-guards.sql",
                "39-workflow-guards.sql","40-relations.sql"};
    }
    public DriverManagerDataSource source(){return source;}
    public void ownFixtureTable(String table){
        if(!Set.of("business_record","test_audit").contains(table))throw new IllegalArgumentException("Unregistered fixture helper table");
        owned.add(table);
    }
    private Set<String> tables(){return new HashSet<>(new JdbcTemplate(source).queryForList(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",String.class));}
    @Override public void close(){
        if(!admitted)return;
        var present=tables();
        if(!owned.containsAll(present))throw new SecurityException("Refusing cleanup of tables not installed by this compact fixture");
        try(var connection=source.getConnection();var statement=connection.createStatement()){
            statement.execute("SET FOREIGN_KEY_CHECKS=0");
            try{for(String table:present.stream().sorted().toList())statement.execute("DROP TABLE `"+table+"`");}
            finally{statement.execute("SET FOREIGN_KEY_CHECKS=1");}
            admitted=false;
        }catch(Exception failure){throw new IllegalStateException("Owned compact fixture cleanup failed",failure);}
    }
}
