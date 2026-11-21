package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.Map;

public record DetectionUploadMetadata(
        @Size(max = 255) String rootDirectory,
        @Size(max = 1000) String notes,
        @Size(max = 5000) List<@Valid Image> images) {
    public record Image(
            @NotBlank @Size(max = 1024) String path,
            @Size(max = 1000) String notes,
            @Size(max = 16) Map<@NotBlank @Size(max = 80) String, @NotBlank @Size(max = 300) String> attributes) {}
}
