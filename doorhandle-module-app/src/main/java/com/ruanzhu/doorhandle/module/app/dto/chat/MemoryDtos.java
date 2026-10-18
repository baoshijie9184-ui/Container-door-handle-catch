package com.ruanzhu.doorhandle.module.app.dto.chat;

import jakarta.validation.constraints.*;
import java.util.List;

public final class MemoryDtos {
    private MemoryDtos() {}
    public record Preference(boolean readEnabled, boolean saveEnabled, int revision, String updatedAt) {}
    public record ChangePreference(@NotNull @Min(0) Integer expectedRevision, @NotNull Boolean readEnabled, @NotNull Boolean saveEnabled) {}
    public record Item(String id, String memory, String sourceSessionId, String createdAt, String updatedAt, String digest, Lifecycle lifecycle) {
        public Item(String id,String memory,String sourceSessionId,String createdAt,String updatedAt,String digest){this(id,memory,sourceSessionId,createdAt,updatedAt,digest,null);}
    }
    public record Lifecycle(String memoryId,int revision,String state,String expiresAt,boolean autoDelete,String cleanupState,String updatedAt) {}
    public record ChangeLifecycle(@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,64}") String requestId,
                                  @NotBlank @Pattern(regexp="[a-f0-9]{64}") String expectedDigest,
                                  @NotNull @Min(0) Integer expectedRevision,
                                  @NotBlank @Pattern(regexp="ACTIVE|EXCLUDED") String state,
                                  @Size(max=50) String expiresAt, boolean autoDelete, @AssertTrue boolean confirmed) {}
    public record StartReview(@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,64}") String requestId,
                              @NotBlank @Pattern(regexp="[a-f0-9]{64}") String expectedDigest,
                              @NotNull @Min(0) Integer expectedRevision) {}
    public record ResolveReview(@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,64}") String requestId,
                                @NotNull @Min(1) Integer expectedRevision,
                                @NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,64}") String candidateId,
                                @NotBlank @Pattern(regexp="KEEP_SOURCE|KEEP_CANDIDATE|KEEP_BOTH") String choice,
                                @AssertTrue boolean confirmed) {}
    public record ReviewPair(String id,Item item,boolean stale,String label,Double similarity) {}
    public record ReviewDecision(String requestId,String candidateId,String choice,int expectedRevision,String createdAt) {}
    public record Review(String id,String sourceId,String status,int revision,Item source,boolean sourceStale,String judgmentStatus,
                         List<ReviewPair> candidates,List<ReviewDecision> decisions,String createdAt,String updatedAt,int searchLimit,
                         Boolean modelCalled,String modelName,Long modelMillis,Integer inputTokens,Integer outputTokens,Integer totalTokens,String usageSource) {}
    public record ReviewHistory(String id,String sourceId,String status,String createdAt) {}
    public record Page(List<Item> items, boolean hasMore, Integer nextOffset) {
        public Page(List<Item> items, boolean hasMore) { this(items, hasMore, null); }
    }
    public record Delete(@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,64}") String requestId,
                         @NotBlank @Pattern(regexp="[a-f0-9]{64}") String expectedDigest, @AssertTrue boolean confirmed) {}
    public record Deleted(boolean deleted, boolean replayed) {}
    public record Update(@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,64}") String requestId,
                         @NotBlank @Pattern(regexp="[a-f0-9]{64}") String expectedDigest,
                         @NotBlank @Size(max=4000) String memory, @AssertTrue boolean confirmed) {}
    public record Updated(boolean updated, boolean replayed) {}
    public record Audit(long id, String action, String outcome, String memoryId, Integer preferenceRevision,
                        Boolean readEnabled, Boolean saveEnabled, String createdAt, String updatedAt, String requestId) {}
    public record Extraction(String requestId,String status,Integer affectedMemories,String updatedAt) {}
}
