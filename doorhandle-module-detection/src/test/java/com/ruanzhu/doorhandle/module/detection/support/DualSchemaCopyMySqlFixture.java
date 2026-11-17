package com.ruanzhu.doorhandle.module.detection.support;

import com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql;
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
    private Map<String,Object> sourceResetShape,targetResetShape;
    private boolean resetHealthy;
    private static final Set<String> REPORT_SOURCE_TABLES=Set.of("detection_quality_report","detection_report_audit",
            "detection_report_command","detection_report_confirmation","detection_report_agent_origin",
            "detection_report_outbox","detection_report_event_receipt","detection_report_event_state");
    private static final Set<String> REPORT_TARGET_TABLES=Set.of("quality_report","workflow_instance","audit_event","runtime_state");

    public DualSchemaCopyMySqlFixture(String sourceConfig,String targetConfig,String prefix,Set<String> sourceTables,Set<String> targetTables) throws Exception {
        source=EcsIsolatedMysql.open(sourceConfig,prefix);target=EcsIsolatedMysql.open(targetConfig,prefix);
        // Shared workflow/audit timestamps are UTC; the historical report source retains its original wall clock.
        target.setUrl(target.getUrl().replace("serverTimezone=Asia/Shanghai","connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true"));
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

    /** Only the report data-only class opts in; other copy fixtures keep per-case DDL. */
    void enableReportDataReset() throws Exception {
        if(!ownsSchemas||sourceResetShape!=null||!sourceTables.equals(REPORT_SOURCE_TABLES)||targetTables.size()!=29)
            throw new IllegalStateException("Report data reset requires its newly installed complete fixture");
        sourceResetShape=resetShape(source,sourceTables,Set.of());
        targetResetShape=resetShape(target,targetTables,Set.of());
        requireEmptyExcept(source,sourceTables,Set.of());requireEmptyExcept(target,targetTables,Set.of());
        resetHealthy=true;
    }

    void resetReportData() throws Exception {
        if(!ownsSchemas||sourceResetShape==null||!resetHealthy)throw new IllegalStateException("Report data reset was not enabled or a previous reset failed");
        resetHealthy=false; // A partial reset must never be reused or silently rebuilt.
        if(!sourceResetShape.equals(resetShape(source,sourceTables,REPORT_SOURCE_TABLES))
                ||!targetResetShape.equals(resetShape(target,targetTables,REPORT_TARGET_TABLES)))
            throw new SecurityException("Report fixture structure or identity changed before data reset");
        requireEmptyExcept(target,targetTables,REPORT_TARGET_TABLES);
        truncate(target,REPORT_TARGET_TABLES);truncate(source,REPORT_SOURCE_TABLES);
        requireEmptyExcept(source,sourceTables,Set.of());requireEmptyExcept(target,targetTables,Set.of());
        if(!sourceResetShape.equals(resetShape(source,sourceTables,Set.of()))
                ||!targetResetShape.equals(resetShape(target,targetTables,Set.of())))
            throw new SecurityException("Report fixture reset did not restore its original structure and counters");
        resetHealthy=true;
    }

    private static Map<String,Object> resetShape(DriverManagerDataSource data,Set<String> expected,Set<String> mutableCounters)throws Exception {
        try(Connection connection=data.getConnection()) {
            var jdbc=new JdbcTemplate(new org.springframework.jdbc.datasource.SingleConnectionDataSource(connection,true));
            var actual=new HashSet<>(jdbc.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'",String.class));
            if(!actual.equals(expected)||jdbc.queryForObject("SELECT (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type<>'BASE TABLE')+(SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema=DATABASE())+(SELECT COUNT(*) FROM information_schema.events WHERE event_schema=DATABASE())",Long.class)!=0)
                throw new SecurityException("Unowned or missing fixture object before data reset");
            var result=new java.util.LinkedHashMap<String,Object>();
            result.put("identity",jdbc.queryForMap("SELECT DATABASE() db,CURRENT_USER() account,@@server_uuid uuid,@@port port"));
            for(String table:expected.stream().sorted().toList()) {
                String ddl=(String)jdbc.queryForMap("SHOW CREATE TABLE `"+table+"`").get("Create Table");
                if(mutableCounters.contains(table))ddl=ddl.replaceFirst("(?m)^(\\) ENGINE=\\S+) AUTO_INCREMENT=[0-9]+", "$1");
                result.put(table,ddl);
            }
            result.put("triggers",jdbc.queryForList("SELECT trigger_name,event_manipulation,event_object_table,action_order,action_statement,action_orientation,action_timing,sql_mode,definer,character_set_client,collation_connection,database_collation FROM information_schema.triggers WHERE trigger_schema=DATABASE() ORDER BY trigger_name"));
            return result;
        }
    }
    private static void requireEmptyExcept(DriverManagerDataSource data,Set<String> all,Set<String> allowed)throws Exception {
        try(Connection connection=data.getConnection()) {
            var jdbc=new JdbcTemplate(new org.springframework.jdbc.datasource.SingleConnectionDataSource(connection,true));
            for(String table:all.stream().filter(name->!allowed.contains(name)).sorted().toList())
                if(Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM `"+table+"` LIMIT 1)",Boolean.class)))
                    throw new SecurityException("Unexpected fixture rows in "+table);
        }
    }
    private static void truncate(DriverManagerDataSource data,Set<String> tables)throws Exception {
        try(Connection connection=data.getConnection();var statement=connection.createStatement()) {
            statement.execute("SET FOREIGN_KEY_CHECKS=0");
            try {for(String table:tables.stream().sorted().toList())statement.execute("TRUNCATE TABLE `"+table+"`");}
            finally {statement.execute("SET FOREIGN_KEY_CHECKS=1");}
        }
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
