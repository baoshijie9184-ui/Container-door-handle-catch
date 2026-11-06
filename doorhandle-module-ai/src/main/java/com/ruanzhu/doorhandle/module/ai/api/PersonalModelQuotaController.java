package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.ai.model.PersonalModelQuotaService;
import java.util.List;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/agent/model-quotas")
@ConditionalOnProperty(prefix="app.model-budget",name="enabled",havingValue="true")
public class PersonalModelQuotaController {
    private final PersonalModelQuotaService service;
    public PersonalModelQuotaController(PersonalModelQuotaService service){this.service=service;}
    @ModelAttribute
    public void privateResponse(jakarta.servlet.http.HttpServletResponse response){response.setHeader("Cache-Control","private, no-store");}
    @GetMapping("/mine")
    public Result<List<PersonalModelQuotaService.MineModel>> mine(){return Result.success(service.mine());}
    @GetMapping("/applications")
    public Result<PersonalModelQuotaService.Page> applications(@RequestParam(defaultValue="mine")String scope,
            @RequestParam(required=false)String status,@RequestParam(defaultValue="9223372036854775807")long before,
            @RequestParam(defaultValue="20")int limit){return Result.success(service.applications(scope,status,before,limit));}
    @PostMapping("/applications")
    public Result<PersonalModelQuotaService.Application> apply(@RequestBody PersonalModelQuotaService.Apply request,
            @RequestHeader(value="X-Budget-Action",required=false)String marker){guard(marker);return Result.success(service.apply(request));}
    @PostMapping("/applications/{id}/decision")
    public Result<PersonalModelQuotaService.Application> decide(@PathVariable String id,@RequestBody PersonalModelQuotaService.Decision request,
            @RequestHeader(value="X-Budget-Action",required=false)String marker){guard(marker);return Result.success(service.decide(id,request));}
    @PostMapping("/applications/{id}/cancel")
    public Result<PersonalModelQuotaService.Application> cancel(@PathVariable String id,@RequestBody PersonalModelQuotaService.Cancel request,
            @RequestHeader(value="X-Budget-Action",required=false)String marker){guard(marker);return Result.success(service.cancel(id,request));}
    private static void guard(String marker){if(!"update".equals(marker))throw new BusinessException(400,"缺少额度操作标记");}
}
