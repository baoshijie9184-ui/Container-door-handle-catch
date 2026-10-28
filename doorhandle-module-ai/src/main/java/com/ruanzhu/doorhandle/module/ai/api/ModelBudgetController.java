package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.ai.model.ModelBudgetService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/api/agent/model-budgets")
@ConditionalOnProperty(prefix="app.model-budget",name="enabled",havingValue="true")
public class ModelBudgetController {
    private final ModelBudgetService service;
    public ModelBudgetController(ModelBudgetService service){this.service=service;}
    @GetMapping public Result<List<Map<String,Object>>> overview(){return Result.success(service.overview());}
    @PutMapping public Result<Void> policy(@RequestBody ModelBudgetService.Policy request,@RequestHeader(value="X-Budget-Action",required=false)String marker){guard(marker);service.policy(request);return Result.success(null);}
    @PostMapping("/observations") public Result<Void> observe(@RequestBody ModelBudgetService.Observation request,@RequestHeader(value="X-Budget-Action",required=false)String marker){guard(marker);service.observe(request);return Result.success(null);}
    @GetMapping("/observations") public Result<List<Map<String,Object>>> observations(@RequestParam String modelId){return Result.success(service.observations(modelId));}
    private static void guard(String marker){if(!"update".equals(marker))throw new BusinessException(400,"缺少额度操作标记");}
}
