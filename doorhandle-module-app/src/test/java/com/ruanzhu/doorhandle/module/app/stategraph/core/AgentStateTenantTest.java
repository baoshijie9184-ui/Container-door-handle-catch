package com.ruanzhu.doorhandle.module.app.stategraph.core;

import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AgentStateTenantTest {

    @Test
    void restoresTenantContextFromImmutableUserId() {
        AgentState state = AgentState.create("sess_1", "hello", "alice")
                .set(AgentState.KEY_TENANT_USER_ID, 42L);

        assertThat(state.requireTenantContext()).isEqualTo(new TenantContext(42L, "alice"));
    }

    @Test
    void rejectsStateWithoutTenantUserId() {
        AgentState state = AgentState.create("sess_1", "hello", "alice");

        assertThatThrownBy(state::requireTenantContext)
                .isInstanceOf(StateGraphException.class)
                .hasMessageContaining("租户用户 ID");
    }
}
