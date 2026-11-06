package com.ruanzhu.doorhandle.module.detection.mapper;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionImageFingerprint;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Bounded read projection: content identity and current detection state have separate owners. */
@Repository
public class DetectionImageFingerprintMapper {
    private final NamedParameterJdbcTemplate jdbc;
    private final ObjectMapper json;

    public DetectionImageFingerprintMapper(org.springframework.jdbc.core.JdbcTemplate jdbc, ObjectMapper json) {
        this.jdbc = new NamedParameterJdbcTemplate(jdbc);
        this.json = json;
    }

    public List<DetectionImageFingerprint> findBySha256(Collection<String> hashes) {
        if (hashes == null || hashes.isEmpty()) return List.of();
        var normalized = hashes.stream().map(hash -> {
            if (hash == null || !hash.matches("[a-fA-F0-9]{64}")) throw new IllegalArgumentException("图片摘要无效");
            return hash.toLowerCase(Locale.ROOT);
        }).distinct().toList();
        return jdbc.query("""
                SELECT a.identity_key AS sha256,r.filename,r.object_key,s.state_code,s.current_ref,
                       s.revision,s.payload_version,s.payload_json,s.created_at,s.updated_at
                FROM content_asset a
                LEFT JOIN content_revision r ON r.asset_id=a.asset_id AND r.asset_kind=a.asset_kind AND r.version=a.current_version
                LEFT JOIN runtime_state s ON s.namespace='DETECTION_FINGERPRINT' AND s.owner_id=0 AND s.scope_key=a.identity_key
                WHERE a.asset_kind='DETECTION_IMAGE' AND a.identity_key IN (:hashes)
                """, Map.of("hashes", normalized), (row, index) -> {
            if (row.getObject("payload_version") == null || row.getInt("payload_version") != 1
                    || row.getString("state_code") == null || row.getString("filename") == null || row.getString("object_key") == null)
                throw new IllegalStateException("图片指纹投影或内容引用不完整");
            JsonNode payload = decodePayload(row.getString("payload_json"));
            long revision = row.getLong("revision");
            if (revision < 0 || revision > Integer.MAX_VALUE) throw new IllegalStateException("图片指纹版本越界");
            var value = new DetectionImageFingerprint();
            value.setId(payload.get("originalId").longValue());
            value.setSha256(row.getString("sha256")); value.setFileName(row.getString("filename"));
            value.setObjectKey(row.getString("object_key")); value.setStatus(row.getString("state_code"));
            value.setLastTaskId(row.getString("current_ref")); value.setVersion((int) revision);
            value.setOwnerUserId(payload.get("sourceOwnerKey").isNull() ? null : payload.get("sourceOwnerKey").textValue());
            value.setCreatedAt(row.getObject("created_at", java.time.LocalDateTime.class));
            value.setUpdatedAt(row.getObject("updated_at", java.time.LocalDateTime.class));
            return value;
        });
    }

    private JsonNode decodePayload(String encoded) {
        try {
            JsonNode value = json.readTree(encoded);
            if (value == null || !value.isObject() || value.size() != 2
                    || !value.has("originalId") || !value.get("originalId").isIntegralNumber()
                    || !value.get("originalId").canConvertToLong() || value.get("originalId").longValue() <= 0
                    || !value.has("sourceOwnerKey") || !(value.get("sourceOwnerKey").isNull()
                    || (value.get("sourceOwnerKey").isTextual() && value.get("sourceOwnerKey").textValue().length() <= 64)))
                throw new IllegalStateException("图片指纹 V1 来源信息不正确");
            return value;
        } catch (com.fasterxml.jackson.core.JsonProcessingException | IllegalArgumentException error) {
            throw new IllegalStateException("图片指纹 V1 来源信息无法读取", error);
        }
    }
}
