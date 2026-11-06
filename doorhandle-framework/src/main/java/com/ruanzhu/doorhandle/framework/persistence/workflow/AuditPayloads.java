package com.ruanzhu.doorhandle.framework.persistence.workflow;

public final class AuditPayloads {
    private AuditPayloads() { }
    public record ConversationInputV1(String status) {
        public ConversationInputV1 { WorkflowPayloads.text(status,32,"status"); }
    }
    public record KnowledgeV1(String documentId, long documentVersion, String action) {
        public KnowledgeV1 {
            WorkflowPayloads.text(documentId,128,"documentId"); WorkflowPayloads.text(action,64,"action");
            if (documentVersion<0) throw new IllegalArgumentException("Invalid document version");
        }
    }
}
