package com.ruanzhu.doorhandle.module.ai.testsupport;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;

/** Reads the real content baseline; H2 adaptations do not prove MySQL DDL compatibility. */
public final class CompactContentFixture {
    private static final ObjectMapper JSON=new ObjectMapper();
    private CompactContentFixture() { }

    public static void install(JdbcTemplate jdbc) throws Exception {
        Path source=sourceRoot().resolve("sql/mysql/compact/baseline/20-content.sql");
        String ddl=Files.readString(source);
        String relations=Files.readString(source.resolveSibling("40-relations.sql"));
        var contentRelations=new StringBuilder();
        for(String statement:relations.replaceAll("(?m)^--.*$","").split(";"))
            if(statement.stripLeading().startsWith("ALTER TABLE content_"))contentRelations.append(statement).append(';');
        ddl+=contentRelations;
        try(var connection=jdbc.getDataSource().getConnection()) {
            if("H2".equals(connection.getMetaData().getDatabaseProductName())) {
                CompactH2Functions.install(jdbc);
                ddl=CompactH2Functions.adaptJsonColumns(ddl).replaceAll(" COLLATE utf8mb4_[a-z0-9_]+","").replace(" VIRTUAL","")
                    .replaceAll(" ENGINE=InnoDB(?: ROW_FORMAT=DYNAMIC)? DEFAULT CHARSET=utf8mb4(?: COLLATE=utf8mb4_[a-z0-9_]+)?","")
                    .replaceAll("(?m)^(\\s*)UNIQUE KEY (\\w+)\\s*(\\([^\\n]+\\))","$1CONSTRAINT $2 UNIQUE $3")
                    .replaceAll("(?m)^\\s*KEY [^\\n]+\\n","").replaceAll(",\\s*\\)",")");
            }
        }
        var script=new ResourceDatabasePopulator(new ByteArrayResource(ddl.getBytes(StandardCharsets.UTF_8)));
        script.setSqlScriptEncoding("UTF-8");script.execute(jdbc.getDataSource());
    }

    private static Path sourceRoot() {
        for(Path path=Path.of("").toAbsolutePath();path!=null;path=path.getParent())
            if(Files.isRegularFile(path.resolve("sql/mysql/compact/baseline/20-content.sql")))return path;
        throw new IllegalStateException("The isolated ECS checkout must contain the compact baseline sources");
    }
    public static boolean jsonValid(String value) {
        try{return value!=null&&JSON.readTree(value)!=null;}catch(Exception invalid){return false;}
    }
    public static LocalDateTime utcTimestamp(){return LocalDateTime.now(ZoneOffset.UTC);}
    public static LocalDateTime utcTimestamp(int precision){return utcTimestamp();}
}
