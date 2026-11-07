package com.ruanzhu.doorhandle.module.model.testsupport;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Connection;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/** Test-only complete source-data digest; not a production backup or migration receipt. */
public final class FixtureSourceSnapshot {
    private static final String TOKEN="__SOURCE_SNAPSHOT_SHA256__";
    private FixtureSourceSnapshot() { }
    public static String bind(String sql,JdbcTemplate source,Set<String> ownedTables){
        return sql.contains(TOKEN)?sql.replace(TOKEN,capture(source,ownedTables)):sql;
    }
    public static String capture(JdbcTemplate source,Set<String> ownedTables){
        return source.execute((ConnectionCallback<String>) connection->{
            if(!"MySQL".equals(connection.getMetaData().getDatabaseProductName())||!connection.getAutoCommit())
                throw new IllegalStateException("Fixture digest requires its own admitted MySQL read transaction");
            int isolation=connection.getTransactionIsolation();boolean readOnly=connection.isReadOnly();
            String timezone;
            try(var statement=connection.createStatement();var row=statement.executeQuery("SELECT @@SESSION.time_zone")){row.next();timezone=row.getString(1);}
            try{
                connection.setReadOnly(true);connection.setTransactionIsolation(Connection.TRANSACTION_REPEATABLE_READ);connection.setAutoCommit(false);
                var jdbc=new JdbcTemplate(new SingleConnectionDataSource(connection,true));
                jdbc.execute("SET SESSION time_zone='+00:00'");
                var tables=jdbc.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY table_name",String.class);
                if(!ownedTables.containsAll(tables))throw new IllegalStateException("Unowned source object cannot enter a fixture snapshot");
                MessageDigest digest;
                try{digest=MessageDigest.getInstance("SHA-256");}catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}
                piece(digest,"DOORHANDLE_ECS_FIXTURE_DATA_SNAPSHOT_V1");piece(digest,Integer.toString(tables.size()));
                for(String table:tables){
                    identifier(table);piece(digest,table);
                    var ddl=jdbc.queryForMap("SHOW CREATE TABLE `"+table+"`").values().stream()
                            .filter(value->value instanceof String text&&text.startsWith("CREATE ")).map(Object::toString).findFirst().orElseThrow();
                    piece(digest,ddl);
                    var columns=jdbc.queryForList("SELECT column_name,data_type FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=? ORDER BY ordinal_position",table);
                    var expressions=new java.util.ArrayList<String>();
                    for(var column:columns){
                        String name=(String)column.get("column_name"),type=(String)column.get("data_type");identifier(name);
                        String value="`"+name+"`";
                        if(Set.of("datetime","timestamp","date","time","json").contains(type))value="CAST("+value+" AS CHAR CHARACTER SET utf8mb4)";
                        else if(type.contains("binary")||type.contains("blob")||"bit".equals(type))value="HEX("+value+")";
                        expressions.add("'"+name+"',"+value);
                    }
                    long count=jdbc.queryForObject("SELECT COUNT(*) FROM `"+table+"`",Long.class);
                    if(count>100_000)throw new IllegalStateException("Fixture source row budget exceeded");
                    List<String> rows=jdbc.queryForList("SELECT CAST(JSON_OBJECT("+String.join(",",expressions)+") AS CHAR CHARACTER SET utf8mb4) FROM `"+table+"`",String.class);
                    if(rows.size()!=count)throw new IllegalStateException("Fixture source snapshot changed");
                    piece(digest,Long.toString(count));rows.stream().sorted().forEach(row->piece(digest,row));
                }
                return HexFormat.of().formatHex(digest.digest());
            }finally{
                connection.rollback();connection.setAutoCommit(true);
                try(var statement=connection.prepareStatement("SET SESSION time_zone=?")){statement.setString(1,timezone);statement.execute();}
                connection.setTransactionIsolation(isolation);connection.setReadOnly(readOnly);
            }
        });
    }
    /** Install the real immutable-evidence guards for tables present in this admitted fixture. */
    public static void installLegacyClockGuards(JdbcTemplate target,java.nio.file.Path baseline)throws Exception{
        var tables=Set.copyOf(target.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",String.class));
        var installed=new java.util.HashSet<>(target.queryForList("SELECT trigger_name FROM information_schema.triggers WHERE trigger_schema=DATABASE()",String.class));
        try(var files=java.nio.file.Files.list(baseline)){
            for(var path:files.filter(file->file.getFileName().toString().startsWith("35-legacy-clock-")&&file.getFileName().toString().endsWith(".sql")).sorted().toList()){
                String sql=java.nio.file.Files.readString(path);
                var table=java.util.regex.Pattern.compile("(?m)^BEFORE (?:UPDATE|DELETE) ON ([a-z_]+) ").matcher(sql);
                if(!table.find())throw new IllegalStateException("Unreviewed legacy clock fixture guard");
                var required=new java.util.HashSet<String>();required.add(table.group(1));
                var references=java.util.regex.Pattern.compile("\\b(?:FROM|JOIN) ([a-z_]+)").matcher(sql);while(references.find())required.add(references.group(1));
                if(!tables.containsAll(required))continue;
                var matcher=java.util.regex.Pattern.compile("(?m)^CREATE TRIGGER ([a-z_]+)").matcher(sql);var names=new java.util.HashSet<String>();
                while(matcher.find())names.add(matcher.group(1));
                if(names.isEmpty())throw new IllegalStateException("Legacy clock fixture guard has no triggers");
                if(installed.containsAll(names))continue;
                if(names.stream().anyMatch(installed::contains))throw new IllegalStateException("Partially installed legacy clock fixture guard");
                try(var connection=target.getDataSource().getConnection()){
                    org.springframework.jdbc.datasource.init.ScriptUtils.executeSqlScript(connection,
                        new org.springframework.core.io.support.EncodedResource(new org.springframework.core.io.ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8),
                        false,false,org.springframework.jdbc.datasource.init.ScriptUtils.DEFAULT_COMMENT_PREFIX,"$$",
                        org.springframework.jdbc.datasource.init.ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,org.springframework.jdbc.datasource.init.ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
                }
                installed.addAll(names);
            }
        }
    }
    private static void identifier(String value){if(value==null||!value.matches("[A-Za-z_][A-Za-z0-9_]{0,63}"))throw new IllegalArgumentException("Unsafe fixture source identifier");}
    private static void piece(MessageDigest digest,String value){byte[] bytes=value.getBytes(StandardCharsets.UTF_8);digest.update(ByteBuffer.allocate(8).putLong(bytes.length).array());digest.update(bytes);}
}
