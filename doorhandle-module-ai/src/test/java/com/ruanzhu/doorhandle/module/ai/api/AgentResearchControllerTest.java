package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import com.ruanzhu.doorhandle.module.ai.research.*;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;
import java.util.List;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class AgentResearchControllerTest {
    @Test void exhaustedExportReturnsRetryAfterWithoutAnAttachment() throws Exception {
        var exports=mock(ResearchEvidenceExportService.class);
        when(exports.export(any(),eq("owned"),eq(true))).thenThrow(new com.ruanzhu.doorhandle.module.ai.research.ResearchExportRateLimit.Limited(37));
        var mvc=MockMvcBuilders.standaloneSetup(new AgentResearchController(mock(AgentJournal.class),null,exports)).build();
        mvc.perform(post("/api/agent/runs/owned/sources/export").principal(auth()).header("X-Agent-Action","export").contentType("application/json").content("{\"confirmed\":true}"))
                .andExpect(status().isTooManyRequests()).andExpect(header().string("Retry-After","37"))
                .andExpect(header().string("Cache-Control","no-store")).andExpect(header().doesNotExist("Content-Disposition"))
                .andExpect(header().doesNotExist("X-Export-Id"));
    }
    @Test void confirmedExportReturnsAttachmentAndIntegrityHeaders() throws Exception {
        var journal=mock(AgentJournal.class);var evidence=mock(ResearchEvidenceService.class);var exports=mock(ResearchEvidenceExportService.class);
        when(evidence.view(any(),eq("owned"))).thenReturn(new ResearchEvidenceDtos.View("owned",true,List.of(),List.of(),null,false,0,0));
        when(exports.export(any(),eq("owned"),eq(true))).thenReturn(new ResearchEvidenceExportService.Download("00000000-0000-0000-0000-000000000001","a".repeat(64),"{}".getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        var mvc=MockMvcBuilders.standaloneSetup(new AgentResearchController(journal,evidence,exports)).build();
        mvc.perform(get("/api/agent/runs/owned/sources").principal(auth())).andExpect(jsonPath("$.exportEnabled").value(true));
        mvc.perform(post("/api/agent/runs/owned/sources/export").principal(auth()).header("X-Agent-Action","export").contentType("application/json").content("{\"confirmed\":true}"))
                .andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store")).andExpect(header().string("X-Content-Type-Options","nosniff"))
                .andExpect(header().string("X-Content-SHA256","a".repeat(64))).andExpect(header().string("Content-Disposition","attachment; filename=\"research-00000000-0000-0000-0000-000000000001.json\""))
                .andExpect(content().json("{}"));
        verify(exports).export(argThat(actor->actor.userId()==1),eq("owned"),eq(true));
    }
    @Test void exportRejectsMissingOrFalseConfirmationAndClientProvidedSources() throws Exception {
        var journal=mock(AgentJournal.class);var exports=mock(ResearchEvidenceExportService.class);
        var mvc=MockMvcBuilders.standaloneSetup(new AgentResearchController(journal,null,exports)).build();
        for(String input:List.of("{}","{\"confirmed\":false}","{\"confirmed\":\"true\"}","{\"confirmed\":true,\"userId\":2}","{\"confirmed\":true,\"sources\":[]}"))
            mvc.perform(post("/api/agent/runs/owned/sources/export").principal(auth()).header("X-Agent-Action","export").contentType("application/json").content(input)).andExpect(status().isBadRequest());
        verifyNoInteractions(exports);
    }
    @Test void exportRejectsCrossSiteAndMissingActionHeader() throws Exception {
        var exports=mock(ResearchEvidenceExportService.class);var mvc=MockMvcBuilders.standaloneSetup(new AgentResearchController(mock(AgentJournal.class),null,exports)).build();
        mvc.perform(post("/api/agent/runs/owned/sources/export").principal(auth()).contentType("application/json").content("{\"confirmed\":true}")).andExpect(status().isForbidden());
        mvc.perform(post("/api/agent/runs/owned/sources/export").principal(auth()).header("X-Agent-Action","export").header("Sec-Fetch-Site","cross-site").contentType("application/json").content("{\"confirmed\":true}")).andExpect(status().isForbidden());
        verifyNoInteractions(exports);
    }
    @Test void disabledExportStillChecksRunOwnership() throws Exception {
        var journal=mock(AgentJournal.class);when(journal.get(any(),eq("foreign"))).thenThrow(new ResponseStatusException(HttpStatus.NOT_FOUND,"运行不存在或无访问权限"));
        var mvc=MockMvcBuilders.standaloneSetup(new AgentResearchController(journal,null)).build();
        mvc.perform(post("/api/agent/runs/foreign/sources/export").principal(auth()).header("X-Agent-Action","export").contentType("application/json").content("{\"confirmed\":true}")).andExpect(status().isNotFound());
        mvc.perform(post("/api/agent/runs/owned/sources/export").principal(auth()).header("X-Agent-Action","export").contentType("application/json").content("{\"confirmed\":true}")).andExpect(status().isConflict());
    }
    @Test void exportAuditErrorDoesNotDeliverAttachmentOrDatabaseDetails() throws Exception {
        var exports=mock(ResearchEvidenceExportService.class);when(exports.export(any(),anyString(),eq(true))).thenThrow(new org.springframework.dao.DataAccessResourceFailureException("PRIVATE_SQL_EXCERPT"));
        var mvc=MockMvcBuilders.standaloneSetup(new AgentResearchController(mock(AgentJournal.class),null,exports)).build();
        mvc.perform(post("/api/agent/runs/owned/sources/export").principal(auth()).header("X-Agent-Action","export").contentType("application/json").content("{\"confirmed\":true}"))
                .andExpect(status().isServiceUnavailable()).andExpect(header().doesNotExist("Content-Disposition"))
                .andExpect(header().string("Cache-Control","no-store")).andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("PRIVATE_SQL_EXCERPT"))));
    }
    private UsernamePasswordAuthenticationToken auth() {
        var roles=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));
        return new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L,"alice","",roles),null,roles);
    }
    @Test void disabledCollectionStillChecksOwnershipAndReturnsNoStore() throws Exception {
        var journal=mock(AgentJournal.class);
        var mvc=MockMvcBuilders.standaloneSetup(new AgentResearchController(journal,null)).build();
        mvc.perform(get("/api/agent/runs/owned/sources").principal(auth())).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"))
                .andExpect(jsonPath("$.runId").value("owned")).andExpect(jsonPath("$.enabled").value(false)).andExpect(jsonPath("$.sources").isEmpty());
        verify(journal).get(any(),eq("owned"));
    }
    @Test void otherUsersRunCannotReachTheSourceService() throws Exception {
        var journal=mock(AgentJournal.class);var evidence=mock(ResearchEvidenceService.class);
        when(journal.get(any(),eq("foreign"))).thenThrow(new ResponseStatusException(HttpStatus.NOT_FOUND,"运行不存在或无访问权限"));
        var mvc=MockMvcBuilders.standaloneSetup(new AgentResearchController(journal,evidence)).build();
        mvc.perform(get("/api/agent/runs/foreign/sources").principal(auth())).andExpect(status().isNotFound()).andExpect(header().string("Cache-Control","no-store"));
        verifyNoInteractions(evidence);
    }
    @Test void databaseErrorsDoNotExposeQueriesOrPrivateContents() throws Exception {
        var journal=mock(AgentJournal.class);var evidence=mock(ResearchEvidenceService.class);
        when(evidence.view(any(),eq("owned"))).thenThrow(new org.springframework.dao.DataAccessResourceFailureException("PRIVATE_SQL_PASSWORD"));
        var mvc=MockMvcBuilders.standaloneSetup(new AgentResearchController(journal,evidence)).build();
        mvc.perform(get("/api/agent/runs/owned/sources").principal(auth())).andExpect(status().isServiceUnavailable()).andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("PRIVATE_SQL_PASSWORD"))));
    }
}
