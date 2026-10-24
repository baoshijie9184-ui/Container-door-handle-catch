package com.ruanzhu.doorhandle.module.infra.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.common.SafePathResolver;
import com.ruanzhu.doorhandle.contracts.agent.FileDelivery;
import com.ruanzhu.doorhandle.contracts.files.*;
import com.ruanzhu.doorhandle.module.infra.security.AuthorizedLocalFileResource;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
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
import java.util.stream.Stream;

@RestController
@RequestMapping("/api")
@Slf4j
@RequiredArgsConstructor
public class FileController {

    private final SafePathResolver safePathResolver;
    private final org.springframework.beans.factory.ObjectProvider<LocalDetectionFilesApi> detectionFiles;
    private final org.springframework.beans.factory.ObjectProvider<LocalModelFilesApi> modelFiles;

    @Value("${detection.upload-dir:${user.dir}/uploads/images}")
    private String imageUploadDir;

    @Value("${detection.annotated-dir:${user.dir}/uploads/annotated}")
    private String annotatedDir;

    @Value("${detection.result-dir:${user.dir}/uploads/results}")
    private String resultDir;

    @Value("${model.upload-dir:${user.dir}/uploads/models}")
    private String modelUploadPath;

    @GetMapping("/files/images/{folder}/{fileName:.+}")
    @FileDelivery(domain="DETECTION_IMAGE",resource="result.body.id",file="result.body.fileId",version="result.body.version",scope="ENTERPRISE")
    public ResponseEntity<Resource> getImage(
            @PathVariable String folder,
            @PathVariable String fileName) {
        Path path=safePathResolver.resolveUnderBase(imageUploadDir, folder, fileName);
        return detectionResource(LocalDetectionFilesApi.Kind.IMAGE,Path.of(imageUploadDir),path);
    }

    @GetMapping("/files/annotated/{folder}/{fileName:.+}")
    @FileDelivery(domain="DETECTION_ANNOTATION",resource="result.body.id",file="result.body.fileId",version="result.body.version",scope="ENTERPRISE")
    public ResponseEntity<Resource> getAnnotatedImage(
            @PathVariable String folder,
            @PathVariable String fileName) {
        Path path=safePathResolver.resolveUnderBase(annotatedDir, folder, fileName);
        return detectionResource(LocalDetectionFilesApi.Kind.ANNOTATED,Path.of(annotatedDir),path);
    }

    @GetMapping("/files/results/{folder}/{fileName:.+}")
    @FileDelivery(domain="DETECTION_RESULT",resource="result.body.id",file="result.body.fileId",version="result.body.version",scope="ENTERPRISE")
    public ResponseEntity<Resource> getResultFile(
            @PathVariable String folder,
            @PathVariable String fileName) {
        Path path=safePathResolver.resolveUnderBase(resultDir, folder, fileName);
        return detectionResource(LocalDetectionFilesApi.Kind.RESULT,Path.of(resultDir),path);
    }

    @GetMapping("/files/models/{fileName:.+}")
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    @FileDelivery(domain="DETECTION_MODEL_DOWNLOAD",resource="result.body.id",file="result.body.fileId",version="result.body.version",scope="ENTERPRISE")
    public ResponseEntity<Resource> getModelFile(@PathVariable String fileName) {
        Path path=safePathResolver.resolveUnderBase(modelUploadPath,fileName);
        var owner=modelFiles.getIfAvailable();
        if(owner==null) throw new org.springframework.security.access.AccessDeniedException("模型文件权限服务不可用");
        var grant=owner.authorizeFile(path);
        return getFileResource(Path.of(modelUploadPath),path,grant,()->owner.authorizeFile(path));
    }

    @GetMapping("/files/annotated/{folder}")
    public ResponseEntity<?> listAnnotatedImages(@PathVariable String folder) {
        try {
            Path folderPath = safePathResolver.resolveUnderBase(annotatedDir, folder);
            var owner=detectionOwner();
            var folderGrant=owner.authorizeFile(LocalDetectionFilesApi.Kind.ANNOTATED,folderPath);
            if (!Files.exists(folderPath) || !Files.isDirectory(folderPath)) {
                log.warn("Authorized annotated folder is unavailable");
                return ResponseEntity.notFound().build();
            }

            List<FileInfo> files;
            try (Stream<Path> stream = Files.list(folderPath)) {
                files = stream
                        .filter(Files::isRegularFile)
                        .filter(path -> isImageFile(path.getFileName().toString()))
                        .filter(path -> {
                            try { return owner.authorizeFile(LocalDetectionFilesApi.Kind.ANNOTATED,path).resourceId().equals(folderGrant.resourceId()); }
                            catch(org.springframework.security.access.AccessDeniedException | SecurityException denied) { return false; }
                        })
                        .map(path -> new FileInfo(
                                path.getFileName().toString(),
                                org.springframework.web.util.UriComponentsBuilder.fromPath("/api/files/annotated").pathSegment(folder,path.getFileName().toString()).build().encode().toUriString()))
                        .toList();
            }
            return ResponseEntity.ok().cacheControl(org.springframework.http.CacheControl.noStore()).body(files);
        } catch (IOException e) {
            log.warn("Authorized annotated folder could not be listed");
            return ResponseEntity.badRequest().build();
        }
    }

    @PostMapping("/upload/model")
    @org.springframework.web.bind.annotation.ResponseStatus(org.springframework.http.HttpStatus.GONE)
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    public Result<String> uploadModel(@RequestParam("file") MultipartFile file) {
        return Result.error(410,"旧的未登记上传入口已停用，请使用 /api/models/upload 并提供模型名称、版本及文件");
    }

    @GetMapping("/direct/annotated/{folder}/{fileName:.+}")
    @FileDelivery(domain="DETECTION_ANNOTATION",resource="result.body.id",file="result.body.fileId",version="result.body.version",scope="ENTERPRISE")
    public ResponseEntity<Resource> getDirectAnnotatedImage(
            @PathVariable String folder,
            @PathVariable String fileName) {
        return getAnnotatedImage(folder, fileName);
    }

    @GetMapping("/direct/images/{folder}/{fileName:.+}")
    @FileDelivery(domain="DETECTION_IMAGE",resource="result.body.id",file="result.body.fileId",version="result.body.version",scope="ENTERPRISE")
    public ResponseEntity<Resource> getDirectImage(
            @PathVariable String folder,
            @PathVariable String fileName) {
        return getImage(folder, fileName);
    }

    private ResponseEntity<Resource> detectionResource(LocalDetectionFilesApi.Kind kind,Path base,Path path) {
        var owner=detectionOwner();var grant=owner.authorizeFile(kind,path);
        return getFileResource(base,path,grant,()->owner.authorizeFile(kind,path));
    }
    private LocalDetectionFilesApi detectionOwner() {
        var owner=detectionFiles.getIfAvailable();
        if(owner==null) throw new org.springframework.security.access.AccessDeniedException("检测文件权限服务不可用");
        return owner;
    }
    private ResponseEntity<Resource> getFileResource(Path base,Path filePath,BusinessFileGrant grant,java.util.function.Supplier<BusinessFileGrant> reauthorize) {
        try {
            if (!Files.isRegularFile(filePath,java.nio.file.LinkOption.NOFOLLOW_LINKS) || !Files.isReadable(filePath)) {
                return ResponseEntity.notFound().build();
            }
            Resource resource = new AuthorizedLocalFileResource(base,filePath,grant,reauthorize);

            return ResponseEntity.ok()
                    .cacheControl(org.springframework.http.CacheControl.noStore())
                    .header("X-Content-Type-Options","nosniff")
                    .header("Content-Security-Policy","default-src 'none'; sandbox")
                    .contentType(resolveMediaType(filePath.getFileName().toString()))
                    .body(resource);
        } catch (IOException e) {
            log.warn("Business file could not be prepared for delivery");
            return ResponseEntity.notFound().build();
        }
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
