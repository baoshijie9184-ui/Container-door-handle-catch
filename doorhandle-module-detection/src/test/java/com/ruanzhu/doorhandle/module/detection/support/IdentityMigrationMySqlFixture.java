package com.ruanzhu.doorhandle.module.detection.support;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Set;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ScriptUtils;

/** Eleven exact source declarations, complete 29-table target, distinct disposable ECS schemas. */
public final class IdentityMigrationMySqlFixture implements AutoCloseable {
    private final DualSchemaCopyMySqlFixture fixture;
    public static final Set<String> SOURCES=Set.of("detection_identity_control","detection_identity_source_control",
            "detection_identity_command","detection_identity_mapping_batch","detection_identity_mapping_item",
            "detection_identity_reconciliation_report","detection_assignment_identity_event",
            "detection_identity_binding_event","detection_identity_reconciliation_item",
            "detection_identity_missing_name_evidence","detection_identity_binding");
    public IdentityMigrationMySqlFixture() throws Exception {
        var targetTables=new HashSet<String>();
        new ObjectMapper().readTree(Path.of("../docs/database/compact-schema-contract.json").toFile())
                .path("expectedTargetTables").forEach(value->targetTables.add(value.asText()));
        if(targetTables.size()!=29)throw new IllegalStateException("Review the identity fixture after changing the compact target");
        fixture=new DualSchemaCopyMySqlFixture(System.getProperty("detection.identity.source.config"),
                System.getProperty("detection.identity.mysql.config"),"doorhandle_detection_verify_",SOURCES,targetTables);
        try {
            fixture.executeSource(new ClassPathResource("compact/identity-source-evidence.sql").getContentAsString(StandardCharsets.UTF_8));
            for(String name:new String[]{"10-core.sql","20-content.sql","25-agent.sql","30-operations.sql","35-runtime-guards.sql",
                    "36-identity-guards.sql","37-audit-guards.sql","38-quota-guards.sql","39-workflow-guards.sql","40-relations.sql"}){
                String sql=Files.readString(Path.of("../sql/mysql/compact/baseline",name));
                try(var connection=fixture.targetDataSource().getConnection()){
                    ScriptUtils.executeSqlScript(connection,new EncodedResource(new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8),
                            false,false,ScriptUtils.DEFAULT_COMMENT_PREFIX,name.endsWith("-guards.sql")?"$$":";",
                            ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
                }
            }
        }catch(Exception failure){try{close();}catch(Exception cleanup){failure.addSuppressed(cleanup);}throw failure;}
    }
    public JdbcTemplate source(){return fixture.source();}
    public JdbcTemplate target(){return fixture.target();}
    public void copy() throws Exception {
        String sql="SET @compact_identity_source_frozen=1;SET @compact_identity_target_frozen=1;\n"
                +Files.readString(Path.of("../sql/mysql/compact/copy/46-detection-identity.sql"))
                .replace("__SOURCE_SCHEMA__",fixture.sourceName()).replace("__SOURCE_IDENTITY_OFFSET__","+08:00");
        for(String table:SOURCES){
            String collation=source().queryForObject("SELECT table_collation FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=?",String.class,table);
            if(!Set.of("utf8mb4_bin","utf8mb4_0900_ai_ci","utf8mb4_unicode_ci").contains(collation))throw new SecurityException("Unreviewed identity source collation");
            sql=sql.replace("__SOURCE_IDENTITY_COLLATION_"+table+"__",collation);
        }
        fixture.executeTarget(sql);
    }
    @Override public void close() throws Exception {fixture.close();}
}
