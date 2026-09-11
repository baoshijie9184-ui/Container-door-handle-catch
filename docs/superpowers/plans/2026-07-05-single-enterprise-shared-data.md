# Single-Enterprise Shared Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every authenticated user share the same business and chat data with identical system capabilities while preserving creator attribution, authentication, auditability, and safe concurrent updates.

**Architecture:** Keep the existing single MySQL schema and JWT authentication. Replace owner/role authorization with an authenticated-user policy, remove username predicates from shared queries, and add a focused audit module for mutating operations. Preserve creator fields as metadata and add conditional updates where shared writes can conflict.

**Tech Stack:** Java 17, Spring Boot 3.2, Spring Security, MyBatis-Plus, MySQL 8/InnoDB, Vue 3, Pinia, JUnit 5, Mockito, AssertJ, Node test runner.

---

## File map

- Modify `src/main/java/com/ruanzhu/doorhandlecatch/security/DetectionTaskAccessPolicy.java`: authenticated-user task policy.
- Modify detection services under `service/impl` and `service/agent/impl`: remove creator filtering.
- Modify `OssPreviewAuthorizationService.java`: authorize any authenticated user for referenced OSS keys.
- Modify chat service interfaces and implementations: shared lookup semantics while retaining actor identity for creation/audit.
- Create `OperationAuditLog.java`, `OperationAuditLogMapper.java`, `OperationAuditService.java`, and `OperationAuditServiceImpl.java`: isolated audit persistence module.
- Create `migration-V15-single-enterprise-shared-data.sql`: audit schema migration.
- Modify high-risk write controllers/services: call the audit service after successful state changes.
- Modify `GlobalExceptionHandler.java`: map optimistic conflicts to code 409.
- Modify `frontend/src/layout/index.vue` and `frontend/src/views/UserManual.vue`: remove administrator-only wording.
- Add focused Java and Node contract tests for shared access, audit redaction, conflict behavior, and equal UI capabilities.

### Task 1: Establish the authenticated-user access policy

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/security/DetectionTaskAccessPolicy.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/security/DetectionTaskAccessPolicyTest.java`

- [ ] **Step 1: Replace owner/admin expectations with shared authenticated access tests**

Add tests covering an operator accessing another user's task and an anonymous request being denied:

```java
@Test
void authenticatedOperatorCanAccessTaskCreatedByAnotherUser() {
    DetectionTask task = new DetectionTask();
    task.setCreatedBy("alice");
    Authentication bob = new UsernamePasswordAuthenticationToken(
            "bob", null, List.of(new SimpleGrantedAuthority("ROLE_OPERATOR")));

    assertThatCode(() -> policy.assertCanAccess(task, bob)).doesNotThrowAnyException();
}

@Test
void anonymousUserCannotAccessTask() {
    assertThatThrownBy(() -> policy.assertCanAccess(new DetectionTask(), null))
            .isInstanceOf(BusinessException.class)
            .extracting("code").isEqualTo(401);
}
```

- [ ] **Step 2: Run the focused test and verify the cross-user case fails**

Run: `.\mvnw.cmd -q -Dtest=DetectionTaskAccessPolicyTest test`

Expected: FAIL because the current policy rejects `bob` for Alice's task.

- [ ] **Step 3: Implement a policy that checks authentication only**

```java
public void assertCanAccess(DetectionTask task, Authentication authentication) {
    if (authentication == null || !authentication.isAuthenticated()
            || !StringUtils.hasText(authentication.getName())) {
        throw new BusinessException(401, "请先登录");
    }
}

public boolean isAdmin(Authentication authentication) {
    return authentication != null && authentication.isAuthenticated();
}
```

Keep `isAdmin` temporarily as a compatibility shim; mark it deprecated and remove all call sites in Tasks 2–3.

- [ ] **Step 4: Run the focused test**

Run: `.\mvnw.cmd -q -Dtest=DetectionTaskAccessPolicyTest test`

Expected: PASS.

- [ ] **Step 5: Commit the policy change**

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/security/DetectionTaskAccessPolicy.java src/test/java/com/ruanzhu/doorhandlecatch/security/DetectionTaskAccessPolicyTest.java
git commit -m "feat: allow authenticated users to share task access"
```

### Task 2: Share detection queries and task mutations

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceImpl.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ImageDetectionServiceImpl.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/agent/impl/DetectionAgentServiceImpl.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/agent/impl/OpsAgentServiceImpl.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/DetectionRecordController.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceImplTest.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ImageDetectionServiceImplTest.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/agent/impl/DetectionAgentServiceImplTest.java`

- [ ] **Step 1: Add failing tests proving list/detail access is not creator-filtered**

For each service, authenticate as `bob`, return a task created by `alice`, and assert it remains in the result. For `DetectionTaskServiceImpl`, capture the query wrapper and verify it has no `created_by = bob` segment:

```java
@Test
void operatorListsTasksCreatedByAllUsers() {
    authenticate("bob", "ROLE_OPERATOR");
    DetectionTask aliceTask = task("task-alice", "alice");
    when(taskMapper.selectList(any())).thenReturn(List.of(aliceTask));

    List<DetectionTask> result = service.listTasksForCurrentUser();

    assertThat(result).extracting(DetectionTask::getTaskId).containsExactly("task-alice");
    verify(taskMapper).selectList(argThat(wrapper ->
            !wrapper.getTargetSql().contains("created_by")));
}
```

Use the actual public list method name from `DetectionTaskService`; do not add a duplicate API solely for the test.

- [ ] **Step 2: Run the detection service tests and verify failure**

Run: `.\mvnw.cmd -q -Dtest=DetectionTaskServiceImplTest,ImageDetectionServiceImplTest,DetectionAgentServiceImplTest test`

Expected: at least one assertion fails because non-admin queries add `created_by`.

- [ ] **Step 3: Remove creator predicates and admin branches**

Replace patterns like:

```java
if (!accessPolicy.isAdmin(authentication)) {
    wrapper.eq(DetectionTask::getCreatedBy, authentication.getName());
}
```

with:

```java
accessPolicy.assertAuthenticated(authentication);
```

Add `assertAuthenticated(Authentication)` to the policy and use it before shared list queries. Retain `createdBy` assignment when creating a new task.

- [ ] **Step 4: Bound raw detection-record pagination**

In `DetectionRecordController`, reject `page < 1`, `size < 1`, or `size > 100` with `Result.error(400, ...)`, and replace `SELECT *` with the explicit columns consumed by the frontend. Do not add a username predicate.

- [ ] **Step 5: Run focused tests**

Run: `.\mvnw.cmd -q -Dtest=DetectionTaskAccessPolicyTest,DetectionTaskServiceImplTest,ImageDetectionServiceImplTest,DetectionAgentServiceImplTest test`

Expected: PASS.

- [ ] **Step 6: Commit shared detection access**

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/security/DetectionTaskAccessPolicy.java src/main/java/com/ruanzhu/doorhandlecatch/service src/main/java/com/ruanzhu/doorhandlecatch/controller/DetectionRecordController.java src/test/java/com/ruanzhu/doorhandlecatch/service
git commit -m "feat: share detection data across authenticated users"
```

### Task 3: Share referenced OSS and local task resources

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/OssPreviewAuthorizationService.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/OssPreviewAuthorizationServiceTest.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/controller/FileControllerTest.java`

- [ ] **Step 1: Add a cross-user OSS preview test**

```java
@Test
void authenticatedUserCanPreviewKeyReferencedByAnotherUsersTask() {
    DetectionTask task = new DetectionTask();
    task.setCreatedBy("alice");
    task.setPreviewImageKeysJson("[\"detection/task-1/preview/a.jpg\"]");
    when(taskMapper.selectList(any())).thenReturn(List.of(task));
    Authentication bob = authenticated("bob");

    assertThatCode(() -> service.authorize(
            "detection/task-1/preview/a.jpg", bob)).doesNotThrowAnyException();
}
```

Also retain tests rejecting blank keys, non-`detection/` keys, unreferenced keys, and anonymous users.

- [ ] **Step 2: Verify the cross-user test fails**

Run: `.\mvnw.cmd -q -Dtest=OssPreviewAuthorizationServiceTest test`

Expected: FAIL because the query and in-memory filter require matching `createdBy`.

- [ ] **Step 3: Remove ownership filtering while retaining reference validation**

Build the query only from the three key-reference columns, call `accessPolicy.assertAuthenticated(authentication)` first, parse JSON for exact key membership, and delete `canAccess(...)`.

- [ ] **Step 4: Verify local file endpoints still require authentication and safe paths**

Add MVC tests asserting unauthenticated access returns `401`, authenticated access reaches the controller, and `..` path segments are rejected. Do not weaken `SafePathResolver`.

- [ ] **Step 5: Run tests and commit**

Run: `.\mvnw.cmd -q -Dtest=OssPreviewAuthorizationServiceTest,SafePathResolverTest,FileControllerTest test`

Expected: PASS.

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/service/OssPreviewAuthorizationService.java src/test/java/com/ruanzhu/doorhandlecatch/service/OssPreviewAuthorizationServiceTest.java src/test/java/com/ruanzhu/doorhandlecatch/controller/FileControllerTest.java
git commit -m "feat: share authenticated task resources"
```

### Task 4: Share chat sessions and messages

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/ChatSessionService.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImpl.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImpl.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImplTest.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImplTest.java`

- [ ] **Step 1: Add failing cross-user chat tests**

```java
@Test
void userCanReadAndRenameSessionCreatedByAnotherUser() {
    ChatSession session = session("sess_shared", "alice");
    when(sessionMapper.selectOne(any())).thenReturn(session);

    assertThat(service.getSession("bob", "sess_shared").getSessionId())
            .isEqualTo("sess_shared");
    service.renameSession("bob", "sess_shared", "共享会话");

    verify(sessionMapper).updateById(argThat(updated ->
            "共享会话".equals(updated.getTitle())));
}
```

Add corresponding tests for list, messages, archive, delete, pin, checkpoint, message send, and pending-action confirmation.

- [ ] **Step 2: Run tests and verify owner checks fail**

Run: `.\mvnw.cmd -q -Dtest=ChatSessionServiceImplTest,AgentOrchestratorServiceImplTest test`

Expected: FAIL from username predicates or `verifySessionOwner`.

- [ ] **Step 3: Rename ownership APIs to shared-access APIs**

Change `verifySessionOwner` to `verifySessionAccess` and `requireOwnedSession` to `requireSession`. `requireSession` queries by `session_id` only and throws 404 if absent. Keep the actor username parameters because creation, rate limiting, memory, and audit attribution still need the current user.

- [ ] **Step 4: Make session listing shared**

Remove `.eq(ChatSession::getUsername, username)` from list queries. Preserve stable ordering by `pinned DESC, updated_at DESC`. Keep newly created sessions' `username` set to the creator.

- [ ] **Step 5: Update orchestrator call sites**

Replace calls to `verifySessionOwner` with `verifySessionAccess`. Keep Mem0 operations keyed by the current actor unless a separate enterprise memory store is explicitly introduced later.

- [ ] **Step 6: Run focused tests and commit**

Run: `.\mvnw.cmd -q -Dtest=ChatSessionServiceImplTest,AgentOrchestratorServiceImplTest test`

Expected: PASS.

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/service/ChatSessionService.java src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImpl.java src/main/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImpl.java src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImplTest.java src/test/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImplTest.java
git commit -m "feat: share chat sessions across users"
```

### Task 5: Share chat projects

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/ChatProjectService.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatProjectServiceImpl.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ChatProjectServiceImplTest.java`

- [ ] **Step 1: Add failing project sharing tests**

Test that Bob can list, rename, delete, attach a session to, and detach a session from a project created by Alice. Ensure project creation still stores Bob as creator.

```java
@Test
void userCanMoveAnySharedSessionIntoAnySharedProject() {
    when(projectMapper.selectOne(any())).thenReturn(project("proj-a", "alice"));
    when(sessionMapper.selectOne(any())).thenReturn(session("sess-b", "bob"));

    service.moveSessionToProject("charlie", "sess-b", "proj-a");

    verify(sessionMapper).updateById(argThat(s -> "proj-a".equals(s.getProjectId())));
}
```

- [ ] **Step 2: Run and verify failure**

Run: `.\mvnw.cmd -q -Dtest=ChatProjectServiceImplTest test`

Expected: FAIL from project or session ownership checks.

- [ ] **Step 3: Implement shared project lookup**

Replace `getProjectOwnedByUser` with `requireProject(projectId)`, query project and session IDs without username predicates, and remove username comparisons. Do not remove creator assignment on insert.

- [ ] **Step 4: Run and commit**

Run: `.\mvnw.cmd -q -Dtest=ChatProjectServiceImplTest test`

Expected: PASS.

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/service/ChatProjectService.java src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatProjectServiceImpl.java src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ChatProjectServiceImplTest.java
git commit -m "feat: share chat projects across users"
```

### Task 6: Add the audit persistence module

**Files:**
- Create: `src/main/resources/db/migration-V15-single-enterprise-shared-data.sql`
- Modify: `src/main/resources/db/schema.sql`
- Create: `src/main/java/com/ruanzhu/doorhandlecatch/entity/OperationAuditLog.java`
- Create: `src/main/java/com/ruanzhu/doorhandlecatch/mapper/OperationAuditLogMapper.java`
- Create: `src/main/java/com/ruanzhu/doorhandlecatch/service/OperationAuditService.java`
- Create: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/OperationAuditServiceImpl.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/config/SingleEnterpriseSharedDataMigrationContractTest.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/OperationAuditServiceImplTest.java`

- [ ] **Step 1: Add a migration contract test**

Read the migration as UTF-8 and assert it creates `operation_audit_log`, the three indexes, `utf8mb4`, and no `tenant_id` column.

- [ ] **Step 2: Add failing audit service tests**

```java
@Test
void successAuditUsesAuthenticatedActorAndRedactsSecrets() {
    authenticate("bob");
    service.recordSuccess("MODEL", "12", "PUBLISH",
            Map.of("token", "secret", "status", "PUBLISHED"));

    verify(mapper).insert(argThat(log ->
            "bob".equals(log.getOperator())
            && "SUCCESS".equals(log.getResult())
            && !log.getChangeSummary().contains("secret")
            && log.getChangeSummary().contains("PUBLISHED")));
}
```

Also test password, authorization, cookie, access-key, and binary-value redaction.

- [ ] **Step 3: Create the migration and mirror it in `schema.sql`**

Use the exact table definition approved in the design. Make migration creation idempotent with `CREATE TABLE IF NOT EXISTS`.

- [ ] **Step 4: Implement the entity, mapper, and service**

`OperationAuditService` exposes:

```java
void recordSuccess(String resourceType, String resourceId,
                   String action, Map<String, ?> changes);
void recordFailure(String resourceType, String resourceId,
                   String action, Throwable failure);
```

The implementation obtains the actor from `SecurityContextHolder`, reads request method/path/IP from `RequestContextHolder` when available, serializes only a sanitized bounded map, truncates summaries at 8 KiB, and never serializes multipart bodies.

- [ ] **Step 5: Run audit tests**

Run: `.\mvnw.cmd -q -Dtest=SingleEnterpriseSharedDataMigrationContractTest,OperationAuditServiceImplTest test`

Expected: PASS.

- [ ] **Step 6: Commit the audit module**

```powershell
git add src/main/resources/db src/main/java/com/ruanzhu/doorhandlecatch/entity/OperationAuditLog.java src/main/java/com/ruanzhu/doorhandlecatch/mapper/OperationAuditLogMapper.java src/main/java/com/ruanzhu/doorhandlecatch/service/OperationAuditService.java src/main/java/com/ruanzhu/doorhandlecatch/service/impl/OperationAuditServiceImpl.java src/test/java/com/ruanzhu/doorhandlecatch/config/SingleEnterpriseSharedDataMigrationContractTest.java src/test/java/com/ruanzhu/doorhandlecatch/service/impl/OperationAuditServiceImplTest.java
git commit -m "feat: add shared-operation audit log"
```

### Task 7: Audit critical write operations

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/ModelController.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/ModelInfoController.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/EmployeeController.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/DeviceController.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/DeviceUsageRecordController.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/DetectionTaskController.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/ChatAssistantController.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/ChatProjectController.java`
- Test: corresponding controller/service test classes under `src/test/java`

- [ ] **Step 1: Add audit-verification tests for every mutation family**

For each controller family, verify one representative success and one failure. Example:

```java
verify(auditService).recordSuccess(
        eq("MODEL"), eq(modelId.toString()), eq("DELETE"), anyMap());
```

Use stable resource types: `MODEL`, `EMPLOYEE`, `DEVICE`, `DEVICE_USAGE`, `DETECTION_TASK`, `CHAT_SESSION`, and `CHAT_PROJECT`.

- [ ] **Step 2: Run the controller tests and verify audit calls are missing**

Run: `.\mvnw.cmd -q -Dtest=ModelServiceImplTest,DeviceServiceImplTest,DetectionTaskServiceImplTest,ChatSessionServiceImplTest,ChatProjectServiceImplTest test`

Expected: FAIL on missing audit interactions.

- [ ] **Step 3: Inject and call the audit service**

Record success only after the underlying mutation succeeds. Wrap only the service invocation so a failure can call `recordFailure(...)` before rethrowing; do not swallow the original exception. Pass small field maps such as status transitions, never whole request objects or multipart files.

- [ ] **Step 4: Run focused tests and commit**

Run: `.\mvnw.cmd -q -Dtest=ModelServiceImplTest,DeviceServiceImplTest,DetectionTaskServiceImplTest,ChatSessionServiceImplTest,ChatProjectServiceImplTest test`

Expected: PASS.

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/controller src/test/java/com/ruanzhu/doorhandlecatch
git commit -m "feat: audit shared write operations"
```

### Task 8: Protect shared state transitions from stale writes

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/mapper/DetectionTaskMapper.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceImpl.java`
- Create: `src/main/java/com/ruanzhu/doorhandlecatch/common/ConcurrentUpdateException.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/common/GlobalExceptionHandler.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceImplTest.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/common/GlobalExceptionHandlerTest.java`

- [ ] **Step 1: Add a stale-transition test**

Mock the mapper's conditional update to return zero and assert the service throws `ConcurrentUpdateException` rather than reporting success.

- [ ] **Step 2: Add a 409 mapping test**

```java
@Test
void concurrentUpdateReturns409() {
    Result<String> result = handler.handleConcurrentUpdate(
            new ConcurrentUpdateException("数据已被其他用户修改，请刷新后重试"));
    assertThat(result.getCode()).isEqualTo(409);
}
```

- [ ] **Step 3: Implement conditional state updates**

Add mapper methods with `WHERE task_id = #{taskId} AND status = #{expectedStatus}` for review, disposition, rework, retry, and upload-complete transitions. Throw `ConcurrentUpdateException` when the affected row count is zero.

- [ ] **Step 4: Map conflicts to 409**

Add a specific handler before the generic exception handler:

```java
@ExceptionHandler(ConcurrentUpdateException.class)
public Result<String> handleConcurrentUpdate(ConcurrentUpdateException e) {
    return Result.error(409, e.getMessage());
}
```

- [ ] **Step 5: Run and commit**

Run: `.\mvnw.cmd -q -Dtest=DetectionTaskServiceImplTest,GlobalExceptionHandlerTest test`

Expected: PASS.

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/mapper/DetectionTaskMapper.java src/main/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceImpl.java src/main/java/com/ruanzhu/doorhandlecatch/common src/test/java/com/ruanzhu/doorhandlecatch
git commit -m "feat: reject stale shared task updates"
```

### Task 9: Align the frontend with equal user capabilities

**Files:**
- Modify: `frontend/src/layout/index.vue`
- Modify: `frontend/src/views/UserManual.vue`
- Create: `frontend/tests/single-enterprise-shared-access-contract.test.cjs`

- [ ] **Step 1: Add a failing source contract**

The Node test reads the two Vue files and asserts the layout no longer labels every user as “系统管理账号”, the manual explains single-enterprise shared access, and no menu/button is conditional on `ADMIN`, `OPERATOR`, or `REVIEWER`.

- [ ] **Step 2: Run and verify failure**

Run: `node --test tests/single-enterprise-shared-access-contract.test.cjs`

Working directory: `frontend`

Expected: FAIL because the layout currently displays administrator-specific wording.

- [ ] **Step 3: Update UI copy and remove role gating**

Show “企业用户” below the current username. Replace role-specific user-manual routes with a shared-capability explanation. Preserve login/logout behavior and creator attribution displays.

- [ ] **Step 4: Run frontend verification**

Run: `node --test tests/*.test.cjs`

Run: `npm run build`

Expected: all contract tests PASS and Vite build exits 0.

- [ ] **Step 5: Commit frontend alignment**

```powershell
git add frontend/src/layout/index.vue frontend/src/views/UserManual.vue frontend/tests/single-enterprise-shared-access-contract.test.cjs
git commit -m "feat: present equal capabilities to all users"
```

### Task 10: Complete regression and two-user acceptance verification

**Files:**
- Modify if required by failures: tests directly related to this feature only
- Verify: `docs/superpowers/specs/2026-07-05-single-enterprise-shared-data-design.md`

- [ ] **Step 1: Run the complete Java suite**

Run: `.\mvnw.cmd test`

Expected: all tests PASS. If the pre-existing raw-list AssertJ compilation error in `CompiledGraphGuardTest` remains, replace raw retrieval with an explicitly typed local variable:

```java
List<String> trace = result.get(AgentState.KEY_NODE_TRACE, List.class);
assertThat(trace).containsExactly("answer");
```

Commit that isolated test compatibility fix separately.

- [ ] **Step 2: Run Python unit tests in the declared environment**

Run: `.\scripts\run-python.ps1 -m pytest tests_python/test_agent.py tests_python/test_agent_auth_client.py tests_python/test_kafka_event_models.py tests_python/test_kafka_detection_worker.py tests_python/test_asr_service.py -q`

Expected: PASS. Do not include browser debug scripts that execute against port 3001 during test collection.

- [ ] **Step 3: Run frontend tests and build**

Run from `frontend`: `node --test tests/*.test.cjs`

Run from `frontend`: `npm run build`

Expected: PASS and successful production bundle.

- [ ] **Step 4: Perform two-user API acceptance checks**

Using two non-admin accounts, verify: Alice creates a task/session/project; Bob can read and mutate each; Bob can publish a model and manage a device; anonymous requests return 401; each Bob mutation creates an audit row with operator `bob`; an intentionally stale task transition returns 409.

- [ ] **Step 5: Inspect migration and query plans**

On a staging MySQL 8 database, apply V15, run `SHOW INDEX FROM operation_audit_log`, and use `EXPLAIN` for audit queries by operator/time and resource/time. Expected indexes are `idx_audit_operator_time`, `idx_audit_resource_time`, and `idx_audit_created_at`, with no full table scan for the first two access patterns.

- [ ] **Step 6: Confirm scope and working tree**

Run: `git status --short`

Expected: no uncommitted feature changes; the pre-existing untracked `docs/项目亮点与面试指南.md` remains untouched.

Run: `git log --oneline -10`

Expected: each task has a focused commit and no unrelated files are included.
