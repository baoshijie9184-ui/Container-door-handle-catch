package com.ruanzhu.doorhandle.module.ai.context;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import java.util.List;
import static org.assertj.core.api.Assertions.*;

class AgentIdentityTest {
    @Test void onlyTrustedPrincipalWithKnownRoleIsAccepted() {
        var authorities = List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));
        var principal = new TenantPrincipal(7L, "alice", "", authorities);
        var auth = new UsernamePasswordAuthenticationToken(principal, null, authorities);
        assertThat(AgentIdentity.from(auth)).isEqualTo(new AgentActor(7, "alice", AgentActor.Role.INSPECTOR));
        assertThatThrownBy(() -> AgentIdentity.from(null)).isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
        assertThatThrownBy(() -> AgentIdentity.from(new UsernamePasswordAuthenticationToken("alice", null, authorities)))
                .isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
    }
}
