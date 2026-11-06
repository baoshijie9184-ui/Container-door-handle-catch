package com.ruanzhu.doorhandle.module.app.testsupport;

import org.springframework.jdbc.core.JdbcTemplate;

/** Withdrawn aggregate fixture. The ECS 29-table CompactMySqlFixture is authoritative. */
@Deprecated
public final class CompactChatFixture {
    private CompactChatFixture() { }

    public static void install(JdbcTemplate jdbc) {
        throw new UnsupportedOperationException("The 003/004 chat fixture is withdrawn; use CompactMySqlFixture on an admitted empty ECS schema");
    }
}
