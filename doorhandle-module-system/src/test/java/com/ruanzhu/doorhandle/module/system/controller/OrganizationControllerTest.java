package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.module.system.service.*;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class OrganizationControllerTest {
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
