package com.ruanzhu.doorhandle.module.app.controller;

import com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos;
import com.ruanzhu.doorhandle.module.app.service.*;
import com.ruanzhu.doorhandle.module.system.security.*;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class PersonalMemoryControllerTest {
    @Test void semanticReviewUsesCurrentAccountAndSeparatesReadOnlyStartFromConfirmedDecision()throws Exception{
        var memory=mock(PersonalMemoryService.class);var preferences=mock(MemoryPreferenceService.class);var owner=new TenantContext(42L,"alice");
        var mvc=MockMvcBuilders.standaloneSetup(new PersonalMemoryController(memory,preferences)).build();
        var request=new MemoryDtos.StartReview("review","a".repeat(64),0);
        when(memory.startReview(owner,"mine",request)).thenReturn(new MemoryDtos.Review("review","mine","RUNNING",0,null,false,"PENDING",List.of(),List.of(),null,null,20,null,null,null,null,null,null,"UNKNOWN"));
        String body="{\"requestId\":\"review\",\"expectedDigest\":\""+"a".repeat(64)+"\",\"expectedRevision\":0}";
        mvc.perform(post("/api/agent/memories/mine/reviews").param("ownerUserId","43").principal(auth("ROLE_INSPECTOR")).contentType("application/json").content(body)).andExpect(status().isAccepted()).andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.status").value("RUNNING"));
        verify(memory).startReview(owner,"mine",request);
        mvc.perform(get("/api/agent/memories/reviews/review").principal(auth("ROLE_SUPERVISOR"))).andExpect(status().isOk());verify(memory).getReview(owner,"review");
        mvc.perform(post("/api/agent/memories/reviews/review/resolve").principal(auth("ROLE_INSPECTOR")).contentType("application/json").content("{\"requestId\":\"decision\",\"expectedRevision\":1,\"candidateId\":\"candidate\",\"choice\":\"KEEP_SOURCE\",\"confirmed\":false}")).andExpect(status().isBadRequest());verify(memory,never()).resolveReview(any(),any(),any());
    }
    @Test void lifecycleControlsCannotSelectAnotherAccountAndCleanupVerificationIsExplicit()throws Exception{
        var memory=mock(PersonalMemoryService.class);var preferences=mock(MemoryPreferenceService.class);var owner=new TenantContext(42L,"alice");
        var mvc=MockMvcBuilders.standaloneSetup(new PersonalMemoryController(memory,preferences)).build();
        mvc.perform(get("/api/agent/memories/lifecycle").param("ownerUserId","43").principal(auth("ROLE_SUPERVISOR"))).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"));
        verify(memory).lifecycleHistory(owner);
        mvc.perform(post("/api/agent/memories/mine/cleanup/verify").principal(auth("ROLE_SUPERVISOR"))).andExpect(status().isForbidden());
        mvc.perform(post("/api/agent/memories/mine/cleanup/verify").header("X-Agent-Action","memory-verify").principal(auth("ROLE_SUPERVISOR"))).andExpect(status().isOk());
        verify(memory).verifyCleanup(owner,"mine");
        mvc.perform(post("/api/agent/memories/mine/lifecycle").principal(auth("ROLE_SUPERVISOR")).contentType("application/json").content("{\"requestId\":\"key\",\"expectedDigest\":\""+"a".repeat(64)+"\",\"expectedRevision\":0,\"state\":\"EXCLUDED\",\"confirmed\":false}")).andExpect(status().isBadRequest());
        verify(memory,never()).changeLifecycle(any(),any(),any());
    }
    @Test void operationVerificationUsesThePrincipalAndNeverCallsASaveTool()throws Exception{
        var memory=mock(PersonalMemoryService.class);var preferences=mock(MemoryPreferenceService.class);var owner=new TenantContext(42L,"alice");String id="a".repeat(64);
        when(memory.verifyExtraction(owner,id)).thenReturn(new MemoryDtos.Extraction(id,"RUNNING",null,null));
        var mvc=MockMvcBuilders.standaloneSetup(new PersonalMemoryController(memory,preferences)).build();
        String path="/api/agent/memories/operations/"+id+"/verify";
        mvc.perform(post(path).principal(auth("ROLE_SUPERVISOR"))).andExpect(status().isForbidden());
        mvc.perform(post(path).header("X-Agent-Action","memory-verify")).andExpect(status().isUnauthorized());
        mvc.perform(post(path).param("ownerUserId","43").header("X-Agent-Action","memory-verify").principal(auth("ROLE_SUPERVISOR"))).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.status").value("RUNNING"));
        verify(memory).verifyExtraction(owner,id);verifyNoInteractions(preferences);
    }
    private UsernamePasswordAuthenticationToken auth(String role){var roles=List.of(new SimpleGrantedAuthority(role));return new UsernamePasswordAuthenticationToken(new TenantPrincipal(42L,"alice","",roles),null,roles);}
    @Test void accountIsDerivedFromPrincipalEvenWhenSupervisorSuppliesAnotherOwner()throws Exception{
        var memory=mock(PersonalMemoryService.class);var preferences=mock(MemoryPreferenceService.class);var owner=new TenantContext(42L,"alice");
        when(memory.list(owner,50)).thenReturn(new MemoryDtos.Page(List.of(),false));when(preferences.change(eq(owner),any())).thenReturn(new MemoryDtos.Preference(false,false,1,null));
        var mvc=MockMvcBuilders.standaloneSetup(new PersonalMemoryController(memory,preferences)).build();
        mvc.perform(get("/api/agent/memories").param("ownerUserId","43").principal(auth("ROLE_SUPERVISOR"))).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"));verify(memory).list(owner,50);
        mvc.perform(put("/api/agent/memories/preferences").principal(auth("ROLE_SUPERVISOR")).contentType("application/json").content("{\"expectedRevision\":0,\"readEnabled\":false,\"saveEnabled\":false,\"ownerUserId\":43}" )).andExpect(status().isOk());verify(preferences).change(eq(owner),any());
    }
    @Test void anonymousUnsupportedRoleAndMissingConfirmationCannotAccessStorage()throws Exception{
        var memory=mock(PersonalMemoryService.class);var preferences=mock(MemoryPreferenceService.class);var mvc=MockMvcBuilders.standaloneSetup(new PersonalMemoryController(memory,preferences)).build();
        mvc.perform(get("/api/agent/memories")).andExpect(status().isUnauthorized());mvc.perform(get("/api/agent/memories").principal(auth("ROLE_USER"))).andExpect(status().isForbidden());
        mvc.perform(post("/api/agent/memories/mine/delete").principal(auth("ROLE_INSPECTOR")).contentType("application/json").content("{\"requestId\":\"r1\",\"expectedDigest\":\""+"a".repeat(64)+"\",\"confirmed\":false}" )).andExpect(status().isBadRequest());verifyNoInteractions(memory,preferences);
    }
    @Test void storageFailureIsNotAnEmptySuccessfulList()throws Exception{
        var memory=mock(PersonalMemoryService.class);var preferences=mock(MemoryPreferenceService.class);when(memory.list(any(),anyInt())).thenThrow(new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE,"记忆不可用"));
        MockMvcBuilders.standaloneSetup(new PersonalMemoryController(memory,preferences)).build().perform(get("/api/agent/memories").principal(auth("ROLE_INSPECTOR"))).andExpect(status().isServiceUnavailable());
    }
    @Test void editAndPagingDeriveOwnerFromSessionAndRequireExplicitConfirmation()throws Exception{
        var memory=mock(PersonalMemoryService.class);var preferences=mock(MemoryPreferenceService.class);var owner=new TenantContext(42L,"alice");
        var mvc=MockMvcBuilders.standaloneSetup(new PersonalMemoryController(memory,preferences)).build();
        mvc.perform(get("/api/agent/memories").param("limit","50").param("offset","100").param("ownerUserId","43").principal(auth("ROLE_SUPERVISOR"))).andExpect(status().isOk());verify(memory).list(owner,50,100);
        mvc.perform(get("/api/agent/memories/mine").param("ownerUserId","43").principal(auth("ROLE_SUPERVISOR"))).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"));verify(memory).get(owner,"mine");
        String body="{\"requestId\":\"r1\",\"expectedDigest\":\""+"a".repeat(64)+"\",\"memory\":\"新的偏好\",\"confirmed\":";
        mvc.perform(post("/api/agent/memories/mine/update").principal(auth("ROLE_INSPECTOR")).contentType("application/json").content(body+"false}")).andExpect(status().isBadRequest());verify(memory,never()).update(any(),any(),any());
        mvc.perform(post("/api/agent/memories/mine/update").principal(auth("ROLE_SUPERVISOR")).contentType("application/json").content(body+"true,\"ownerUserId\":43}")).andExpect(status().isOk());verify(memory).update(eq(owner),eq("mine"),any());
        mvc.perform(post("/api/agent/memories/mine/update").contentType("application/json").content(body+"true}")).andExpect(status().isUnauthorized());
    }
}
