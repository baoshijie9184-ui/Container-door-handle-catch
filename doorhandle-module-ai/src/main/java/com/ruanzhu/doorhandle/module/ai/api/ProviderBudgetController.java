package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.ai.model.ProviderBudgetService;
import java.util.List;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/agent/provider-budgets")
@ConditionalOnProperty(prefix="app.model-budget",name="provider-limits",havingValue="true")
public class ProviderBudgetController {
    private final ProviderBudgetService budgets;
    public ProviderBudgetController(ProviderBudgetService budgets){this.budgets=budgets;}
    @ModelAttribute
    public void privateResponse(jakarta.servlet.http.HttpServletResponse response){response.setHeader("Cache-Control","private, no-store");}
    @GetMapping
    public Result<ProviderBudgetService.View> view(@RequestParam(required=false)Long employeeId,
            @RequestParam(defaultValue="9223372036854775807")long before,@RequestParam(defaultValue="false")boolean pending) {
        return Result.success(budgets.view(employeeId,before,pending));
    }
    @GetMapping("/employees")
    public Result<List<ProviderBudgetService.Employee>> employees(@RequestParam(defaultValue="")String query,
            @RequestParam(defaultValue="0")long after) {return Result.success(budgets.employees(query,after));}
    @PostMapping("/attempts/{attempt}/review")
    public Result<Void> review(@PathVariable long attempt,@RequestBody ProviderBudgetService.Review review,
            @RequestHeader(value="X-Budget-Action",required=false)String marker) {
        if(!"update".equals(marker))throw new BusinessException(400,"缺少额度操作标记");
        budgets.review(attempt,review);return Result.success(null);
    }
    @PutMapping
    public Result<Void> configure(@RequestBody ProviderBudgetService.Policy policy,
            @RequestHeader(value="X-Budget-Action",required=false)String marker) {
        if(!"update".equals(marker))throw new BusinessException(400,"缺少额度操作标记");
        budgets.configure(policy);
        return Result.success(null);
    }
}
