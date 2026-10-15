package com.ruanzhu.doorhandle.module.infra.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.common.SafePathResolver;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.stream.Stream;

@RestController
@RequestMapping("/api")
@Slf4j
@RequiredArgsConstructor
public class FileController {

    private final SafePathResolver safePathResolver;
    private final org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.infra.security.LocalDetectionFileAuthorization> detectionFiles;

    @Value("${detection.upload-dir:${user.dir}/uploads/images}")
    private String imageUploadDir;

    @Value("${detection.annotated-dir:${user.dir}/uploads/annotated}")
    private String annotatedDir;

    @Value("${detection.result-dir:${user.dir}/uploads/results}")
    private String resultDir;

    @Value("${file.upload.path.models:${user.dir}/uploads/models}")
    private String modelUploadPath;

    @Value("${model.max-upload-bytes:209715200}")
    private long maxModelUploadBytes;

    @GetMapping("/files/images/{folder}/{fileName:.+}")
    public ResponseEntity<Resource> getImage(
            @PathVariable String folder,
            @PathVariable String fileName) {
        Path path=safePathResolver.resolveUnderBase(imageUploadDir, folder, fileName);
        authorize(com.ruanzhu.doorhandle.module.infra.security.LocalDetectionFileAuthorization.Kind.IMAGE,path);
        return getFileResource(path);
    }

    @GetMapping("/files/annotated/{folder}/{fileName:.+}")
    public ResponseEntity<Resource> getAnnotatedImage(
            @PathVariable String folder,
            @PathVariable String fileName) {
        Path path=safePathResolver.resolveUnderBase(annotatedDir, folder, fileName);
        authorize(com.ruanzhu.doorhandle.module.infra.security.LocalDetectionFileAuthorization.Kind.ANNOTATED,path);
        return getFileResource(path);
    }

    @GetMapping("/files/results/{folder}/{fileName:.+}")
    public ResponseEntity<Resource> getResultFile(
            @PathVariable String folder,
            @PathVariable String fileName) {
        Path path=safePathResolver.resolveUnderBase(resultDir, folder, fileName);
        authorize(com.ruanzhu.doorhandle.module.infra.security.LocalDetectionFileAuthorization.Kind.RESULT,path);
        return getFileResource(path);
    }

    @GetMapping("/files/models/{fileName:.+}")
    public ResponseEntity<Resource> getModelFile(@PathVariable String fileName) {
        return getFileResource(safePathResolver.resolveUnderBase(modelUploadPath, fileName));
    }

    @GetMapping("/files/annotated/{folder}")
    public ResponseEntity<?> listAnnotatedImages(@PathVariable String folder) {
        try {
            Path folderPath = safePathResolver.resolveUnderBase(annotatedDir, folder);
            authorize(com.ruanzhu.doorhandle.module.infra.security.LocalDetectionFileAuthorization.Kind.ANNOTATED,folderPath);
            if (!Files.exists(folderPath) || !Files.isDirectory(folderPath)) {
                log.warn("Annotated folder does not exist: {}", folderPath);
                return ResponseEntity.notFound().build();
            }

            List<FileInfo> files;
            try (Stream<Path> stream = Files.list(folderPath)) {
                files = stream
                        .filter(Files::isRegularFile)
                        .filter(path -> isImageFile(path.getFileName().toString()))
                        .map(path -> new FileInfo(
                                path.getFileName().toString(),
                                "/api/files/annotated/" + folder + "/" + path.getFileName()))
                        .toList();
            }
            return ResponseEntity.ok().cacheControl(org.springframework.http.CacheControl.noStore()).body(files);
        } catch (IOException e) {
            log.error("Failed to list annotated images for folder {}", folder, e);
            return ResponseEntity.badRequest().build();
        }
    }

    @PostMapping("/upload/model")
    public Result<String> uploadModel(@RequestParam("file") MultipartFile file) {
        if (file.isEmpty()) {
            return Result.error("上传的文件不能为空");
        }

        String originalFilename = file.getOriginalFilename();
        if (originalFilename == null || !originalFilename.toLowerCase(Locale.ROOT).endsWith(".onnx")) {
            return Result.error("只能上传 ONNX 模型文件");
        }
        if (file.getSize() > maxModelUploadBytes) {
            return Result.error("模型文件不能超过 " + formatBytes(maxModelUploadBytes));
        }

        try {
            String fileExtension = originalFilename.substring(originalFilename.lastIndexOf('.')).toLowerCase(Locale.ROOT);
            String newFilename = UUID.randomUUID() + fileExtension;
            Path targetPath = safePathResolver.resolveUnderBase(modelUploadPath, newFilename);
            Files.createDirectories(targetPath.getParent());
            file.transferTo(targetPath);

            String fileUrl = "/api/files/models/" + newFilename;
            log.info("Model file uploaded: {}", fileUrl);
            return Result.success(fileUrl);
        } catch (IOException e) {
            log.error("Failed to upload model file", e);
            return Result.error("模型文件上传失败: " + e.getMessage());
        }
    }

    @GetMapping("/direct/annotated/{folder}/{fileName:.+}")
    public ResponseEntity<Resource> getDirectAnnotatedImage(
            @PathVariable String folder,
            @PathVariable String fileName) {
        return getAnnotatedImage(folder, fileName);
    }

    @GetMapping("/direct/images/{folder}/{fileName:.+}")
    public ResponseEntity<Resource> getDirectImage(
            @PathVariable String folder,
            @PathVariable String fileName) {
        return getImage(folder, fileName);
    }

    private ResponseEntity<Resource> getFileResource(Path filePath) {
        try {
            Resource resource = new FileSystemResource(filePath);
            if (!resource.exists() || !resource.isReadable()) {
                log.warn("File not found or unreadable: {}", filePath);
                return ResponseEntity.notFound().build();
            }

            return ResponseEntity.ok()
                    .cacheControl(org.springframework.http.CacheControl.noStore())
                    .contentType(resolveMediaType(filePath.getFileName().toString()))
                    .body(resource);
        } catch (Exception e) {
            log.error("Failed to serve file {}", filePath, e);
            return ResponseEntity.badRequest().build();
        }
    }

    private void authorize(com.ruanzhu.doorhandle.module.infra.security.LocalDetectionFileAuthorization.Kind kind,Path path) {
        var authorization=detectionFiles.getIfAvailable();
        if(authorization==null) throw new org.springframework.security.access.AccessDeniedException("检测文件权限服务不可用");
        authorization.authorize(kind,path);
    }

    private MediaType resolveMediaType(String fileName) {
        String lowerCaseName = fileName.toLowerCase(Locale.ROOT);
        if (lowerCaseName.endsWith(".jpg") || lowerCaseName.endsWith(".jpeg")) {
            return MediaType.IMAGE_JPEG;
        }
        if (lowerCaseName.endsWith(".png")) {
            return MediaType.IMAGE_PNG;
        }
        if (lowerCaseName.endsWith(".gif")) {
            return MediaType.IMAGE_GIF;
        }
        if (lowerCaseName.endsWith(".txt")) {
            return MediaType.TEXT_PLAIN;
        }
        if (lowerCaseName.endsWith(".json")) {
            return MediaType.APPLICATION_JSON;
        }
        return MediaType.APPLICATION_OCTET_STREAM;
    }

    private boolean isImageFile(String fileName) {
        String lowerCaseName = fileName.toLowerCase(Locale.ROOT);
        return lowerCaseName.endsWith(".jpg")
                || lowerCaseName.endsWith(".jpeg")
                || lowerCaseName.endsWith(".png")
                || lowerCaseName.endsWith(".gif");
    }

    private String formatBytes(long bytes) {
        if (bytes >= 1024L * 1024L) {
            return (bytes / 1024L / 1024L) + "MB";
        }
        if (bytes >= 1024L) {
            return (bytes / 1024L) + "KB";
        }
        return bytes + "B";
    }

    public static class FileInfo {
        private final String name;
        private final String url;

        public FileInfo(String name, String url) {
            this.name = name;
            this.url = url;
        }

        public String getName() {
            return name;
        }

        public String getUrl() {
            return url;
        }
    }
}
