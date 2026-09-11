# Assistant Internal Write Tenancy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every intelligent-assistant message, pending action, checkpoint, and asynchronous callback is authorized by immutable user ID plus session ID.

**Architecture:** Capture `TenantContext` once at the authenticated boundary and pass it explicitly through orchestration, StateGraph, checkpoint, and background upload APIs. Centralize `(user_id, session_id)` ownership validation in `ChatSessionServiceImpl`, and remove weak Mem0 overloads so compilation prevents future unscoped calls.

**Tech Stack:** Java 17, Spring Boot 3.2, Spring Security, MyBatis-Plus, JUnit 5, Mockito, Python 3/pytest, Mem0

---

### Task 1: Tenant-authorized chat session writes

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/ChatSessionService.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImpl.java`
- Modify: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImplTest.java`

- [ ] **Step 1: Write failing ownership tests**

Add tests that authenticate user `42`, invoke message, pending-action, and state methods with `new TenantContext(42L, "alice")`, capture the first `ChatSession` query, and assert its SQL contains both `session_id` and `user_id`. Add a cross-tenant case where `selectOne` returns `null` and assert `BusinessException` has status 404 before any message insert occurs.

```java
TenantContext tenant = new TenantContext(42L, "alice");
when(chatSessionMapper.selectOne(any())).thenReturn(null);

assertThatThrownBy(() -> chatSessionService.appendUserMessage(tenant, "sess_other", "hello"))
        .isInstanceOf(BusinessException.class)
        .extracting("code").isEqualTo(404);
verify(chatMessageMapper, never()).insert(any());
```

- [ ] **Step 2: Run tests and verify failure**

Run: `./mvnw -q -Dtest=ChatSessionServiceImplTest test`

Expected: compilation fails because tenant-aware method signatures do not exist.

- [ ] **Step 3: Add tenant-aware service signatures**

Replace session-only internal signatures with explicit tenant signatures:

```java
ChatMessageResponse appendUserMessage(TenantContext tenant, String sessionId, String content);
ChatMessageResponse appendAssistantMessage(TenantContext tenant, String sessionId, String content,
                                            String messageType, String intent, String actionId);
ChatPendingAction savePendingAction(TenantContext tenant, String sessionId, String actionId,
                                    String actionType, ChatPendingActionPayload payload);
ChatPendingAction getPendingAction(TenantContext tenant, String sessionId, String actionId);
boolean transitionPendingAction(TenantContext tenant, String sessionId, String actionId,
                                String expectedStatus, String targetStatus, String errorMessage);
void saveState(TenantContext tenant, String sessionId, String stateJson);
String loadState(TenantContext tenant, String sessionId);
```

In `ChatSessionServiceImpl`, call this guard at the start of every method above:

```java
private ChatSession requireOwnedSession(TenantContext tenant, String sessionId) {
    ChatSession session = chatSessionMapper.selectOne(new LambdaQueryWrapper<ChatSession>()
            .eq(ChatSession::getSessionId, sessionId)
            .eq(ChatSession::getUserId, tenant.userId())
            .last("limit 1"));
    if (session == null) throw new BusinessException(404, "会话不存在");
    return session;
}
```

Keep private unguarded persistence helpers only when their caller has already executed the guard in the same synchronous call.

- [ ] **Step 4: Run focused tests**

Run: `./mvnw -q -Dtest=ChatSessionServiceImplTest test`

Expected: all `ChatSessionServiceImplTest` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/ruanzhu/doorhandlecatch/service/ChatSessionService.java src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImpl.java src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImplTest.java
git commit -m "refactor: require tenant for assistant session writes"
```

### Task 2: Tenant-aware StateGraph and checkpoint

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/stategraph/core/AgentState.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/stategraph/checkpoint/Checkpointer.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/stategraph/checkpoint/MySqlCheckpointer.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/stategraph/core/CompiledGraph.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/stategraph/node/HumanConfirmNode.java`
- Modify: `src/test/java/com/ruanzhu/doorhandlecatch/stategraph/checkpoint/MySqlCheckpointerTest.java`
- Create: `src/test/java/com/ruanzhu/doorhandlecatch/stategraph/node/HumanConfirmNodeTest.java`
- Modify: `src/test/java/com/ruanzhu/doorhandlecatch/stategraph/core/CompiledGraphGuardTest.java`

- [ ] **Step 1: Write failing checkpoint and pending-action tests**

Add `AgentState.KEY_TENANT_USER_ID`, construct state with user ID 42, and verify checkpoint save/load/delete and `HumanConfirmNode` pass `new TenantContext(42L, "alice")`. Add a test asserting a missing user ID raises `StateGraphException` before persistence.

```java
AgentState state = AgentState.create("sess_1", "hello", "alice")
        .set(AgentState.KEY_TENANT_USER_ID, 42L);
checkpointer.save(new TenantContext(42L, "alice"), "sess_1", state);
verify(chatSessionService).saveState(new TenantContext(42L, "alice"), "sess_1", anyString());
```

- [ ] **Step 2: Run tests and verify failure**

Run: `./mvnw -q -Dtest=MySqlCheckpointerTest,HumanConfirmNodeTest,CompiledGraphGuardTest test`

Expected: compilation fails on the new tenant-aware checkpoint signatures.

- [ ] **Step 3: Change checkpoint contracts and graph propagation**

Use these contracts:

```java
void save(TenantContext tenant, String threadId, AgentState state);
AgentState load(TenantContext tenant, String threadId);
void delete(TenantContext tenant, String threadId);
```

Add helpers in `AgentState`:

```java
public static final String KEY_TENANT_USER_ID = "tenant_user_id";
public TenantContext requireTenantContext() {
    Long userId = getLong(KEY_TENANT_USER_ID);
    String username = getString(KEY_USERNAME);
    if (userId == null) throw new StateGraphException("AgentState 缺少租户用户 ID");
    return new TenantContext(userId, username);
}
```

Change `CompiledGraph.invoke` saves to use `state.requireTenantContext()`. Change resume to `resume(TenantContext tenant, String threadId, Map<String,Object> updates)` and use that tenant for checkpoint loading. Implement `MySqlCheckpointer` through tenant-aware `ChatSessionService` instead of direct unscoped mapper calls.

Update `HumanConfirmNode` to call:

```java
TenantContext tenant = state.requireTenantContext();
chatSessionService.savePendingAction(tenant, sessionId, actionId, decision.getIntent(), payload);
```

- [ ] **Step 4: Run StateGraph tests**

Run: `./mvnw -q -Dtest=MySqlCheckpointerTest,HumanConfirmNodeTest,CompiledGraphGuardTest test`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/ruanzhu/doorhandlecatch/stategraph src/test/java/com/ruanzhu/doorhandlecatch/stategraph
git commit -m "feat: bind state graph checkpoints to tenant"
```

### Task 3: Orchestrator propagation

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImpl.java`
- Modify: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImplTest.java`

- [ ] **Step 1: Write failing orchestration tests**

Update mocks to require `TenantContext` for every append, checkpoint, pending-action, transition, and resume call. Verify SSE captures user 42 before the executor runs.

```java
verify(chatSessionService).appendUserMessage(
        new TenantContext(42L, "alice"), "sess_alice_default", request.getContent());
verify(chatGraph).invoke(argThat(state ->
        Long.valueOf(42L).equals(state.getLong(AgentState.KEY_TENANT_USER_ID))));
```

- [ ] **Step 2: Run test and verify failure**

Run: `./mvnw -q -Dtest=AgentOrchestratorServiceImplTest test`

Expected: compilation or Mockito verification fails because old calls omit tenant context.

- [ ] **Step 3: Pass tenant through the complete orchestration call**

Set the tenant ID when creating state:

```java
AgentState state = AgentState.create(sessionId, request.getContent(), tenant.username())
        .set(AgentState.KEY_TENANT_USER_ID, tenant.userId());
```

Use tenant-aware session methods for all message and pending-action operations. Use `chatGraph.resume(tenant, sessionId, updates)`, and use tenant-aware checkpointer calls in context restore/save. Keep `requireTenant(username)` at public entry points.

- [ ] **Step 4: Run orchestrator tests**

Run: `./mvnw -q -Dtest=AgentOrchestratorServiceImplTest test`

Expected: all orchestrator tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImpl.java src/test/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImplTest.java
git commit -m "feat: propagate tenant through assistant orchestration"
```

### Task 4: Explicit tenant in asynchronous detection callbacks

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/DetectionUploadAsyncService.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/agent/impl/DetectionAgentServiceImpl.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceImpl.java`
- Modify: `src/test/java/com/ruanzhu/doorhandlecatch/service/DetectionUploadAsyncServiceTest.java`
- Modify: `src/test/java/com/ruanzhu/doorhandlecatch/service/agent/impl/DetectionAgentServiceImplTest.java`
- Modify: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceImplTest.java`

- [ ] **Step 1: Write failing async propagation test**

Clear `SecurityContextHolder`, call `uploadAndConfirm` with tenant 42, and verify success and failure callbacks use the explicit tenant.

```java
TenantContext tenant = new TenantContext(42L, "alice");
SecurityContextHolder.clearContext();
service.uploadAndConfirm(tenant, response, files, folder, "sess_alice_1");
verify(chatSessionService).appendAssistantMessage(
        eq(tenant), eq("sess_alice_1"), anyString(), eq("TEXT"), eq("DETECTION_ACTION"), isNull());
```

- [ ] **Step 2: Run tests and verify failure**

Run: `./mvnw -q -Dtest=DetectionUploadAsyncServiceTest,DetectionAgentServiceImplTest test`

Expected: compilation fails because `uploadAndConfirm` lacks a tenant parameter.

- [ ] **Step 3: Add explicit tenant task input**

Change the upload method to:

```java
@Async
public void uploadAndConfirm(TenantContext tenant,
                             CreateDetectionTaskResponse createResp,
                             List<DetectionUploadFileRequest> files,
                             Path folder,
                             String sessionId)
```

Require non-null tenant only when `sessionId` has text. Pass the state tenant from `DetectionAgentServiceImpl`; use it for every upload completion/error callback.

When a task with `sessionId` is created, validate the association before persisting it. Add a system-only resolver to `ChatSessionService`:

```java
TenantContext resolveTenantForSystemCallback(String sessionId);
```

Its implementation loads the session by globally unique `session_id`, requires non-null `user_id`, and returns `new TenantContext(session.getUserId(), session.getUsername())`. `DetectionTaskServiceImpl.notifyDetectionCompleted` must call the resolver first and then call the tenant-aware `appendAssistantMessage`. The resolver is not exposed from a controller.

- [ ] **Step 4: Run detection tests**

Run: `./mvnw -q -Dtest=DetectionUploadAsyncServiceTest,DetectionAgentServiceImplTest test`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/ruanzhu/doorhandlecatch/service src/test/java/com/ruanzhu/doorhandlecatch/service
git commit -m "feat: carry assistant tenant into async callbacks"
```

### Task 5: Remove weak Mem0 APIs and verify the repository

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/Mem0Client.java`
- Modify: `src/test/java/com/ruanzhu/doorhandlecatch/service/Mem0ClientTest.java`
- Verify: `memory_service/main.py`
- Verify: `tests_python/test_memory_service_tenancy.py`

- [ ] **Step 1: Add an API contract test**

Use reflection to assert there is no public Mem0 method whose first parameter is `String` for add/search operations:

```java
assertThat(Arrays.stream(Mem0Client.class.getMethods())
        .filter(method -> Set.of("addMemory", "addMemoryAsync", "searchMemories").contains(method.getName()))
        .filter(method -> method.getParameterCount() > 0)
        .filter(method -> method.getParameterTypes()[0] == String.class))
        .isEmpty();
```

- [ ] **Step 2: Run test and verify failure**

Run: `./mvnw -q -Dtest=Mem0ClientTest test`

Expected: the reflection assertion finds the legacy String overloads.

- [ ] **Step 3: Delete legacy overloads**

Remove:

```java
addMemory(String userId, ...)
addMemoryAsync(String userId, ...)
searchMemories(String userId, ...)
```

Keep only methods that accept `TenantContext` and `sessionId`. Run `rg -n "addMemory\(|addMemoryAsync\(|searchMemories\(" src/main/java` and confirm every production call supplies both values.

- [ ] **Step 4: Run complete verification**

Run:

```bash
./mvnw test -q
python -m pytest tests_python/test_memory_service_tenancy.py -q
git diff --check
```

Expected: Maven reports zero failures/errors, the Python tenancy test passes, and `git diff --check` prints no errors.

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/ruanzhu/doorhandlecatch/service/Mem0Client.java src/test/java/com/ruanzhu/doorhandlecatch/service/Mem0ClientTest.java
git commit -m "refactor: remove unscoped Mem0 APIs"
```
