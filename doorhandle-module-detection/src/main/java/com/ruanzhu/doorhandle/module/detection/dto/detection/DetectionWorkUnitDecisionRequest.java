package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

public record DetectionWorkUnitDecisionRequest(@NotNull @Min(0) Integer expectedVersion,
                                               @NotNull UUID requestId,
                                               @Size(max = 1000) String reason) {}
