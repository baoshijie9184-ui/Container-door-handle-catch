package com.ruanzhu.doorhandle.module.app.testsupport;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.jdbc.core.JdbcTemplate;

/** Actual support source DDL and the complete target in two pre-provisioned ECS schemas. */
public final class SupportCopyMySqlFixture implements AutoCloseable {
    public static final List<String> SUPPORT=List.of("chat_project","chat_message","detection_image_fingerprint",
            "agent_research_storage_owner","agent_skill_download_owner");
    private static final Set<String> SOURCES=Set.of("users","chat_session","chat_project","chat_message",
            "detection_image_fingerprint","agent_research_storage_owner","agent_skill_download_owner");
    private final DualSchemaCopyMySqlFixture schemas;

    public SupportCopyMySqlFixture() throws Exception {
        var targetTables=new HashSet<String>();
        for(String file:List.of("10-core.sql","20-content.sql","25-agent.sql","30-operations.sql")) {
            var matcher=Pattern.compile("(?m)^CREATE TABLE ([a-z_]+) ").matcher(Files.readString(Path.of("../sql/mysql/compact/baseline",file)));
            while(matcher.find())targetTables.add(matcher.group(1));
        }
        schemas=new DualSchemaCopyMySqlFixture(System.getProperty("doorhandle.support.source.config"),
                System.getProperty("doorhandle.support.mysql.config"),"doorhandle_feature_",SOURCES,targetTables);
        try {
            String core=Files.readString(Path.of("../sql/mysql/schema.sql"));
            // Use the real referenced core declarations, including their foreign keys.
            for(String table:List.of("users","chat_session")) {
                var declaration=Pattern.compile("(?is)CREATE TABLE IF NOT EXISTS `?"+table+"`?\\s*\\(.*?\\)\\s*ENGINE[^;]*;").matcher(core);
                if(!declaration.find())throw new IllegalStateException("Actual support reference DDL missing: "+table);
                schemas.executeSource(declaration.group());
            }
            schemas.executeSource(Files.readString(Path.of("src/test/resources/compact-support-source.sql")));
            new CompactMySqlFixture(schemas.targetDataSource());
        }catch(Exception error){try{close();}catch(Exception cleanup){error.addSuppressed(cleanup);}throw error;}
    }
    public JdbcTemplate source(){return schemas.source();}
    public JdbcTemplate target(){return schemas.target();}

    /** Copy only the independently seeded core references; they are not support copy inputs. */
    public void copyReferences() {
        for(String table:List.of("users","chat_session")) {
            var columns=source().queryForList("SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=? ORDER BY ordinal_position",String.class,table);
            String names=String.join(",",columns.stream().map(column->"`"+column+"`").toList());
            target().update("INSERT INTO `"+table+"`("+names+") SELECT "+names+" FROM `"+schemas.sourceName()+"`.`"+table+"`");
        }
    }
    public void copyChatAndFingerprints() throws Exception {copy("12-chat-and-fingerprints.sql");}
    public void copyOwnerLocks() throws Exception {copy("50-owner-locks.sql");}

    private void copy(String name) throws Exception {
        String sql=Files.readString(Path.of("../sql/mysql/compact/copy",name)).replace("__SOURCE_SCHEMA__",schemas.sourceName());
        // A separate source connection owns READ locks across the copy's transaction and HWM DDL.
        // START TRANSACTION would release LOCK TABLES if the same connection owned both.
        try(Connection frozen=source().getDataSource().getConnection();var lock=frozen.createStatement()) {
            lock.execute("LOCK TABLES "+String.join(",",SOURCES.stream().sorted().map(table->"`"+table+"` READ").toList()));
            try {schemas.executeTarget(sql);}
            finally {lock.execute("UNLOCK TABLES");}
        }
    }
    @Override public void close() throws Exception {schemas.close();}
}
