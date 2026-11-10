package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.common.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.core.env.MapPropertySource;
import org.springframework.http.ResponseEntity;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class ResultHttpStatusAdviceTest {
    @RestController static class Endpoints {
        @GetMapping("/result") public Result<Void> result(@RequestParam int code){return Result.error(code,"existing result");}
        @GetMapping("/business") public Result<Void> business(){throw new BusinessException(409,"version changed");}
        @GetMapping("/unknown") public Result<Void> unknown(){throw new IllegalStateException("unknown result");}
        @GetMapping("/created") public ResponseEntity<Result<Void>> created(){return ResponseEntity.status(201).body(Result.success());}
        @GetMapping("/map") public Map<String,Object> map(){return Map.of("code",409);}
    }
    @ParameterizedTest @ValueSource(booleans={true,false})
    void onlyTheEnabledFeatureChangesErrorResultTransportStatus(boolean enabled)throws Exception{
        try(var context=new AnnotationConfigApplicationContext()){
            context.getEnvironment().getPropertySources().addFirst(new MapPropertySource("feature",Map.of("collaboration.mutations.enabled",String.valueOf(enabled))));
            context.register(ResultHttpStatusAdvice.class);context.refresh();
            var advices=new ArrayList<Object>();advices.add(new GlobalExceptionHandler());advices.addAll(context.getBeansOfType(ResultHttpStatusAdvice.class).values());
            assertThat(context.getBeansOfType(ResultHttpStatusAdvice.class)).hasSize(enabled?1:0);
            var http=MockMvcBuilders.standaloneSetup(new Endpoints()).setControllerAdvice(advices.toArray()).build();
            for(int code:List.of(400,401,403,409,429,500,503,599))
                http.perform(get("/result").param("code",String.valueOf(code))).andExpect(status().is(enabled?code:200)).andExpect(jsonPath("$.code").value(code));
            http.perform(get("/business")).andExpect(status().is(enabled?409:200)).andExpect(jsonPath("$.code").value(409));
            http.perform(get("/unknown")).andExpect(status().is(enabled?500:200)).andExpect(jsonPath("$.code").value(500));
            for(int code:List.of(200,399,600))http.perform(get("/result").param("code",String.valueOf(code))).andExpect(status().isOk());
            http.perform(get("/created")).andExpect(status().isCreated());http.perform(get("/map")).andExpect(status().isOk());
        }
    }
}
