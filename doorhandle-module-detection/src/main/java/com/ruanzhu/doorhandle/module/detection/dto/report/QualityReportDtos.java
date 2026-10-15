package com.ruanzhu.doorhandle.module.detection.dto.report;

import jakarta.validation.constraints.*;
import java.time.LocalDateTime;
import java.util.Map;

public final class QualityReportDtos {
    private QualityReportDtos() {}
    public record Create(@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,128}") String taskId,
            @NotBlank @Size(max=120) String title, @NotBlank @Size(max=10000) String narrative,
            @NotBlank @Pattern(regexp="[A-Za-z0-9_-]{8,64}") String requestId) {}
    public record Edit(@NotNull @Min(1) Integer expectedVersion, @NotBlank @Size(max=120) String title,
            @NotBlank @Size(max=10000) String narrative, @NotBlank @Pattern(regexp="[A-Za-z0-9_-]{8,64}") String requestId) {}
    public record Command(@NotNull @Min(1) Integer expectedVersion,
            @NotBlank @Pattern(regexp="[A-Za-z0-9_-]{8,64}") String requestId) {}
    public record DecisionPreview(@NotNull @Min(1) Integer expectedVersion,
            @NotBlank @Pattern(regexp="APPROVE|REJECT") String decision, @NotBlank @Size(max=500) String reason) {}
    public record Decision(@NotNull @Min(1) Integer expectedVersion,
            @NotBlank @Pattern(regexp="APPROVE|REJECT") String decision, @NotBlank @Size(max=500) String reason,
            @NotBlank @Pattern(regexp="[a-f0-9]{64}") String confirmationToken,
            @NotBlank @Pattern(regexp="[A-Za-z0-9_-]{8,64}") String requestId) {}
    public record View(String reportId, String previousReportId, long ownerUserId, String ownerUsername,
            String taskId, String title, String narrative, String status, int version,
            Map<String,Object> source, String sourceSha256, String snapshotSha256,
            LocalDateTime submittedAt, LocalDateTime decidedAt, String deciderUsername, String decisionReason,
            LocalDateTime createdAt, LocalDateTime updatedAt) {}
    public record Preview(View report, String decision, String reason, String confirmationToken, LocalDateTime expiresAt) {}
    public record EventDelivery(String eventId,String eventType,String deliveryStatus,int attempts,LocalDateTime nextAttemptAt,
            LocalDateTime deliveredAt,String lastErrorCode,LocalDateTime consumedAt) {}
    public record RetryEvent(@NotNull @Min(0) Integer expectedAttempts,@AssertTrue boolean confirmed,
            @NotBlank @Pattern(regexp="[A-Za-z0-9_-]{8,64}") String requestId) {}
    public record Audit(long id, String actorUsername, String action, String beforeStatus, String afterStatus,
            int reportVersion, String reason, String snapshotSha256, LocalDateTime createdAt,String runId,String callId,String toolName) {}
}
