package com.ruanzhu.doorhandle.module.detection.security;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import java.util.Map;

@Component
public class DetectionTaskAccessPolicy {

    public boolean isAdmin(Authentication authentication) {
        return authenticated(authentication) && authentication.getAuthorities().stream()
                .anyMatch(a -> "ROLE_SUPERVISOR".equals(a.getAuthority()) || "ROLE_ADMIN".equals(a.getAuthority()));
    }

    public void assertCanAccess(DetectionTask task, Authentication authentication) {
        assertAuthenticated(authentication);
        if (!canAccess(task, authentication.getName(), isAdmin(authentication))) {
            throw new AccessDeniedException("任务不存在或无访问权限");
        }
    }

    public void assertAuthenticated(Authentication authentication) {
        if (!authenticated(authentication)) {
            throw new BusinessException(401, "请先登录");
        }
    }

    private boolean authenticated(Authentication authentication) {
        return authentication != null && authentication.isAuthenticated()
                && !(authentication instanceof AnonymousAuthenticationToken)
                && StringUtils.hasText(authentication.getName());
    }

    public boolean canAccess(DetectionTask task, String username, boolean supervisor) {
        return task != null && StringUtils.hasText(username)
                && (supervisor || username.equals(task.getCreatedBy()) || username.equals(task.getAssignee()));
    }

    /** 在分页、计数和图片候选查询之前添加括号，不能在返回后过滤。 */
    public void applyScope(LambdaQueryWrapper<DetectionTask> query, Authentication authentication) {
        assertAuthenticated(authentication);
        if (!isAdmin(authentication)) {
            query.and(q -> q.eq(DetectionTask::getCreatedBy, authentication.getName())
                    .or().eq(DetectionTask::getAssignee, authentication.getName()));
        }
    }

    public void applyScope(QueryWrapper<DetectionTask> query, AgentActor actor) {
        if (actor == null) throw new SecurityException("缺少认证身份");
        if (!actor.supervisor()) {
            query.and(q -> q.eq("created_by", actor.username()).or().eq("assignee", actor.username()));
        }
    }

    /** JDBC 与 MyBatis 使用相同规则；别名只能来自固定服务代码，身份采用绑定参数。 */
    public SqlScope currentSqlScope(String alias) {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        assertAuthenticated(authentication);
        if (alias == null || !alias.matches("(?:[A-Za-z][A-Za-z0-9_]*\\.)?")) {
            throw new IllegalArgumentException("非法 SQL 别名");
        }
        return isAdmin(authentication) ? new SqlScope("1 = 1", Map.of())
                : new SqlScope("(" + alias + "created_by = :scopeUsername OR " + alias
                + "assignee = :scopeUsername)", Map.of("scopeUsername", authentication.getName()));
    }

    public record SqlScope(String predicate, Map<String, Object> parameters) { }
}
