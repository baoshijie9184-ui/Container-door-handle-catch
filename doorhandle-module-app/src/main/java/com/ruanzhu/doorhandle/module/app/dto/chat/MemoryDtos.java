package com.ruanzhu.doorhandle.module.app.dto.chat;

import jakarta.validation.constraints.*;
import java.util.List;

public final class MemoryDtos {
    private MemoryDtos() {}
    public record Preference(boolean readEnabled, boolean saveEnabled, int revision, String updatedAt) {}
    public record ChangePreference(@NotNull @Min(0) Integer expectedRevision, @NotNull Boolean readEnabled, @NotNull Boolean saveEnabled) {}
    public record Item(String id, String memory, String sourceSessionId, String createdAt, String updatedAt, String digest) {}
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
                        Boolean readEnabled, Boolean saveEnabled, String createdAt, String updatedAt) {}
}
