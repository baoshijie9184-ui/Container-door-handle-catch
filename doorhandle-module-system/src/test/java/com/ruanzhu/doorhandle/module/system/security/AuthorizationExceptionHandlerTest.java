package com.ruanzhu.doorhandle.module.system.security;
import com.ruanzhu.doorhandle.common.GlobalExceptionHandler;
import org.junit.jupiter.api.Test;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.web.bind.annotation.*;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.assertj.core.api.Assertions.*;
class AuthorizationExceptionHandlerTest {
    @RestController static class ProtectedController {
        @GetMapping("/protected") String denied(){throw new AccessDeniedException("private-internal-policy");}
    }
    @Test void permissionDenialWinsOverGenericExceptionHandlerAndDoesNotExposeInternals() throws Exception {
        var mvc=MockMvcBuilders.standaloneSetup(new ProtectedController())
                .setControllerAdvice(new GlobalExceptionHandler(),new AuthorizationExceptionHandler()).build();
        var response=mvc.perform(get("/protected")).andExpect(status().isForbidden()).andExpect(jsonPath("$.code").value(403)).andReturn();
        assertThat(response.getResponse().getContentAsString()).doesNotContain("private-internal-policy");
    }
}
