package com.ruanzhu.doorhandle.module.system.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi;
import com.ruanzhu.doorhandle.module.system.dto.AccountIdentity;
import com.ruanzhu.doorhandle.module.system.entity.*;
import com.ruanzhu.doorhandle.module.system.mapper.*;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;
import java.util.*;
import java.util.function.Function;
import java.util.stream.Collectors;

/** 系统模块拥有账号关联；员工事实通过跨模块门面实时读取，不缓存权限身份。 */
@Service
public class AccountIdentityService {
    private final UserMapper users;
    private final AccountEmployeeBindingMapper bindings;
    private final OrganizationBindingAuditMapper audits;
    private final EmployeeDirectoryApi employees;
    public AccountIdentityService(UserMapper users, AccountEmployeeBindingMapper bindings,
            OrganizationBindingAuditMapper audits, EmployeeDirectoryApi employees) {
        this.users = users; this.bindings = bindings; this.audits = audits; this.employees = employees;
    }
    public AccountIdentity mine(TenantPrincipal principal) {
        var user = current(principal, false);
        return identities(List.of(user)).get(0);
    }
    public Page<AccountIdentity> list(TenantPrincipal principal, int page, int size, String keyword) {
        assertSupervisor(principal);
        if (page < 1 || page > 10000 || size < 1 || size > 100 || (keyword != null && keyword.length() > 50))
            throw new BusinessException(400, "分页或查询参数不正确");
        var query = new LambdaQueryWrapper<User>().select(User::getId, User::getUsername, User::getRole)
                .orderByAsc(User::getId);
        if (keyword != null && !keyword.isBlank()) query.like(User::getUsername, keyword.trim());
        var result = users.selectPage(new Page<>(page, size), query);
        var response = new Page<AccountIdentity>(page, size, result.getTotal());
        response.setRecords(identities(result.getRecords()));
        return response;
    }
    public List<OrganizationBindingAudit> audit(TenantPrincipal principal, Long userId) {
        assertSupervisor(principal);
        return audits.selectList(new LambdaQueryWrapper<OrganizationBindingAudit>()
                .eq(OrganizationBindingAudit::getUserId, userId).orderByDesc(OrganizationBindingAudit::getId).last("LIMIT 50"));
    }
    @Transactional(rollbackFor = Exception.class)
    public AccountIdentity bind(TenantPrincipal principal, Long userId, Long employeeId, Integer expectedVersion) {
        assertSupervisor(principal);
        if (userId == null || userId < 1 || (employeeId != null && employeeId < 1) || expectedVersion == null || expectedVersion < 0)
            throw new BusinessException(400, "账号、员工及版本参数不正确");
        // 按账号串行化首次插入和解除后的重新绑定，版本不随解除而丢失。
        var user = users.selectOne(new LambdaQueryWrapper<User>().eq(User::getId, userId).last("FOR UPDATE"));
        if (user == null) throw new BusinessException(404, "账号不存在");
        var binding = bindings.selectById(userId);
        int version = binding == null ? 0 : binding.getVersion();
        if (version != expectedVersion) throw new BusinessException(409, "账号关联已更新，请刷新后重试");
        Long before = binding == null ? null : binding.getEmployeeId();
        if (employeeId != null) {
            var employee = employees.lock(employeeId);
            if (!"ACTIVE".equals(employee.status())) throw new BusinessException(409, "只能关联在岗员工");
            if (employee.departmentId() == null) throw new BusinessException(409, "请先完善员工所属部门");
            if (bindings.selectCount(new LambdaQueryWrapper<AccountEmployeeBinding>()
                    .eq(AccountEmployeeBinding::getEmployeeId, employeeId).ne(AccountEmployeeBinding::getUserId, userId)) > 0)
                throw new BusinessException(409, "该员工已关联其他账号");
        }
        if (Objects.equals(before, employeeId)) return identities(List.of(user)).get(0);
        if (binding == null) {
            binding = new AccountEmployeeBinding(); binding.setUserId(userId);
            binding.setEmployeeId(employeeId); binding.setVersion(1); bindings.insert(binding);
        } else {
            binding.setEmployeeId(employeeId); binding.setVersion(version + 1);
            if (bindings.updateById(binding) != 1) throw new BusinessException(409, "账号关联更新失败");
        }
        var audit = new OrganizationBindingAudit(); audit.setUserId(userId); audit.setUsername(user.getUsername());
        audit.setActorUserId(principal.userId()); audit.setActorUsername(principal.username());
        audit.setBeforeEmployeeId(before); audit.setAfterEmployeeId(employeeId);
        audit.setBindingVersion(binding.getVersion()); audit.setAction(employeeId == null ? "UNBIND" : before == null ? "BIND" : "REBIND");
        audit.setCreatedAt(LocalDateTime.now());
        if (audits.insert(audit) != 1) throw new IllegalStateException("账号关联审计写入失败");
        return identities(List.of(user)).get(0);
    }
    public void assertSupervisor(TenantPrincipal principal) { current(principal, true); }
    private User current(TenantPrincipal principal, boolean supervisor) {
        if (principal == null) throw new AccessDeniedException("未登录");
        var user = users.selectById(principal.userId());
        if (user == null || !principal.username().equals(user.getUsername()) || (supervisor && !isSupervisor(user.getRole())))
            throw new AccessDeniedException("当前账号没有组织管理权限");
        return user;
    }
    private List<AccountIdentity> identities(List<User> accounts) {
        if (accounts.isEmpty()) return List.of();
        var links = bindings.selectBatchIds(accounts.stream().map(User::getId).toList()).stream()
                .collect(Collectors.toMap(AccountEmployeeBinding::getUserId, Function.identity()));
        var staff = employees.findAll(links.values().stream().map(AccountEmployeeBinding::getEmployeeId)
                .filter(Objects::nonNull).distinct().toList()).stream().collect(Collectors.toMap(EmployeeDirectoryApi.EmployeeIdentity::id, Function.identity()));
        return accounts.stream().map(u -> {
            var link = links.get(u.getId()); var e = link == null ? null : staff.get(link.getEmployeeId());
            return new AccountIdentity(u.getId(), u.getUsername(), isSupervisor(u.getRole()) ? "SUPERVISOR" : "INSPECTOR",
                    e == null ? null : e.id(), e == null ? null : e.employeeNumber(), e == null ? null : e.name(),
                    e == null ? null : e.status(), e == null ? null : e.employeeType(), e == null ? null : e.departmentId(),
                    e == null ? null : e.departmentName(), link == null ? 0 : link.getVersion(),
                    isSupervisor(u.getRole()) ? "SINGLE_ENTERPRISE" : "OWNED_OR_ASSIGNED");
        }).toList();
    }
    private static boolean isSupervisor(String role) { return "SUPERVISOR".equalsIgnoreCase(role) || "ADMIN".equalsIgnoreCase(role); }
}
