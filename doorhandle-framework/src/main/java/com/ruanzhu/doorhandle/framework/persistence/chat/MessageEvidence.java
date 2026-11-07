package com.ruanzhu.doorhandle.framework.persistence.chat;

/** Original message identities live in the audit envelope, independently of the current chat projection. */
public final class MessageEvidence {
    private MessageEvidence() { }
    public static final String EXECUTION="MESSAGE_EXECUTION", SNAPSHOT="MESSAGE_WORKSPACE_SNAPSHOT", SOURCES="MESSAGE_CONTEXT_SOURCES";
    public record ExecutionV1(String legacyId,String createdAtSource,String sourceUtcOffset) { }
    /** Historical provenance of an authorized message link, independent of the message body date. */
    public record ExecutionLink(String runId,String clockStatus,java.util.Map<String,String> sourceWallTimes) {
        public ExecutionLink { sourceWallTimes=java.util.Collections.unmodifiableMap(new java.util.LinkedHashMap<>(sourceWallTimes)); }
    }
    public record WorkspaceSnapshotV1(String legacyId,String snapshotJson,String createdAtSource,String sourceUtcOffset) { }
    public record ContextSourcesV1(String sourcesJson) { }
}
