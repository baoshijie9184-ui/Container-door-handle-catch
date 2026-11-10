package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.module.system.service.AccountAccessService;
import jakarta.validation.Valid;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/accounts")
@PreAuthorize("hasRole('SUPERVISOR')")
public class AccountAccessController {
    private final AccountAccessService accounts;
    public AccountAccessController(AccountAccessService accounts){this.accounts=accounts;}
    @GetMapping("/{userId}/access") public Result<AccountAccessService.View> read(@AuthenticationPrincipal TenantPrincipal actor,@PathVariable long userId){return Result.success(accounts.read(actor,userId));}
    @PostMapping("/{userId}/access") public Result<AccountAccessService.View> change(@AuthenticationPrincipal TenantPrincipal actor,@PathVariable long userId,@Valid @RequestBody AccountAccessService.Change command){return Result.success(accounts.change(actor,userId,command));}
}
