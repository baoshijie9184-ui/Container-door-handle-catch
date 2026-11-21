package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionCaptureInfo;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadFileRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadMetadata;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.util.StringUtils;

@Repository
@RequiredArgsConstructor
@Slf4j
public class DetectionUploadMetadataStore {
    private static final int MAX_BYTES = 256 * 1024;

    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final OssStorageService oss;

    public record Registered(JsonNode document, boolean storedInOss) {}
    private record Snapshot(String contents, boolean storedInOss) {}

    public void save(String taskId, DetectionCaptureInfo capture, List<DetectionUploadFileRequest> files,
                     DetectionUploadMetadata metadata) {
        String contents = document(capture, files, metadata).toString();
        if (contents.getBytes(StandardCharsets.UTF_8).length > MAX_BYTES) {
            throw new BusinessException(400, "元数据内容不能超过 256 KB，请缩短备注或拆分批次");
        }
        jdbc.update("""
                INSERT INTO runtime_state(namespace,owner_id,scope_key,payload_version,payload_json,created_at,updated_at)
                VALUES('DETECTION_UPLOAD_METADATA',0,?,1,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                """, taskId, contents);
    }

    /** Call only after the task or its assigned upload source has been authorized. */
    public Registered read(String taskId) {
        var snapshot = load(taskId, false);
        if (snapshot == null) return null;
        try {
            return new Registered(json.readTree(snapshot.contents()), snapshot.storedInOss());
        } catch (JsonProcessingException invalid) {
            throw new BusinessException(500, "已登记的元数据暂不可读取");
        }
    }

    /** The upload confirmation transaction retains the same task and JSON for a retry. */
    public void storeInOss(String taskId, String originalPrefix) {
        var snapshot = load(taskId, true);
        if (snapshot == null || snapshot.storedInOss()) return;
        String key = UploadFolders.metadataKey(originalPrefix);
        byte[] bytes = snapshot.contents().getBytes(StandardCharsets.UTF_8);
        try {
            oss.putObject(key, new ByteArrayInputStream(bytes), bytes.length, "application/json");
        } catch (RuntimeException failure) {
            log.warn("OSS metadata write failed for task {} ({})", taskId, failure.getClass().getSimpleName());
            throw new BusinessException(503, "元数据文件暂未保存到 OSS，请重试上传确认");
        }
        jdbc.update("""
                UPDATE runtime_state SET state_code='OSS_STORED',updated_at=UTC_TIMESTAMP(6)
                WHERE namespace='DETECTION_UPLOAD_METADATA' AND owner_id=0 AND scope_key=?
                """, taskId);
    }

    private Snapshot load(String taskId, boolean lock) {
        var rows = jdbc.query("""
                SELECT payload_json, state_code FROM runtime_state
                WHERE namespace='DETECTION_UPLOAD_METADATA' AND owner_id=0 AND scope_key=?
                """ + (lock ? " FOR UPDATE" : ""),
                (row, index) -> new Snapshot(row.getString("payload_json"), "OSS_STORED".equals(row.getString("state_code"))),
                taskId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    ObjectNode document(DetectionCaptureInfo capture, List<DetectionUploadFileRequest> files,
                        DetectionUploadMetadata metadata) {
        String directory = metadata.rootDirectory();
        String prefix = StringUtils.hasText(directory) ? safePath(directory) + "/" : "";
        if (StringUtils.hasText(directory) && prefix.indexOf('/') != prefix.length() - 1) {
            throw new BusinessException(400, "元数据根目录无效");
        }
        var images = new LinkedHashMap<String, ObjectNode>();
        for (var file : files) {
            String path = safePath(StringUtils.hasText(file.getRelativePath()) ? file.getRelativePath() : file.getFileName());
            if (!prefix.isEmpty()) {
                if (!path.startsWith(prefix)) throw new BusinessException(400, "图片路径与元数据根目录不一致");
                path = safePath(path.substring(prefix.length()));
            }
            if (images.putIfAbsent(path, json.createObjectNode().put("path", path)) != null) {
                throw new BusinessException(400, "图片相对路径重复，请检查上传文件夹");
            }
        }
        var appliedPaths = new HashSet<String>();
        if (metadata.images() != null) {
            for (var image : metadata.images()) {
                if (image == null) throw new BusinessException(400, "图片元数据必须为对象");
                String path = safePath(image.path());
                ObjectNode stored = images.get(path);
                if (stored == null) throw new BusinessException(400, "元数据引用了未选中的图片：" + path);
                if (!appliedPaths.add(path)) throw new BusinessException(400, "图片元数据重复：" + path);
                addDetails(stored, image.notes(), image.attributes());
            }
        }
        ObjectNode result = json.createObjectNode().put("schemaVersion", 1);
        result.set("captureInfo", json.valueToTree(capture));
        addDetails(result, metadata.notes(), null);
        var manifest = result.putArray("images");
        images.values().forEach(manifest::add);
        return result;
    }

    private void addDetails(ObjectNode target, String notes, Map<String, String> attributes) {
        if (StringUtils.hasText(notes)) target.put("notes", notes.strip());
        if (attributes != null && !attributes.isEmpty()) target.set("attributes", json.valueToTree(attributes));
    }

    private static String safePath(String raw) {
        if (!StringUtils.hasText(raw) || raw.length() > 1024 || raw.chars().anyMatch(Character::isISOControl)) {
            throw new BusinessException(400, "图片元数据路径无效");
        }
        String path = raw.replace('\\', '/');
        if (path.matches("^[A-Za-z]:/.*") || Arrays.stream(path.split("/", -1)).anyMatch(part -> part.isBlank() || part.equals(".") || part.equals(".."))) {
            throw new BusinessException(400, "图片元数据须使用有效相对路径");
        }
        return path;
    }
}
