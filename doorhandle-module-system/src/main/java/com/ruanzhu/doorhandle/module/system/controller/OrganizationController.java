package com.ruanzhu.doorhandle.module.system.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ruanzhu.doorhandle.common.*;
import com.ruanzhu.doorhandle.contracts.organization.OrganizationDirectoryApi.DepartmentIdentity;
import com.ruanzhu.doorhandle.module.system.dto.AccountIdentity;
import com.ruanzhu.doorhandle.module.system.entity.OrganizationBindingAudit;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.module.system.service.*;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/organization")
public class OrganizationController {
    public record BindRequest(@Positive Long employeeId, @NotNull @Min(0) Integer version) {}
    public record DepartmentRequest(@NotBlank @Size(max = 100) String name) {}
    private final AccountIdentityService identities;
    private final OrganizationDepartmentService departments;
    public OrganizationController(AccountIdentityService identities, OrganizationDepartmentService departments) {
        this.identities = identities; this.departments = departments;
    }
    @GetMapping("/me")
    public Result<AccountIdentity> mine(@AuthenticationPrincipal TenantPrincipal principal) { return Result.success(identities.mine(principal)); }
    @GetMapping("/departments")
    public Result<List<DepartmentIdentity>> departments() { return Result.success(departments.list()); }
    @PostMapping("/departments")
    @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<DepartmentIdentity> create(@AuthenticationPrincipal TenantPrincipal principal,
            @RequestHeader(value="X-Organization-Action", required=false) String header, @Valid @RequestBody DepartmentRequest request) {
        guard(header); identities.assertSupervisor(principal); return Result.success(departments.create(request.name()));
    }
    @GetMapping("/accounts")
    @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<Page<AccountIdentity>> accounts(@AuthenticationPrincipal TenantPrincipal principal,
            @RequestParam(defaultValue="1") int page, @RequestParam(defaultValue="20") int size,
            @RequestParam(required=false) String keyword) { return Result.success(identities.list(principal, page, size, keyword)); }
    @PutMapping("/accounts/{userId}/employee")
    @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<AccountIdentity> bind(@AuthenticationPrincipal TenantPrincipal principal, @PathVariable Long userId,
            @RequestHeader(value="X-Organization-Action", required=false) String header, @Valid @RequestBody BindRequest request) {
        guard(header); return Result.success(identities.bind(principal, userId, request.employeeId(), request.version()));
    }
    @GetMapping("/accounts/{userId}/audit")
    @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<List<OrganizationBindingAudit>> audit(@AuthenticationPrincipal TenantPrincipal principal, @PathVariable Long userId) {
        return Result.success(identities.audit(principal, userId));
    }
    private static void guard(String header) {
        if (!"update".equals(header)) throw new BusinessException(400, "缺少组织操作请求标记");
    }
}
