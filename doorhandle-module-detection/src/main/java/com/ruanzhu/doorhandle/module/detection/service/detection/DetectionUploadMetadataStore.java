package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionCaptureInfo;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadFileRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadMetadata;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.util.StringUtils;

@Repository
@RequiredArgsConstructor
public class DetectionUploadMetadataStore {
    private static final int MAX_BYTES = 256 * 1024;

    private final JdbcTemplate jdbc;
    private final ObjectMapper json;

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
    public JsonNode read(String taskId) {
        var rows = jdbc.queryForList("""
                SELECT payload_json FROM runtime_state
                WHERE namespace='DETECTION_UPLOAD_METADATA' AND owner_id=0 AND scope_key=?
                """, String.class, taskId);
        if (rows.isEmpty()) return null;
        try {
            return json.readTree(rows.get(0));
        } catch (JsonProcessingException invalid) {
            throw new BusinessException(500, "已登记的元数据暂不可读取");
        }
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
