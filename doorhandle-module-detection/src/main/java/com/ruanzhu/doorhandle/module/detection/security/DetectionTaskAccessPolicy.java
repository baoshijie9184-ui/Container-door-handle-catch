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
    @org.springframework.beans.factory.annotation.Value("${collaboration.mutations.enabled:false}") private boolean candidateReadsEnabled;
    @org.springframework.beans.factory.annotation.Autowired
    public void setUsers(BusinessUserDirectory value){users=value;}
    @org.springframework.beans.factory.annotation.Autowired(required=false)
    public void setIdentities(com.ruanzhu.doorhandle.module.detection.service.DetectionIdentityService value){identities=value;}
    @org.springframework.beans.factory.annotation.Autowired(required=false)
    private org.springframework.jdbc.core.JdbcTemplate folderAssignments;
    private static final String FOLDER_READER = "EXISTS (SELECT 1 FROM detection_work_unit w WHERE w.work_unit_id=detection_task.task_id COLLATE utf8mb4_0900_ai_ci AND w.strategy='OSS_FOLDER' AND w.assignee_user_id=CAST({0} AS CHAR))";
    private boolean assignedFolder(DetectionTask task,long user) {
        return task!=null && "OSS_FOLDER".equals(task.getTaskType()) && folderAssignments!=null &&
            Boolean.TRUE.equals(folderAssignments.queryForObject("SELECT EXISTS(SELECT 1 FROM detection_work_unit WHERE work_unit_id=? AND strategy='OSS_FOLDER' AND assignee_user_id=?)",
            Boolean.class,task.getTaskId(),Long.toString(user)));
    }
    public boolean stableIdentityActive(){return identities!=null&&identities.active();}
    public String actorPredicate(String alias,String parameter){if(!alias.matches("(?:[A-Za-z][A-Za-z0-9_]*\\.)?"))throw new IllegalArgumentException("非法别名");return stableIdentityActive()?identities.predicate(alias,parameter):"("+alias+"created_by="+parameter+" OR "+alias+"assignee="+parameter+")";}
    public String actorPredicate(String alias,String parameter,String candidateParameter){
        String owned=actorPredicate(alias,parameter);
        return candidateReadsEnabled?"("+owned+" OR "+DetectionClaimCandidates.predicate(alias,candidateParameter)+")":owned;
    }

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
        if(canMutate(task,authentication))return true;
        if(users!=null && assignedFolder(task,current(authentication).userId()))return true;
        return candidateReadsEnabled && task!=null && (users!=null||identities!=null)
                && DetectionClaimCandidates.includes(task,current(authentication).userId());
    }
    /** Candidate visibility never establishes permission to review, retry or edit a task. */
    public boolean canMutate(DetectionTask task,Authentication authentication) {
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
        if(canMutate(task,actor))return true;
        return candidateReadsEnabled && task!=null && DetectionClaimCandidates.includes(task,current(actor).userId());
    }
    public boolean canMutate(DetectionTask task,AgentActor actor) {
        if(actor==null)throw new SecurityException("缺少认证身份");
        if(task==null)return false;
        var fresh=current(actor);
        if(stableIdentityActive())return fresh.supervisor()||identities.canAccess(task.getTaskId(),fresh.userId());
        return legacy(task,fresh.username(),fresh.supervisor());
    }
    public void assertCanMutate(DetectionTask task,Authentication authentication) {
        if(!canMutate(task,authentication))throw new AccessDeniedException("领取任务后才可修改任务");
    }
    public void assertCanMutate(DetectionTask task,AgentActor actor) {
        if(!canMutate(task,actor))throw new SecurityException("领取任务后才可修改任务");
    }
    public boolean readOnlyCandidate(DetectionTask task){
        if(task==null || (!"OSS_FOLDER".equals(task.getTaskType()) && (!candidateReadsEnabled||task.getClaimCandidateIds()==null)))return false;
        var authentication=SecurityContextHolder.getContext().getAuthentication();
        return canAccess(task,authentication)&&!canMutate(task,authentication);
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
            if(stableIdentityActive()){
                var id=current(authentication).userId();
                query.and(q->{q.apply(actorPredicate("","{0}","{0}"),id); if(folderAssignments!=null) q.or().apply(FOLDER_READER,id);});
                return;
            }
            query.and(q -> {q.eq(DetectionTask::getCreatedBy, authentication.getName()).or().eq(DetectionTask::getAssignee, authentication.getName());
                if(folderAssignments!=null && users!=null)q.or().apply(FOLDER_READER,current(authentication).userId());
                if(candidateReadsEnabled&&(users!=null||identities!=null))q.or().apply(DetectionClaimCandidates.predicate("","{0}"),current(authentication).userId());});
        }
    }

    public void applyScope(QueryWrapper<DetectionTask> query, AgentActor actor) {
        applyAgentScope(query, actor, false);
    }

    /** A detector assigned through a folder work unit may read the task without gaining mutation rights. */
    public boolean applyAgentReadScope(QueryWrapper<DetectionTask> query, AgentActor actor) {
        return applyAgentScope(query, actor, folderAssignments != null);
    }

    private boolean applyAgentScope(QueryWrapper<DetectionTask> query, AgentActor actor, boolean includeFolderAssignment) {
        if (actor == null) throw new SecurityException("缺少认证身份");
        var fresh=current(actor);
        if (fresh.supervisor()) return true;
        boolean stableIdentity = stableIdentityActive();
        query.and(scope -> {
            if (stableIdentity) {
                scope.apply(actorPredicate("", "{0}", "{0}"), fresh.userId());
            } else {
                scope.eq("created_by", fresh.username()).or().eq("assignee", fresh.username());
                if (candidateReadsEnabled) scope.or().apply(DetectionClaimCandidates.predicate("", "{0}"), fresh.userId());
            }
            if (includeFolderAssignment) {
                scope.or().apply("(detection_task.task_type = 'OSS_FOLDER' AND " + FOLDER_READER + ")", fresh.userId());
            }
        });
        return false;
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
        if(!supervisor&&stableIdentityActive())return new SqlScope(actorPredicate(alias,":scopeUserId",":scopeUserId"),Map.of("scopeUserId",fresh.userId()));
        if(!supervisor&&candidateReadsEnabled&&fresh!=null)return new SqlScope(actorPredicate(alias,":scopeUsername",":scopeUserId"),Map.of("scopeUsername",fresh.username(),"scopeUserId",fresh.userId()));
        return supervisor ? new SqlScope("1 = 1", Map.of())
                : new SqlScope("(" + alias + "created_by = :scopeUsername OR " + alias
                + "assignee = :scopeUsername)", Map.of("scopeUsername", authentication.getName()));
    }

    public record SqlScope(String predicate, Map<String, Object> parameters) { }
}
