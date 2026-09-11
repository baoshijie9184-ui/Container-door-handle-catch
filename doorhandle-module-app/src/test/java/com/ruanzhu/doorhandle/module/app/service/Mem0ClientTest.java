package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.system.security.SensitiveDataSanitizer;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class Mem0ClientTest {
    @Test
    void exposesNoStringScopedMemoryOperations() {
        assertThat(Arrays.stream(Mem0Client.class.getMethods())
                .filter(method -> Set.of("addMemory", "addMemoryAsync", "searchMemories")
                        .contains(method.getName()))
                .filter(method -> method.getParameterCount() > 0)
                .filter(method -> method.getParameterTypes()[0] == String.class))
                .isEmpty();
    }

    @Test
    void buildsNamespacedUserApplicationAndRunScope() {
        Mem0Client client = new Mem0Client(new SensitiveDataSanitizer());

        assertThat(client.buildScope(new TenantContext(42L, "alice"), "sess_abc"))
                .containsEntry("user_id", "doorhandlecatch:user:42")
                .containsEntry("app_id", "doorhandlecatch")
                .containsEntry("run_id", "sess_abc");
    }
}
