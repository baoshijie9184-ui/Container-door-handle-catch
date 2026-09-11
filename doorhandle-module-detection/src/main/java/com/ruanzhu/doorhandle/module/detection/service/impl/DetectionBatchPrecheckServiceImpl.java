package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionBatchPrecheckRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionBatchPrecheckResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadedFileItem;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionImageFingerprint;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionImageFingerprintMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionBatchPrecheckService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class DetectionBatchPrecheckServiceImpl implements DetectionBatchPrecheckService {
    private final DetectionImageFingerprintMapper fingerprintMapper;

    @Override
    public DetectionBatchPrecheckResponse precheck(DetectionBatchPrecheckRequest request, String ownerUserId) {
        String strategy = "ALL".equalsIgnoreCase(request.getStrategy()) ? "ALL" : "UNDETECTED_ONLY";
        List<String> hashes = request.getFiles().stream().map(DetectionUploadedFileItem::getSha256)
                .filter(this::isSha256).distinct().toList();
        Map<String, DetectionImageFingerprint> known = fingerprintMapper.findBySha256(hashes).stream()
                .collect(Collectors.toMap(DetectionImageFingerprint::getSha256, x -> x, (a, b) -> a));
        List<DetectionBatchPrecheckResponse.Item> items = request.getFiles().stream().map(file -> {
            DetectionImageFingerprint hit = known.get(file.getSha256());
            String status = hit == null ? "NEW" : normalize(hit.getStatus());
            if ("ALL".equals(strategy) && ("DETECTED".equals(status) || "APPROVED_PUBLIC".equals(status))) status = "DETECTED";
            return DetectionBatchPrecheckResponse.Item.builder().fileName(file.getFileName()).objectKey(file.getObjectKey())
                    .sha256(file.getSha256()).status(status).lastTaskId(hit == null ? null : hit.getLastTaskId()).build();
        }).toList();
        return DetectionBatchPrecheckResponse.builder().precheckToken(UUID.randomUUID().toString())
                .strategy(strategy).total(items.size())
                .newCount(count(items, "NEW")).detectedCount(count(items, "DETECTED") + count(items, "APPROVED_PUBLIC"))
                .runningCount(count(items, "RUNNING")).failedCount(count(items, "FAILED")).items(items).build();
    }

    private int count(List<DetectionBatchPrecheckResponse.Item> items, String status) {
        return (int) items.stream().filter(x -> status.equals(x.getStatus())).count();
    }

    private String normalize(String status) { return status == null || status.isBlank() ? "NEW" : status.toUpperCase(); }
    private boolean isSha256(String value) { return value != null && value.matches("[a-fA-F0-9]{64}"); }
}
