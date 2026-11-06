package com.ruanzhu.doorhandle.module.app.testsupport;

import com.ruanzhu.doorhandle.module.app.EcsIsolatedMysql;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/** Opt-in legacy.chat.mysql.config: a pre-provisioned empty doorhandle_agent_verify_ ECS schema. */
public final class LegacyChatActionMySqlFixture implements AutoCloseable {
    private final DriverManagerDataSource source;
    private final Map<String,Object> identity;
    private final CompactMySqlFixture schema;

    public LegacyChatActionMySqlFixture() throws Exception {
        source=EcsIsolatedMysql.open(System.getProperty("legacy.chat.mysql.config"),"doorhandle_agent_verify_");
        source.setUrl(source.getUrl().replace("serverTimezone=Asia/Shanghai","connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true"));
        identity=identity();
        schema=new CompactMySqlFixture(source);
        try {
            if(jdbc().queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'",Long.class)!=29L)
                throw new IllegalStateException("Legacy chat verification requires the complete 29-table candidate");
        } catch(Exception failure){try{schema.close();}catch(Exception cleanup){failure.addSuppressed(cleanup);}throw failure;}
    }
    public DriverManagerDataSource dataSource(){return source;}
    public JdbcTemplate jdbc(){return new JdbcTemplate(source);}
    private Map<String,Object> identity(){return jdbc().queryForMap("SELECT DATABASE() db,@@server_uuid uuid,@@port port");}
    @Override public void close() {
        if(!identity.equals(identity()))throw new SecurityException("Legacy chat fixture identity changed; refusing cleanup");
        schema.close();
    }
}
