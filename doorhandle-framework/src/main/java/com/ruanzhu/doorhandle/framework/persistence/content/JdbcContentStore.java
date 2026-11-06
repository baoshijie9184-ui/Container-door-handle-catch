package com.ruanzhu.doorhandle.framework.persistence.content;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/**
 * Storage protocol shared by content owners. Authorization remains in the domain service.
 * Create the identity without a version pointer, insert immutable revisions, then advance
 * the pointer within the same database transaction. No JSON-shaped generic row writer exists.
 */
public final class JdbcContentStore {
    private final JdbcTemplate jdbc;

    public JdbcContentStore(JdbcTemplate jdbc) { this.jdbc=Objects.requireNonNull(jdbc); }

    public record AssetDraft(String assetId, ContentKind kind, Long ownerUserId, String title,
                             String filename, String visibility, String requiredRole,
                             String identityKey, LocalDateTime createdAt) { }

    public record KnowledgeRevision(String assetId, int version, long ownerUserId, long creatorUserId,
                                    String title, String filename, String content, String contentSha256,
                                    byte[] sourceBytes, String sourceSha256, String mediaType,
                                    List<String> chunks, LocalDateTime createdAt) {
        public KnowledgeRevision {
            sourceBytes=Objects.requireNonNull(sourceBytes).clone();
            chunks=List.copyOf(chunks);
        }
        @Override public byte[] sourceBytes() { return sourceBytes.clone(); }
    }

    public void prepare(AssetDraft draft) {
        transaction();
        Objects.requireNonNull(draft.kind());
        if(draft.assetId()==null||draft.assetId().isBlank()||draft.assetId().length()>128)
            throw new IllegalArgumentException("Content identity is required");
        jdbc.update("INSERT INTO content_asset(asset_id,asset_kind,owner_user_id,title,filename,visibility,required_role,identity_key,lifecycle,current_version,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'PREPARING',NULL,1,?,?)",
                draft.assetId(),draft.kind().name(),draft.ownerUserId(),draft.title(),draft.filename(),
                draft.visibility(),draft.requiredRole(),draft.identityKey(),draft.createdAt(),draft.createdAt());
    }

    public void appendKnowledge(KnowledgeRevision input) {
        transaction();
        var identities=jdbc.queryForList("SELECT owner_user_id,current_version FROM content_asset WHERE asset_id=? AND asset_kind='KNOWLEDGE' FOR UPDATE",input.assetId());
        if(identities.size()!=1||((Number)identities.get(0).get("owner_user_id")).longValue()!=input.ownerUserId())
            throw new IllegalStateException("Knowledge revision owner differs from its content identity");
        Object current=identities.get(0).get("current_version");
        if(input.version()!=(current==null?1:((Number)current).intValue()+1))
            throw new IllegalStateException("Knowledge version must append to the current content version");
        byte[] original=input.sourceBytes();
        if(!sha(input.content().getBytes(StandardCharsets.UTF_8)).equals(input.contentSha256())
                ||!sha(original).equals(input.sourceSha256()))
            throw new IllegalArgumentException("Content and original-file digests must match their bytes");
        jdbc.update("INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,creator_user_id,title,filename,content_text,content_sha256,stored_content_sha256,source_bytes,source_sha256,byte_length,media_type,index_state,chunk_count,created_at) VALUES(?,'KNOWLEDGE',?,?,?,?,?,?,?,?,?,?,?,?,'READY',?,?)",
                input.assetId(),input.version(),input.ownerUserId(),input.creatorUserId(),input.title(),input.filename(),
                input.content(),input.contentSha256(),input.contentSha256(),original,input.sourceSha256(),original.length,
                input.mediaType(),input.chunks().size(),input.createdAt());
        int ordinal=0;
        for(String chunk:input.chunks()) jdbc.update("INSERT INTO content_chunk(asset_id,version,ordinal_no,locator,content_text) VALUES(?,?,?,?,?)",
                input.assetId(),input.version(),++ordinal,"文字段落 "+ordinal,chunk);
    }

    public void advanceKnowledge(String id, long expectedRevision, int version, String title,
                                 String filename, String visibility, LocalDateTime updatedAt) {
        transaction();
        int changed=jdbc.update("UPDATE content_asset SET title=?,filename=?,visibility=?,revision=CASE WHEN current_version IS NULL THEN revision ELSE revision+1 END,current_version=?,lifecycle='ACTIVE',updated_at=? WHERE asset_id=? AND asset_kind='KNOWLEDGE' AND revision=? AND (current_version IS NULL OR current_version=?) AND EXISTS (SELECT 1 FROM content_revision r WHERE r.asset_id=content_asset.asset_id AND r.asset_kind='KNOWLEDGE' AND r.version=?)",
                title,filename,visibility,version,updatedAt,id,expectedRevision,version-1,version);
        if(changed!=1) throw new IllegalStateException("Knowledge content changed before publication");
    }

    private void transaction() {
        if(!TransactionSynchronizationManager.isActualTransactionActive()||jdbc.getDataSource()==null
                ||!TransactionSynchronizationManager.hasResource(jdbc.getDataSource())
                ||!Boolean.FALSE.equals(jdbc.execute((ConnectionCallback<Boolean>) connection->connection.getAutoCommit())))
            throw new IllegalStateException("Content writes require the caller's transaction on this JDBC data source");
    }

    private static String sha(byte[] bytes) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch(java.security.NoSuchAlgorithmException unavailable) { throw new IllegalStateException(unavailable); }
    }
}
