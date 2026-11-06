package com.ruanzhu.doorhandle.framework.persistence.content;

/** Registered content contracts, not arbitrary table names or caller-provided namespaces. */
public enum ContentKind {
    KNOWLEDGE, SKILL, WORKSPACE_FILE, RESEARCH_SOURCE, CONTEXT_SUMMARY,
    TOOL_EVIDENCE, SKILL_IMPORT, DETECTION_IMAGE,
    DETECTION_MODEL, CONNECTOR_IMAGE, CONNECTOR_PACKAGE, REPORT_EXPORT,
    CHAT_MESSAGE_EVIDENCE
}
