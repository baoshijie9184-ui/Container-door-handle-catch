package com.ruanzhu.doorhandle.module.ai.testsupport;

import java.util.List;

/** The same complete source baseline used by the compact assembler, including provenance guards. */
public final class CompactBaselineParts {
    private CompactBaselineParts() {}
    public static List<String> all(){return List.of("10-core.sql","20-content.sql","25-agent.sql","30-operations.sql",
        "35-runtime-guards.sql","36-identity-guards.sql","37-audit-guards.sql","38-quota-guards.sql","39-workflow-guards.sql",
        "35-legacy-clock-content-asset.sql","35-legacy-clock-content-revision.sql","35-legacy-clock-content-link.sql",
        "35-legacy-clock-agent-run.sql","35-legacy-clock-agent-connector.sql","35-legacy-clock-runtime-state.sql",
        "35-legacy-clock-workflow-instance.sql","35-legacy-clock-audit-event.sql","35-legacy-clock-parent-model-management.sql",
        "35-legacy-clock-parent-chat-session.sql","35-legacy-clock-parent-users.sql","40-relations.sql");}
    public static String separator(String name){return name.endsWith("-guards.sql")||name.startsWith("35-legacy-clock-")?"$$":";";}
}
