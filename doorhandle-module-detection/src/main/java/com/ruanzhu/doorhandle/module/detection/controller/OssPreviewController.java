package com.ruanzhu.doorhandle.module.detection.controller;

import com.aliyun.oss.ClientException;
import com.aliyun.oss.OSSException;
import com.ruanzhu.doorhandle.module.detection.service.OssPreviewAuthorizationService;
import com.ruanzhu.doorhandle.module.infra.config.properties.OssProperties;
import com.ruanzhu.doorhandle.module.infra.service.OssPreviewStorage;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.time.Duration;
import java.util.Locale;
import java.util.Set;

@RestController
@RequestMapping("/api/oss")
@RequiredArgsConstructor
public class OssPreviewController {
    private final OssPreviewStorage storage;
    private final OssProperties properties;
    private final OssPreviewAuthorizationService authorization;

    private static final Set<String> RASTER_TYPES = Set.of("image/jpeg", "image/png", "image/webp",
            "image/gif", "image/bmp", "image/avif", "image/tiff");

    @org.springframework.beans.factory.annotation.Value("${folder.results.dir:}")
    private String localResults;

    private java.nio.file.Path localFile(String key) {
        if (localResults == null || localResults.isBlank() || !key.startsWith("detection/folder-results/")) return null;
        String relative = key.substring("detection/folder-results/".length());
        if (!relative.matches("det_folder_[0-9a-f]{32}/[a-f0-9-]{36}/[^/\\\\]+"))
            throw new com.ruanzhu.doorhandle.common.BusinessException(400,"结果文件名无效");
        java.nio.file.Path root = java.nio.file.Path.of(localResults).toAbsolutePath().normalize();
        var file = root.resolve(relative).normalize();
        if (!file.startsWith(root) || !file.getFileName().toString().equals(relative.substring(relative.lastIndexOf('/')+1)))
            throw new com.ruanzhu.doorhandle.common.BusinessException(400,"结果文件名无效");
        return file;
    }

    @GetMapping("/preview")
    public void preview(@RequestParam String key, Authentication authentication,
                        @RequestHeader(name = "Sec-Fetch-Dest", defaultValue = "") String destination,
                        HttpServletResponse response) throws IOException {
        authorization.authorize(key, authentication);
        response.setHeader("Cache-Control", "private, no-store");
        var local = localFile(key);
        if (local != null) {
            if (!java.nio.file.Files.isRegularFile(local)) {response.setStatus(404); return;}
            response.setContentType(key.endsWith("/detection_results.json") ? "application/json" : "image/jpeg");
            response.setHeader("X-Content-Type-Options","nosniff");
            response.setHeader("Content-Security-Policy","sandbox; default-src 'none'");
            response.setContentLengthLong(java.nio.file.Files.size(local));
            java.nio.file.Files.copy(local,response.getOutputStream());
            return;
        }
        if (!storage.configured()) {
            response.setStatus(503);
            return;
        }
        if (!"image".equals(destination)) {
            response.sendRedirect(storage.sign(key, Duration.ofMinutes(properties.getPreviewUrlExpireMinutes())).toString());
            return;
        }
        // Embedded images stay on the application's origin even when a workstation cannot reach OSS.
        try (var object = storage.open(key, false)) {
            var metadata = object.getObjectMetadata();
            String mime = metadata.getContentType();
            response.setContentType(RASTER_TYPES.contains(mime == null ? "" : mime.toLowerCase(Locale.ROOT))
                    ? mime : "application/octet-stream");
            response.setHeader("X-Content-Type-Options", "nosniff");
            response.setHeader("Content-Security-Policy", "sandbox; default-src 'none'");
            if (metadata.getContentLength() >= 0) response.setContentLengthLong(metadata.getContentLength());
            var output = response.getOutputStream();
            try {
                object.getObjectContent().transferTo(output);
            } catch (IOException error) {
                object.forcedClose();
                throw error;
            }
        } catch (OSSException error) {
            if (!response.isCommitted()) response.setStatus("NoSuchKey".equals(error.getErrorCode()) ? 404 : 502);
        } catch (ClientException error) {
            if (!response.isCommitted()) response.setStatus(502);
        }
    }

    @GetMapping("/preview-status")
    public ResponseEntity<PreviewStatus> status(@RequestParam String key, Authentication authentication) {
        authorization.authorize(key, authentication);
        var local = localFile(key);
        if (local != null) return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(
            new PreviewStatus(java.nio.file.Files.isRegularFile(local) ? "READABLE" : "MISSING"));
        String reason = "NOT_CONFIGURED";
        if (storage.configured()) {
            try (var object = storage.open(key, true)) {
                reason = object.getObjectContent().read() >= 0 ? "READABLE" : "EMPTY";
            } catch (OSSException error) {
                reason = classify(error.getErrorCode(), error.getErrorMessage());
            } catch (IOException | ClientException error) {
                reason = "UNREACHABLE";
            }
        }
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(new PreviewStatus(reason));
    }

    record PreviewStatus(String reason) {}

    static String classify(String code, String message) {
        String detail = message == null ? "" : message.strip().toLowerCase(Locale.ROOT);
        if (Set.of("KmsInDebt", "InsufficientBalance", "AccountInArrears", "Arrearage").contains(code == null ? "" : code)
                || detail.matches("(?s)(?:your |the )?account (?:is in arrears|has (?:an )?overdue (?:payment|bill)|has insufficient balance)[.!]?(?: .*)?")
                || detail.matches("(?:您的|该|当前)?(?:阿里云)?(?:账号|账户)(?:已欠费|余额不足)[。！]?.*"))
            return "BILLING_OVERDUE";
        return switch (code == null ? "" : code) {
            case "UserDisable", "BucketDisable", "AbnormalBucketOwnerStatus" -> "DISABLED";
            case "NoSuchKey" -> "MISSING";
            case "InvalidAccessKeyId", "SignatureDoesNotMatch", "NoSuchBucket" -> "CONFIGURATION";
            case "AccessDenied", "AccessForbidden" -> "ACCESS_DENIED";
            default -> "UNAVAILABLE";
        };
    }
}
