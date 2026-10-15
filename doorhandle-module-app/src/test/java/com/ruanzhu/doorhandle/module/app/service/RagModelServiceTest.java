package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentTextApi;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import java.util.List;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class RagModelServiceTest {
    @Test void unavailableOrFailedModelKeepsLocalRetrievalFunctional() {
        var provider = mock(ObjectProvider.class);
        var service = new RagModelService(provider, new ObjectMapper());
        assertThat(service.rewriteRagQuery("原问题")).isEqualTo("原问题");
        assertThat(service.rerankRagCandidates("问题", List.of("a", "b"), 1)).containsExactly(0);
        var api = mock(AgentTextApi.class); when(provider.getIfAvailable()).thenReturn(api);
        when(api.generate(any(), any())).thenThrow(new IllegalStateException("secret"));
        assertThat(service.rewriteRagQuery("原问题")).isEqualTo("原问题");
        assertThat(service.rerankRagCandidates("问题", List.of("a", "b"), 1)).containsExactly(0);
    }
    @Test void rankingRejectsInvalidDuplicateAndOutOfRangeIndices() {
        var provider = mock(ObjectProvider.class); var api = mock(AgentTextApi.class);
        when(provider.getIfAvailable()).thenReturn(api);
        when(api.generate(any(), any())).thenReturn("{\"indices\":[-1,999,\"1\",1,1,0]}");
        assertThat(new RagModelService(provider, new ObjectMapper()).rerankRagCandidates("问题", List.of("a", "b"), 2)).containsExactly(1, 0);
    }
}
