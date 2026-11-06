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

/** Seven original tables to the complete compact model, in two controller-owned ECS schemas. */
public final class DetectionRuntimeCopyMySqlFixture implements AutoCloseable {
    private final DualSchemaCopyMySqlFixture fixture;
    public DetectionRuntimeCopyMySqlFixture() throws Exception {
        var targetTables=new HashSet<String>();
        new ObjectMapper().readTree(Path.of("../docs/database/compact-schema-contract.json").toFile())
                .path("expectedTargetTables").forEach(value->targetTables.add(value.asText()));
        if(targetTables.size()!=29)throw new IllegalStateException("Review detection fixture after changing the compact model");
        fixture=new DualSchemaCopyMySqlFixture(System.getProperty("doorhandle.detection.runtime.copy.source.config"),
                System.getProperty("doorhandle.detection.runtime.copy.target.config"),"doorhandle_detection_verify_",
                Set.of("detection_creation_owner","detection_creation_job","detection_creation_object","detection_creation_review",
                        "detection_execution_command","detection_dispatch_outbox","detection_worker_receipt"),targetTables);
        try {
            fixture.executeSource(new ClassPathResource("db/compact/detection-runtime-source.sql").getContentAsString(StandardCharsets.UTF_8));
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
        String object=collation("detection_creation_object"),review=collation("detection_creation_review");
        String sql="SET @compact_source_quiesced=1;\n"+Files.readString(Path.of("../sql/mysql/compact/copy/47-detection-runtime.sql"))
                .replace("__SOURCE_SCHEMA__",fixture.sourceName()).replace("__SOURCE_DETECTION_OFFSET__","+08:00")
                .replace("__SOURCE_DETECTION_OBJECT_COLLATION__",object).replace("__SOURCE_DETECTION_REVIEW_COLLATION__",review);
        fixture.executeTarget(sql);
    }
    private String collation(String table){
        String value=source().queryForObject("SELECT table_collation FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=?",String.class,table);
        if(!Set.of("utf8mb4_bin","utf8mb4_0900_ai_ci","utf8mb4_unicode_ci").contains(value))
            throw new IllegalStateException("Unreviewed source fixture collation");
        return value;
    }
    @Override public void close() throws Exception {fixture.close();}
}
