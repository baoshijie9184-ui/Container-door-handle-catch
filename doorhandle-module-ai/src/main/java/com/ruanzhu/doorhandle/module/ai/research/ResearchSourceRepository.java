package com.ruanzhu.doorhandle.module.ai.research;

import com.ruanzhu.doorhandle.framework.persistence.content.ContentKind;
import com.ruanzhu.doorhandle.framework.persistence.content.JdbcContentStore;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/** Research provenance on the shared content protocol; no legacy SQL fallback. */
public final class ResearchSourceRepository {
    private final JdbcTemplate jdbc;
    private final JdbcContentStore content;
    private static final String FROM = """
        FROM content_link l
        JOIN content_asset a ON a.asset_id=l.asset_id AND a.owner_user_id=l.owner_user_id
          AND a.asset_kind='RESEARCH_SOURCE'
        JOIN content_revision r ON r.asset_id=l.asset_id AND r.version=l.asset_version
          AND r.owner_user_id=l.owner_user_id AND r.asset_kind='RESEARCH_SOURCE'
        WHERE l.link_kind='RESEARCH_SOURCE' AND l.state='ACTIVE'
        """;
    private static final String SOURCE_COLUMNS = """
        SELECT a.asset_id AS source_id,l.owner_user_id AS user_id,l.run_id,l.call_id,
          r.source_url AS requested_url,r.source_query_omitted AS query_omitted,
          r.source_url_redacted AS url_redacted,r.title,r.content_text AS excerpt,
          r.source_sha256 AS content_sha256,l.request_sha256,r.text_chars,
          r.range_start AS start_index,r.max_length,r.created_at AS fetched_at,r.expires_at
        """;
    private static final RowMapper<ResearchEvidenceDtos.Source> SOURCE = (rs,n) ->
        new ResearchEvidenceDtos.Source(rs.getString("source_id"),rs.getString("run_id"),rs.getString("call_id"),
            rs.getString("requested_url"),rs.getBoolean("query_omitted"),rs.getBoolean("url_redacted"),
            rs.getString("title"),rs.getString("excerpt"),rs.getString("content_sha256"),rs.getInt("text_chars"),
            rs.getInt("start_index"),rs.getInt("max_length"),rs.getObject("fetched_at",LocalDateTime.class),
            rs.getObject("expires_at",LocalDateTime.class));

    public ResearchSourceRepository(JdbcTemplate jdbc) {
        this.jdbc=jdbc;
        this.content=new JdbcContentStore(jdbc);
    }

    public void validateSchema() {
        jdbc.queryForList(SOURCE_COLUMNS+FROM+" AND 1=0");
        jdbc.queryForList("SELECT source_sha256,stored_content_sha256,purge_owner_user_id,cleared_chars,purged_at FROM content_revision WHERE 1=0");
    }

    public record Captured(String id,long owner,String runId,String callId,String url,boolean queryOmitted,
                           boolean urlRedacted,String title,String excerpt,String fullSourceHash,String requestHash,
                           int textChars,int start,int max,LocalDateTime fetchedAt,LocalDateTime expiresAt) { }

    public void append(Captured value) {
        content.prepare(new JdbcContentStore.AssetDraft(value.id(),ContentKind.RESEARCH_SOURCE,value.owner(),
            value.title(),null,"PRIVATE",null,null,value.fetchedAt()));
        // The fetched body's digest is deliberately distinct from the scrubbed excerpt's digest.
        jdbc.update("""
            INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,creator_user_id,title,
              content_text,content_sha256,stored_content_sha256,source_sha256,byte_length,media_type,
              source_run_id,source_url,source_query_omitted,source_url_redacted,range_start,max_length,text_chars,
              request_sha256,expires_at,created_at)
            VALUES(?,'RESEARCH_SOURCE',1,?,?,?,?,?,?,?,?,'text/plain; charset=utf-8',?,?,?,?,?,?,?,?,?,?)
            """,value.id(),value.owner(),value.owner(),value.title(),value.excerpt(),value.fullSourceHash(),
            ResearchEvidenceService.sha256(value.excerpt()),value.fullSourceHash(),
            value.excerpt().getBytes(StandardCharsets.UTF_8).length,value.runId(),value.url(),value.queryOmitted(),
            value.urlRedacted(),value.start(),value.max(),value.textChars(),value.requestHash(),value.expiresAt(),value.fetchedAt());
        jdbc.update("""
            INSERT INTO content_link(link_kind,owner_user_id,run_id,call_id,asset_id,asset_version,
              request_sha256,state,created_at) VALUES('RESEARCH_SOURCE',?,?,?,?,1,?,'ACTIVE',?)
            """,value.owner(),value.runId(),value.callId(),value.id(),value.requestHash(),value.fetchedAt());
        int changed=jdbc.update("UPDATE content_asset SET current_version=1,lifecycle='ACTIVE' WHERE asset_id=? AND asset_kind='RESEARCH_SOURCE' AND owner_user_id=? AND current_version IS NULL",
            value.id(),value.owner());
        if(changed!=1) throw new IllegalStateException("Research content identity changed before publication");
    }

    public List<Map<String,Object>> findCall(long owner,String run,String call) {
        return jdbc.queryForList("SELECT a.asset_id AS source_id,l.request_sha256,r.source_sha256 AS content_sha256 "+FROM+
            " AND l.owner_user_id=? AND l.run_id=? AND l.call_id=?",owner,run,call);
    }

    public long countRun(long owner,String run) {
        return jdbc.queryForObject("SELECT COUNT(*) "+FROM+" AND l.owner_user_id=? AND l.run_id=?",Long.class,owner,run);
    }

    public long countActive(long owner) {
        return jdbc.queryForObject("SELECT COUNT(*) "+FROM+" AND l.owner_user_id=? AND r.expires_at>UTC_TIMESTAMP(6)",Long.class,owner);
    }

    public List<String> activeIds(long owner,String run) {
        return jdbc.queryForList("SELECT a.asset_id "+FROM+" AND l.owner_user_id=? AND l.run_id=? AND r.expires_at>UTC_TIMESTAMP(6)",
            String.class,owner,run);
    }

    public List<String> activeHashes(long owner,String sourceId) {
        return jdbc.queryForList("SELECT r.source_sha256 "+FROM+
            " AND l.owner_user_id=? AND a.asset_id=? AND r.expires_at>UTC_TIMESTAMP(6)",String.class,owner,sourceId);
    }

    public List<ResearchEvidenceDtos.Source> active(long owner,String run) {
        return jdbc.query(SOURCE_COLUMNS+FROM+" AND l.owner_user_id=? AND l.run_id=? AND r.expires_at>UTC_TIMESTAMP(6) ORDER BY r.id LIMIT 20",SOURCE,owner,run);
    }

    public int expiredCount(long owner,String run) {
        return jdbc.queryForObject("SELECT COUNT(*) "+FROM+" AND l.owner_user_id=? AND l.run_id=? AND r.expires_at<=UTC_TIMESTAMP(6)",Integer.class,owner,run);
    }

    public List<Map<String,Object>> purgeCandidates(int maximum) {
        return jdbc.query("SELECT a.asset_id AS source_id,l.owner_user_id AS user_id "+FROM+
            " AND r.expires_at<=UTC_TIMESTAMP(6) AND r.purged_at IS NULL ORDER BY r.expires_at,r.id LIMIT ?",
            statement->{statement.setInt(1,maximum);statement.setQueryTimeout(5);},new org.springframework.jdbc.core.ColumnMapRowMapper());
    }

    /** Caller holds the research owner lock; byte removal and the receipt are atomic. */
    public int purge(long owner,String sourceId) {
        if(!TransactionSynchronizationManager.isActualTransactionActive()||jdbc.getDataSource()==null
                ||!TransactionSynchronizationManager.hasResource(jdbc.getDataSource())
                ||!Boolean.FALSE.equals(jdbc.execute((ConnectionCallback<Boolean>) c->c.getAutoCommit())))
            throw new IllegalStateException("Research purge requires its JDBC transaction");
        var rows=jdbc.queryForList("SELECT r.source_url,r.title,r.content_text "+FROM+
            " AND l.owner_user_id=? AND a.asset_id=? AND r.expires_at<=UTC_TIMESTAMP(6) AND r.purged_at IS NULL FOR UPDATE",owner,sourceId);
        if(rows.isEmpty()) return 0;
        if(rows.size()!=1) throw new IllegalStateException("Research provenance is not unique");
        var row=rows.get(0);
        int chars=row.get("source_url").toString().length()+row.get("title").toString().length()+row.get("content_text").toString().length();
        int changed=jdbc.update("""
            UPDATE content_revision SET source_url='',title='',content_text='',content_state='PURGED',
              purge_owner_user_id=?,cleared_chars=?,purged_at=UTC_TIMESTAMP(6)
            WHERE asset_kind='RESEARCH_SOURCE' AND asset_id=? AND version=1 AND owner_user_id=?
              AND expires_at<=UTC_TIMESTAMP(6) AND purged_at IS NULL
            """,owner,chars,sourceId,owner);
        if(changed!=1) throw new IllegalStateException("Research content purge did not record exactly one receipt");
        if(jdbc.update("UPDATE content_asset SET title='',updated_at=UTC_TIMESTAMP(6),revision=revision+1 WHERE asset_id=? AND asset_kind='RESEARCH_SOURCE' AND owner_user_id=?",sourceId,owner)!=1)
            throw new IllegalStateException("Research content identity did not match its purge");
        return 1;
    }
}
