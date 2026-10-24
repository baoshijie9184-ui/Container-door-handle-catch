package com.ruanzhu.doorhandle.module.detection.security;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessPrincipal;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import java.util.Map;

@Component
public class DetectionTaskAccessPolicy {
    private com.ruanzhu.doorhandle.module.detection.service.DetectionIdentityService identities;
    private BusinessUserDirectory users;
    @org.springframework.beans.factory.annotation.Autowired
    public void setUsers(BusinessUserDirectory value){users=value;}
    @org.springframework.beans.factory.annotation.Autowired(required=false)
    public void setIdentities(com.ruanzhu.doorhandle.module.detection.service.DetectionIdentityService value){identities=value;}
    public boolean stableIdentityActive(){return identities!=null&&identities.active();}
    public String actorPredicate(String alias,String parameter){if(!alias.matches("(?:[A-Za-z][A-Za-z0-9_]*\\.)?"))throw new IllegalArgumentException("非法别名");return stableIdentityActive()?identities.predicate(alias,parameter):"("+alias+"created_by="+parameter+" OR "+alias+"assignee="+parameter+")";}

    public boolean isAdmin(Authentication authentication) {
        if((users!=null||identities!=null)&&authenticated(authentication))return current(authentication).supervisor();
        return authenticated(authentication) && authentication.getAuthorities().stream()
                .anyMatch(a -> "ROLE_SUPERVISOR".equals(a.getAuthority()) || "ROLE_ADMIN".equals(a.getAuthority()));
    }

    public void assertCanAccess(DetectionTask task, Authentication authentication) {
        assertAuthenticated(authentication);
        if (!canAccess(task, authentication)) {
            throw new AccessDeniedException("任务不存在或无访问权限");
        }
    }

    public void assertAuthenticated(Authentication authentication) {
        if (!authenticated(authentication)) {
            throw new BusinessException(401, "请先登录");
        }
        if(users!=null||identities!=null)current(authentication);
    }
    private com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity current(Authentication authentication){
        if(!(authentication.getPrincipal() instanceof BusinessPrincipal principal)||principal.userId()==null)throw new AccessDeniedException("账号稳定身份不可用");
        return users!=null?users.current(principal.userId(),principal.username()):identities.current(principal.userId(),principal.username());
    }

    private boolean authenticated(Authentication authentication) {
        return authentication != null && authentication.isAuthenticated()
                && !(authentication instanceof AnonymousAuthenticationToken)
                && StringUtils.hasText(authentication.getName());
    }

    public boolean canAccess(DetectionTask task,Authentication authentication) {
        assertAuthenticated(authentication);
        if(task==null)return false;
        if(users!=null||identities!=null){
            var actor=current(authentication);
            if(stableIdentityActive())return actor.supervisor()||identities.canAccess(task.getTaskId(),actor.userId());
            return legacy(task,actor.username(),actor.supervisor());
        }
        return legacy(task,authentication.getName(),isAdmin(authentication));
    }
    public boolean canAccess(DetectionTask task,AgentActor actor) {
        if(actor==null)throw new SecurityException("缺少认证身份");
        if(task==null)return false;
        var fresh=current(actor);
        if(stableIdentityActive())return fresh.supervisor()||identities.canAccess(task.getTaskId(),fresh.userId());
        return legacy(task,fresh.username(),fresh.supervisor());
    }
    /** Legacy source signature; caller-supplied names and role flags no longer establish identity. */
    @Deprecated public boolean canAccess(DetectionTask task,String username,boolean supervisor) {
        var authentication=SecurityContextHolder.getContext().getAuthentication();
        assertAuthenticated(authentication);
        if(!java.util.Objects.equals(username,authentication.getName()))throw new AccessDeniedException("缺少原账号的稳定身份");
        return canAccess(task,authentication);
    }
    private BusinessUserDirectory.Identity current(AgentActor actor){
        if(users!=null)return users.current(actor.userId(),actor.username());
        if(identities!=null)return identities.current(actor.userId(),actor.username());
        return new BusinessUserDirectory.Identity(actor.userId(),actor.username(),actor.supervisor());
    }
    private boolean legacy(DetectionTask task,String username,boolean supervisor){
        return task!=null && StringUtils.hasText(username) && (supervisor||username.equals(task.getCreatedBy())||username.equals(task.getAssignee()));
    }

    /** 在分页、计数和图片候选查询之前添加括号，不能在返回后过滤。 */
    public void applyScope(LambdaQueryWrapper<DetectionTask> query, Authentication authentication) {
        assertAuthenticated(authentication);
        if (!isAdmin(authentication)) {
            if(stableIdentityActive()){query.apply(identities.predicate("","{0}"),current(authentication).userId());return;}
            query.and(q -> q.eq(DetectionTask::getCreatedBy, authentication.getName())
                    .or().eq(DetectionTask::getAssignee, authentication.getName()));
        }
    }

    public void applyScope(QueryWrapper<DetectionTask> query, AgentActor actor) {
        if (actor == null) throw new SecurityException("缺少认证身份");
        var fresh=current(actor);
        if (!fresh.supervisor()) {
            if(stableIdentityActive()){query.apply(identities.predicate("","{0}"),fresh.userId());return;}
            query.and(q -> q.eq("created_by", fresh.username()).or().eq("assignee", fresh.username()));
        }
    }

    /** JDBC 与 MyBatis 使用相同规则；别名只能来自固定服务代码，身份采用绑定参数。 */
    public SqlScope currentSqlScope(String alias) {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        assertAuthenticated(authentication);
        if (alias == null || !alias.matches("(?:[A-Za-z][A-Za-z0-9_]*\\.)?")) {
            throw new IllegalArgumentException("非法 SQL 别名");
        }
        var fresh=users!=null||identities!=null?current(authentication):null;
        boolean supervisor=fresh!=null?fresh.supervisor():isAdmin(authentication);
        if(!supervisor&&stableIdentityActive())return new SqlScope(identities.predicate(alias,":scopeUserId"),Map.of("scopeUserId",fresh.userId()));
        return supervisor ? new SqlScope("1 = 1", Map.of())
                : new SqlScope("(" + alias + "created_by = :scopeUsername OR " + alias
                + "assignee = :scopeUsername)", Map.of("scopeUsername", authentication.getName()));
    }

    public record SqlScope(String predicate, Map<String, Object> parameters) { }
}
