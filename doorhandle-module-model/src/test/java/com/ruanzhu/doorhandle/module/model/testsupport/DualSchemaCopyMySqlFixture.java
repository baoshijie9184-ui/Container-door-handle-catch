package com.ruanzhu.doorhandle.module.model.testsupport;

import com.ruanzhu.doorhandle.module.model.EcsIsolatedMysql;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ScriptUtils;

/** Two pre-provisioned EMPTY ECS schemas; no CREATE DATABASE/GRANT and no business-schema fallback. */
public final class DualSchemaCopyMySqlFixture implements AutoCloseable {
    private final DriverManagerDataSource source,target;
    private final Set<String> sourceTables,targetTables;
    private final Map<String,Object> sourceIdentity,targetIdentity;
    private boolean ownsSchemas;

    public DualSchemaCopyMySqlFixture(String sourceConfig,String targetConfig,String prefix,Set<String> sourceTables,Set<String> targetTables) throws Exception {
        source=EcsIsolatedMysql.open(sourceConfig,prefix);target=EcsIsolatedMysql.open(targetConfig,prefix);
        this.sourceTables=Set.copyOf(sourceTables);this.targetTables=Set.copyOf(targetTables);
        sourceIdentity=identity(source);targetIdentity=identity(target);
        if(sourceIdentity.get("db").equals(targetIdentity.get("db"))
                || !sourceIdentity.get("uuid").equals(targetIdentity.get("uuid")) || !sourceIdentity.get("port").equals(targetIdentity.get("port")))
            throw new SecurityException("Copy requires distinct source/target schemas on the same admitted ECS server");
        if(!tables(source).isEmpty() || !tables(target).isEmpty())throw new SecurityException("Both copy schemas must be empty before fixture setup");
        var privileges=new HashSet<>(target().queryForList("SELECT privilege_type FROM information_schema.schema_privileges "
                +"WHERE table_schema=? AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))",String.class,sourceName()));
        if(!privileges.containsAll(Set.of("SELECT","TRIGGER")))throw new SecurityException("Target account needs pre-existing source SELECT and TRIGGER metadata privileges");
        ownsSchemas=true;
    }
    public JdbcTemplate source(){return new JdbcTemplate(source);}
    public JdbcTemplate target(){return new JdbcTemplate(target);}
    public DriverManagerDataSource targetDataSource(){return target;}
    public String sourceName(){return String.valueOf(sourceIdentity.get("db"));}
    public String targetName(){return String.valueOf(targetIdentity.get("db"));}
    public void executeSource(String sql) throws Exception {execute(source,sql);}
    public void executeTarget(String sql) throws Exception {execute(target,FixtureSourceSnapshot.bind(sql,source(),sourceTables));}
    public String sourceSnapshotSha256(){return FixtureSourceSnapshot.capture(source(),sourceTables);}

    /** ScriptUtils stops at the first error; all migrated rows roll back on this exact connection. */
    private static void execute(DriverManagerDataSource data,String sql) throws Exception {
        try(Connection connection=data.getConnection()) {
            connection.setAutoCommit(false);
            try {
                ScriptUtils.executeSqlScript(connection,new EncodedResource(new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8));
                connection.commit();
            } catch(Exception error) {
                try {connection.rollback();} catch(Exception rollback) {error.addSuppressed(rollback);}
                throw error;
            }
        }
    }
    private static Map<String,Object> identity(DriverManagerDataSource data) {
        return new JdbcTemplate(data).queryForMap("SELECT DATABASE() db,@@server_uuid uuid,@@port port");
    }
    private static Set<String> tables(DriverManagerDataSource data) {
        return new HashSet<>(new JdbcTemplate(data).queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",String.class));
    }
    @Override public void close() throws Exception {
        if(!ownsSchemas)return;
        // Verify both schemas and ownership before touching either schema during disposable cleanup.
        if(!sourceIdentity.equals(identity(source)) || !targetIdentity.equals(identity(target)))throw new SecurityException("Fixture server/schema identity changed; refusing cleanup");
        var left=tables(source);var right=tables(target);
        if(!sourceTables.containsAll(left) || !targetTables.containsAll(right))throw new SecurityException("Unowned fixture object found; refusing cleanup");
        clean(target,right);clean(source,left);ownsSchemas=false;
    }
    private static void clean(DriverManagerDataSource data,Set<String> owned) throws Exception {
        try(Connection connection=data.getConnection();var statement=connection.createStatement()) {
            statement.execute("SET FOREIGN_KEY_CHECKS=0");
            try {for(String table:owned.stream().sorted().toList())statement.execute("DROP TABLE `"+table+"`");}
            finally {statement.execute("SET FOREIGN_KEY_CHECKS=1");}
        }
    }
}
