package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.module.system.service.*;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.assertj.core.api.Assertions.*;

class OrganizationControllerTest {
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
        var mvc = MockMvcBuilders.standaloneSetup(new OrganizationController(identities, departments))
                .setControllerAdvice(new OrganizationExceptionHandler()).build();
        mvc.perform(put("/api/organization/accounts/1/employee").contentType(MediaType.APPLICATION_JSON)
                .content("{\"employeeId\":2,\"version\":0}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value(400));
        mvc.perform(post("/api/organization/departments").header("X-Organization-Action", "wrong")
                .contentType(MediaType.APPLICATION_JSON).content("{\"name\":\"检测部\"}"))
                .andExpect(status().isBadRequest());
        verifyNoInteractions(identities, departments);
    }
}
