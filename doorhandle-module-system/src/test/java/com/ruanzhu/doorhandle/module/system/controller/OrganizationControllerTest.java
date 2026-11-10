package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.module.system.service.*;
import com.ruanzhu.doorhandle.module.system.security.AuthorizationExceptionHandler;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.authorization.method.AuthorizationManagerBeforeMethodInterceptor;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.method.annotation.AuthenticationPrincipalArgumentResolver;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.List;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.assertj.core.api.Assertions.*;

class OrganizationControllerTest {
    @AfterEach void clearAuthentication() { SecurityContextHolder.clearContext(); }

    private static TenantPrincipal authenticate(String role) {
        var principal = new TenantPrincipal(7L, "organization-actor", "",
                List.of(new SimpleGrantedAuthority("ROLE_" + role)));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(principal, null, principal.getAuthorities()));
        return principal;
    }

    private static MockMvc mvc(AccountIdentityService identities, OrganizationDepartmentService departments) {
        var proxy = new ProxyFactory(new OrganizationController(identities, departments));
        proxy.addAdvisor(AuthorizationManagerBeforeMethodInterceptor.preAuthorize());
        // standaloneSetup does not install Spring Security's MVC resolver or method security.
        return MockMvcBuilders.standaloneSetup(proxy.getProxy())
                .setCustomArgumentResolvers(new AuthenticationPrincipalArgumentResolver())
                .setControllerAdvice(new OrganizationExceptionHandler(), new AuthorizationExceptionHandler()).build();
    }

    @Test void departmentWireKeepsBigintVersionAndOlderConstructorRemainsUnknown() throws Exception {
        var builder=org.springframework.http.converter.json.Jackson2ObjectMapperBuilder.json();
        new com.ruanzhu.doorhandle.module.system.config.OrganizationJsonConfiguration().organizationIdentityJson().customize(builder);
        var json=builder.build();
        var legacy=new com.ruanzhu.doorhandle.contracts.organization.OrganizationDirectoryApi.DepartmentIdentity(21L,"检测部");
        assertThat(legacy.version()).isNull();assertThat(json.readTree(json.writeValueAsBytes(legacy)).get("version").isNull()).isTrue();
        var current=new com.ruanzhu.doorhandle.contracts.organization.OrganizationDirectoryApi.DepartmentIdentity(21L,"检测部",Long.MAX_VALUE);
        var output=json.readTree(json.writeValueAsBytes(current));
        assertThat(output.path("version").isTextual()).isTrue();assertThat(output.path("version").textValue()).isEqualTo(Long.toString(Long.MAX_VALUE));
        assertThat(current.version()).isEqualTo(Long.MAX_VALUE);
    }
    @Test void missingOrWrongOperationHeaderIs400AndNeverCallsBindingService() throws Exception {
        var identities = mock(AccountIdentityService.class);
        var departments = mock(OrganizationDepartmentService.class);
        var mvc = mvc(identities, departments);
        authenticate("SUPERVISOR");
        mvc.perform(put("/api/organization/accounts/1/employee").contentType(MediaType.APPLICATION_JSON)
                .content("{\"employeeId\":2,\"version\":0}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value(400));
        mvc.perform(post("/api/organization/departments").header("X-Organization-Action", "wrong")
                .contentType(MediaType.APPLICATION_JSON).content("{\"name\":\"检测部\"}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value(400));
        verifyNoInteractions(identities, departments);
    }

    @Test void validOperationHeaderPassesTheAuthenticatedPrincipalToTheBindingService() throws Exception {
        var identities = mock(AccountIdentityService.class);
        var departments = mock(OrganizationDepartmentService.class);
        var mvc = mvc(identities, departments);
        var principal = authenticate("SUPERVISOR");
        mvc.perform(put("/api/organization/accounts/1/employee").header("X-Organization-Action", "update")
                .contentType(MediaType.APPLICATION_JSON).content("{\"employeeId\":2,\"version\":0}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(200));
        verify(identities).bind(same(principal), eq(1L), eq(2L), eq(0));
        verifyNoMoreInteractions(identities);
        verifyNoInteractions(departments);
    }

    @Test void inspectorIs403BeforeMutationServicesForBothValidAndMissingHeaders() throws Exception {
        var identities = mock(AccountIdentityService.class);
        var departments = mock(OrganizationDepartmentService.class);
        var mvc = mvc(identities, departments);
        authenticate("INSPECTOR");
        mvc.perform(put("/api/organization/accounts/1/employee").header("X-Organization-Action", "update")
                .contentType(MediaType.APPLICATION_JSON).content("{\"employeeId\":2,\"version\":0}"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.code").value(403));
        mvc.perform(post("/api/organization/departments").contentType(MediaType.APPLICATION_JSON)
                .content("{\"name\":\"检测部\"}"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.code").value(403));
        verifyNoInteractions(identities, departments);
    }
}
