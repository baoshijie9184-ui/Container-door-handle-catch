package com.ruanzhu.doorhandle.framework.persistence.workflow;

import java.util.Set;

/** Explicit version-one payloads; no arbitrary map is accepted for these protocols. */
public final class WorkflowPayloads {
    private WorkflowPayloads() { }
    public record ConversationInputV1(String username, String mode, String requestedMode,
                                      String entryPoint, String content, String contentSha256,
                                      @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL) Long queueOrder) {
        public ConversationInputV1(String username,String mode,String requestedMode,String entryPoint,String content,String contentSha256) {
            this(username,mode,requestedMode,entryPoint,content,contentSha256,null);
        }
        public ConversationInputV1 {
            text(username, 128, "username");
            if (!Set.of("NEXT_TURN", "NEXT_STEP").contains(mode)
                    || !Set.of("NEXT_TURN", "NEXT_STEP").contains(requestedMode)
                    || !Set.of("CHAT", "AGUI").contains(entryPoint)
                    || content == null || content.length() > ("NEXT_STEP".equals(mode) ? 4000 : 8000)
                    || (queueOrder != null && queueOrder <= 0) || contentSha256 == null || !contentSha256.matches("[a-f0-9]{64}")) {
                throw new IllegalArgumentException("Invalid conversation input payload");
            }
        }
        public ConversationInputV1 withContent(String body, String digest) {
            return new ConversationInputV1(username, mode, requestedMode, entryPoint, body, digest, queueOrder);
        }
        public ConversationInputV1 withQueueOrder(long position) {
            return new ConversationInputV1(username, mode, requestedMode, entryPoint, content, contentSha256, position);
        }
        public ConversationInputV1 withMode(String value) {
            return new ConversationInputV1(username, value, requestedMode, entryPoint, content, contentSha256, queueOrder);
        }
    }
    public record KnowledgeCommandV1(String documentId, long documentVersion, String action) {
        public KnowledgeCommandV1 {
            text(documentId, 128, "documentId"); text(action, 64, "action");
            if (documentVersion < 0) throw new IllegalArgumentException("Invalid document version");
        }
    }
    public record WorkspaceForkV1(String sourceSessionId, long throughMessageId, String resultSessionId) {
        public WorkspaceForkV1 {
            text(sourceSessionId, 128, "sourceSessionId"); text(resultSessionId, 128, "resultSessionId");
            if (throughMessageId <= 0) throw new IllegalArgumentException("Invalid fork boundary");
        }
    }
    static void text(String value, int limit, String field) {
        if (value == null || value.isBlank() || value.length() > limit)
            throw new IllegalArgumentException("Invalid workflow " + field);
    }
}
