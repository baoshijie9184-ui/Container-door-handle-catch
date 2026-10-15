package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.evolution.*;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.List;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class SkillEvolutionControllerTest {
    final SkillEvolutionService service=mock(SkillEvolutionService.class);
    final org.springframework.test.web.servlet.MockMvc mvc=MockMvcBuilders.standaloneSetup(new SkillEvolutionController(service)).build();
    final List<SimpleGrantedAuthority> roles=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));
    final UsernamePasswordAuthenticationToken auth=new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L,"alice","",roles),null,roles);
    @Test void missingExplicitActionHeaderAndInvalidReviewCannotExecuteMutations()throws Exception {
        mvc.perform(post("/api/agent/skills/sources/source/consent").principal(auth)).andExpect(status().isBadRequest());
        mvc.perform(post("/api/agent/skills/skill-test/decision").principal(auth).header("X-Skill-Action","update").contentType("application/json").content("{\"expectedRevision\":1,\"decision\":\"APPROVE\",\"reason\":\"审核\",\"businessReviewed\":false,\"privacyReviewed\":false}"))
                .andExpect(status().isBadRequest());verifyNoInteractions(service);
    }
    @Test void historyDisablesCachingAndAnonymousCannotReadSources()throws Exception {
        when(service.sources(any())).thenReturn(List.of());mvc.perform(get("/api/agent/skills/sources").principal(auth)).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"));
        mvc.perform(get("/api/agent/skills/sources")).andExpect(status().isForbidden());verify(service,times(1)).sources(any());
    }
    @Test void removedUploadAndToolMappingRoutesCannotCreateImports()throws Exception {
        var file=new org.springframework.mock.web.MockMultipartFile("file","skill.zip","application/zip",new byte[]{'P','K',3,4});
        mvc.perform(multipart("/api/agent/skills/imports").file(file).principal(auth).header("X-Skill-Action","update")).andExpect(status().isGone());
        mvc.perform(get("/api/agent/skills/imports").principal(auth)).andExpect(status().isGone());
        mvc.perform(get("/api/agent/skills/imports/tool-options").principal(auth)).andExpect(status().isGone());
        mvc.perform(get("/api/agent/skills/imports")).andExpect(status().isForbidden());
        verifyNoInteractions(service);
    }
    @Test void externalSourceCannotBypassRemovalThroughOrdinaryDraftEndpoint()throws Exception {
        var payload=java.util.Map.of("name","task-guide","targetRole","INSPECTOR","description","查询任务时使用的步骤","instructions","先核对当前用户有权查看的检测任务编号 再使用任务查询工具展示处理进度 无数据依据时明确说明 保留业务审核流程","tools",List.of("get_task_detail"),"sourceRunId","source-1","requestId","removed-upload-request","sourceImportId","import-00000000-0000-0000-0000-000000000000");
        mvc.perform(post("/api/agent/skills").principal(auth).header("X-Skill-Action","update").contentType("application/json").content(new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(payload))).andExpect(status().isBadRequest());
        verifyNoInteractions(service);
    }
}
