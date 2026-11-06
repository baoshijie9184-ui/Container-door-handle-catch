package com.ruanzhu.doorhandle.module.ai.testsupport;

import com.ruanzhu.doorhandle.module.ai.EcsIsolatedMysql;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.util.HashSet;
import java.util.Set;
import javax.sql.DataSource;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ScriptUtils;

/** Original V64 source and actual compact quota DDL, in two existing, distinct, verified ECS schemas. */
public final class ModelBudgetMigrationFixture implements AutoCloseable {
    private static final Set<String> SOURCE_TABLES=Set.of("agent_model_budget","agent_model_budget_attempt",
            "agent_model_budget_observation","agent_model_budget_audit");
    private final DataSource source,target;
    private final String sourceName;
    private CompactQuotaFixture compact;
    private boolean ownsSource;

    public ModelBudgetMigrationFixture() throws Exception {
        target=FeatureMySql.source();
        source=EcsIsolatedMysql.open(System.getProperty("doorhandle.model-budget.source.config"),"doorhandle_feature_");
        var left=new JdbcTemplate(source).queryForMap("SELECT DATABASE() db,@@server_uuid uuid,@@port port,@@datadir datadir");
        var right=new JdbcTemplate(target).queryForMap("SELECT DATABASE() db,@@server_uuid uuid,@@port port,@@datadir datadir");
        sourceName=String.valueOf(left.get("db"));
        if(sourceName.equals(right.get("db")) || !left.get("uuid").equals(right.get("uuid"))
                || !left.get("port").equals(right.get("port")) || !left.get("datadir").equals(right.get("datadir")))
            throw new SecurityException("Budget migration requires distinct schemas on the same admitted ECS MySQL instance");
        if(!tables(source).isEmpty() || !tables(target).isEmpty())throw new SecurityException("Budget migration requires two empty schemas");
        var grants=new JdbcTemplate(target).queryForList("SELECT privilege_type FROM information_schema.schema_privileges WHERE table_schema=? "
                + "AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))",String.class,sourceName);
        if(!grants.containsAll(Set.of("SELECT","TRIGGER")))throw new SecurityException("Existing source SELECT/TRIGGER metadata grants are required");
        ownsSource=true;
        try {
            try(Connection connection=source.getConnection()) {
                execute(connection,Files.readString(Path.of("../sql/mysql/migration-V64-model-budget.sql")),";");
            }
            compact=new CompactQuotaFixture(target);
        } catch(Exception error) {
            try {close();}catch(Exception cleanup){error.addSuppressed(cleanup);}throw error;
        }
    }
    public JdbcTemplate source(){return new JdbcTemplate(source);}
    public JdbcTemplate target(){return new JdbcTemplate(target);}
    public DataSource targetDataSource(){return target;}
    public String sourceName(){return sourceName;}
    public void migrate() throws Exception {
        String sql=Files.readString(Path.of("../sql/mysql/compact/copy/38-model-budget.sql")).replace("__SOURCE_SCHEMA__",sourceName);
        try(Connection connection=target.getConnection()) {
            connection.setAutoCommit(false);
            try {execute(connection,sql,";");}
            catch(Exception error) {try {connection.rollback();}catch(Exception rollback){error.addSuppressed(rollback);}throw error;}
        }
    }
    public void targetSql(String sql,String separator) throws Exception {
        try(Connection connection=target.getConnection()){execute(connection,sql,separator);}
    }
    private static void execute(Connection connection,String sql,String separator) {
        ScriptUtils.executeSqlScript(connection,new EncodedResource(new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8),false,false,
                ScriptUtils.DEFAULT_COMMENT_PREFIX,separator,ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
    }
    private static Set<String> tables(DataSource data) {
        return new HashSet<>(new JdbcTemplate(data).queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",String.class));
    }
    @Override public void close() throws Exception {
        if(!ownsSource)return;
        Set<String> present=tables(source);
        if(!SOURCE_TABLES.containsAll(present))throw new SecurityException("Unowned source object; refusing budget fixture cleanup");
        // CompactQuotaFixture verifies its own table ownership. DROP TABLE does not bypass a business DELETE to clear history.
        if(compact!=null)compact.close();
        try(Connection connection=source.getConnection();var statement=connection.createStatement()) {
            for(String table:present.stream().sorted().toList())statement.execute("DROP TABLE `"+table+"`");
        }
        ownsSource=false;
    }
}
