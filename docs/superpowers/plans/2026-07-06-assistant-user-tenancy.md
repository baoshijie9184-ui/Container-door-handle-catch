# Assistant Per-User Tenancy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate every user's assistant projects, sessions, messages, pending actions, checkpoints, Mem0 memories, and rate limits while keeping enterprise business data and RAG knowledge shared.

**Architecture:** Use immutable `users.id` as the tenant key carried in JWT and a server-created `TenantContext`. Add `user_id` to assistant aggregate roots, authorize every assistant operation with `(external_id, user_id)`, and scope Mem0 with namespaced `user_id`, fixed `app_id`, and session `run_id`. Keep username as compatibility and audit metadata during migration.

**Tech Stack:** Java 17, Spring Boot 3.2, Spring Security, JJWT, MyBatis-Plus, MySQL 8/InnoDB, FastAPI, Mem0, Chroma, JUnit 5, Mockito, pytest.

---

## File map

- Create `TenantContext.java` and `TenantPrincipal.java`: immutable authenticated tenant identity.
- Modify JWT/authentication classes: issue and restore immutable user ID.
- Create V16 migration and update schema: add/backfill/index assistant tenant columns.
- Modify chat entities and services: authorize by `user_id`, retain username only as metadata.
- Modify mappers/checkpointer paths: require user ID for checkpoint, message, and action access.
- Modify Java Mem0 client and Python memory service: require `user_id + app_id + run_id` scopes.
- Modify orchestrator: pass TenantContext through sync/SSE/async paths and key rate limits by user ID.

### Task 1: Add and validate the assistant tenancy migration

**Files:**
- Create: `src/main/resources/db/migration-V16-assistant-user-tenancy.sql`
- Modify: `src/main/resources/db/schema.sql`
- Create: `src/test/java/com/ruanzhu/doorhandlecatch/config/AssistantUserTenancyMigrationContractTest.java`

- [ ] **Step 1: Write a failing migration contract test**

```java
@Test
void migrationBackfillsAndConstrainsAssistantUserIds() throws Exception {
    String sql = Files.readString(Path.of("src/main/resources/db/migration-V16-assistant-user-tenancy.sql"));
    assertThat(sql)
            .contains("chat_project", "chat_session", "user_id")
            .contains("JOIN `users`")
            .contains("idx_chat_session_tenant_status_updated")
            .contains("idx_chat_project_tenant_sort_created")
            .contains("SIGNAL SQLSTATE '45000'")
            .doesNotContain("DROP COLUMN `username`");
}
```

- [ ] **Step 2: Run the test and verify it fails because V16 does not exist**

Run: `.\mvnw.cmd -q -Dtest=AssistantUserTenancyMigrationContractTest test`

Expected: FAIL on missing migration file.

- [ ] **Step 3: Create the idempotent migration**

Add nullable `user_id`, backfill with `UPDATE ... JOIN users ON username`, count null rows, and use a prepared `SIGNAL SQLSTATE '45000'` when unmatched rows remain. Only after validation, add foreign keys, composite indexes, and change both columns to `BIGINT NOT NULL`.

- [ ] **Step 4: Mirror the final schema**

Add `user_id BIGINT NOT NULL`, indexes, and foreign keys to `chat_project` and `chat_session` in `schema.sql`; keep username columns and their compatibility foreign keys.

- [ ] **Step 5: Run and commit**

Run: `.\mvnw.cmd -q -Dtest=AssistantUserTenancyMigrationContractTest test`

Expected: PASS.

```powershell
git add src/main/resources/db src/test/java/com/ruanzhu/doorhandlecatch/config/AssistantUserTenancyMigrationContractTest.java
git commit -m "feat: add assistant user tenancy migration"
```

### Task 2: Carry immutable user ID in authentication

**Files:**
- Create: `src/main/java/com/ruanzhu/doorhandlecatch/security/TenantContext.java`
- Create: `src/main/java/com/ruanzhu/doorhandlecatch/security/TenantPrincipal.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/util/JwtUtil.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/AuthServiceImpl.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/security/JwtAuthenticationFilter.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/AuthController.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/util/JwtUtilTest.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/security/JwtAuthenticationFilterTest.java`

- [ ] **Step 1: Add failing JWT and filter tests**

```java
@Test
void tokenCarriesImmutableUserId() {
    String token = jwtUtil.generateToken(42L, "alice");
    assertThat(jwtUtil.getUserIdFromToken(token)).isEqualTo(42L);
    assertThat(jwtUtil.getUsernameFromToken(token)).isEqualTo("alice");
}
```

Filter test: mock user `id=42`, parse a token for Alice, then assert the SecurityContext principal is `TenantPrincipal(42L, "alice", ...)`.

- [ ] **Step 2: Verify RED**

Run: `.\mvnw.cmd -q '-Dtest=JwtUtilTest,JwtAuthenticationFilterTest' test`

Expected: compilation failure because user-ID APIs and principal types do not exist.

- [ ] **Step 3: Implement tenant identity types**

```java
public record TenantContext(Long userId, String username) {
    public String mem0UserId() { return "doorhandlecatch:user:" + userId; }
}
```

`TenantPrincipal` implements `UserDetails`, stores `userId`, username, password, and authorities, and exposes `tenantContext()`.

- [ ] **Step 4: Add JWT `uid` claim and restore the principal**

Change token creation to `generateToken(Long userId, String username)`, store `uid`, add `getUserIdFromToken`, and reject tokens without a positive user ID. AuthService passes the database user's ID. JwtAuthenticationFilter verifies token username and ID match the freshly loaded user.

- [ ] **Step 5: Expose current user ID from `/api/auth/check`**

Read the TenantPrincipal from Authentication and return `userId` plus username. Do not accept user ID from request input.

- [ ] **Step 6: Run and commit**

Run: `.\mvnw.cmd -q '-Dtest=JwtUtilTest,JwtAuthenticationFilterTest,AuthControllerTest' test`

Expected: PASS.

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/security src/main/java/com/ruanzhu/doorhandlecatch/util/JwtUtil.java src/main/java/com/ruanzhu/doorhandlecatch/service/impl/AuthServiceImpl.java src/main/java/com/ruanzhu/doorhandlecatch/controller/AuthController.java src/test/java/com/ruanzhu/doorhandlecatch
git commit -m "feat: carry assistant tenant identity in JWT"
```

### Task 3: Persist assistant aggregate ownership by user ID

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/entity/ChatProject.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/entity/ChatSession.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/ChatProjectService.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/ChatSessionService.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ChatProjectServiceImplTest.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImplTest.java`

- [ ] **Step 1: Add failing ownership persistence tests**

Create TenantContext `(42, alice)`, create a project/session, capture the inserted entity, and assert both `userId=42` and `username=alice` are written.

- [ ] **Step 2: Verify RED**

Run: `.\mvnw.cmd -q '-Dtest=ChatProjectServiceImplTest,ChatSessionServiceImplTest' test`

Expected: compilation failure because entities and service methods lack userId/TenantContext.

- [ ] **Step 3: Add entity fields and update interfaces**

```java
@TableField("user_id")
private Long userId;
```

Replace username authorization parameters with `TenantContext tenant` while continuing to populate username on inserts.

- [ ] **Step 4: Run tests and commit**

Run: `.\mvnw.cmd -q '-Dtest=ChatProjectServiceImplTest,ChatSessionServiceImplTest' test`

Expected: PASS for ownership persistence tests.

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/entity src/main/java/com/ruanzhu/doorhandlecatch/service src/test/java/com/ruanzhu/doorhandlecatch/service/impl
git commit -m "feat: persist assistant tenant ownership"
```

### Task 4: Enforce project and session tenant boundaries

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatProjectServiceImpl.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImpl.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/ChatProjectController.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/ChatAssistantController.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ChatProjectServiceImplTest.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImplTest.java`

- [ ] **Step 1: Add cross-tenant denial tests**

For list queries, capture wrappers and assert `user_id=42`. For direct access, return no row for `(sessionId, userId)` and assert `BusinessException(404, "会话不存在")`. Cover get, rename, archive, pin, delete, move, and remove.

- [ ] **Step 2: Verify RED**

Run: `.\mvnw.cmd -q '-Dtest=ChatProjectServiceImplTest,ChatSessionServiceImplTest' test`

Expected: FAIL because current queries use username or external IDs alone.

- [ ] **Step 3: Replace username ownership predicates**

Every project/session list uses `user_id`. Every direct project/session query combines external ID and user ID. Rename helpers to `requireTenantProject` and `requireTenantSession`. Return 404 for missing/cross-tenant records.

- [ ] **Step 4: Build TenantContext only from Authentication**

Add a small `TenantContextResolver` that requires `TenantPrincipal`; controllers call it and never use request-supplied identity.

- [ ] **Step 5: Run and commit**

Run: `.\mvnw.cmd -q '-Dtest=ChatProjectServiceImplTest,ChatSessionServiceImplTest,AuthControllerTest' test`

Expected: PASS.

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatProjectServiceImpl.java src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImpl.java src/main/java/com/ruanzhu/doorhandlecatch/controller src/main/java/com/ruanzhu/doorhandlecatch/security/TenantContextResolver.java src/test/java/com/ruanzhu/doorhandlecatch
git commit -m "feat: enforce assistant tenant boundaries"
```

### Task 5: Tenant-protect messages, actions, and checkpoints

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/mapper/ChatSessionMapper.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImpl.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/stategraph/checkpoint/MySqlCheckpointer.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImplTest.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/stategraph/checkpoint/MySqlCheckpointerTest.java`

- [ ] **Step 1: Add failing cross-tenant tests**

Verify listMessages, checkpoint snapshot, pending-action lookup/status transition, and checkpointer load/save first call `requireTenantSession`. A foreign action ID in another tenant must produce 404 without updating it.

- [ ] **Step 2: Verify RED**

Run: `.\mvnw.cmd -q '-Dtest=ChatSessionServiceImplTest,MySqlCheckpointerTest' test`

Expected: FAIL because checkpoint and action methods accept session ID alone.

- [ ] **Step 3: Make checkpoint SQL tenant-aware**

Update/select statements use `WHERE session_id = #{sessionId} AND user_id = #{userId}`. Pass TenantContext explicitly into checkpointer save/load calls; do not use thread-local authentication inside stategraph workers.

- [ ] **Step 4: Guard messages and actions through the tenant session**

Keep message/action tables normalized, but require a successful tenant session lookup before querying or mutating child rows.

- [ ] **Step 5: Run and commit**

Run: `.\mvnw.cmd -q '-Dtest=ChatSessionServiceImplTest,MySqlCheckpointerTest' test`

Expected: PASS.

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/mapper/ChatSessionMapper.java src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImpl.java src/main/java/com/ruanzhu/doorhandlecatch/stategraph src/test/java/com/ruanzhu/doorhandlecatch
git commit -m "feat: tenant-protect assistant child data"
```

### Task 6: Scope Mem0 by user, application, and run

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/Mem0Client.java`
- Modify: `memory_service/main.py`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/Mem0ClientTest.java`
- Test: `tests_python/test_memory_service_tenancy.py`

- [ ] **Step 1: Add failing Java request-contract tests**

Inject a mock HTTP server and assert add/search bodies contain:

```json
{
  "user_id": "doorhandlecatch:user:42",
  "app_id": "doorhandlecatch",
  "run_id": "sess_abc"
}
```

Assert APIs reject blank scope fields before sending HTTP.

- [ ] **Step 2: Add failing FastAPI tests**

Use a fake `memory_instance`; POST add/search and assert Mem0 receives filters containing all three entity fields. Test that delete-all requires user and app scopes and never uses wildcards.

- [ ] **Step 3: Verify RED in both stacks**

Run: `.\mvnw.cmd -q -Dtest=Mem0ClientTest test`

Run: `.\scripts\run-python.ps1 -m pytest tests_python/test_memory_service_tenancy.py -q`

Expected: FAIL because current APIs only send user_id.

- [ ] **Step 4: Implement scoped DTOs and calls**

Add `app_id` and `run_id` to Python request models. Use Mem0 filters with `AND` over `user_id`, `app_id`, and `run_id`; for user-wide retrieval use explicit `run_id: "*"`. Java methods accept `TenantContext` and sessionId, build the namespaced user key, and send the fixed application ID.

- [ ] **Step 5: Run and commit**

Run both commands from Step 3.

Expected: PASS.

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/service/Mem0Client.java memory_service/main.py src/test/java/com/ruanzhu/doorhandlecatch/service/Mem0ClientTest.java tests_python/test_memory_service_tenancy.py
git commit -m "feat: isolate Mem0 memories by assistant tenant"
```

### Task 7: Propagate tenancy through orchestration and rate limiting

**Files:**
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/AgentOrchestratorService.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImpl.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/controller/ChatAssistantController.java`
- Test: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImplTest.java`

- [ ] **Step 1: Add failing isolation tests**

Verify Alice and Bob use different rate-window keys even with the same username display after a rename. Capture Mem0 calls and assert TenantContext plus the active session ID are passed for sync, SSE, and async memory writes.

- [ ] **Step 2: Verify RED**

Run: `.\mvnw.cmd -q -Dtest=AgentOrchestratorServiceImplTest test`

Expected: FAIL because orchestrator methods accept username only.

- [ ] **Step 3: Pass TenantContext explicitly**

Change send, stream, confirm, context build, and async memory functions to receive TenantContext. Key request windows by `tenant.userId()`. Capture TenantContext before creating SSE/async tasks and pass it as an immutable value.

- [ ] **Step 4: Preserve shared business and RAG access**

Do not add user ID predicates to detection, device, employee, model, dashboard, or RAG queries. Only assistant-owned records and Mem0 are tenant scoped.

- [ ] **Step 5: Run and commit**

Run: `.\mvnw.cmd -q -Dtest=AgentOrchestratorServiceImplTest test`

Expected: PASS.

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/service/AgentOrchestratorService.java src/main/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImpl.java src/main/java/com/ruanzhu/doorhandlecatch/controller/ChatAssistantController.java src/test/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImplTest.java
git commit -m "feat: propagate assistant tenant context"
```

### Task 8: Full regression and tenancy acceptance

**Files:**
- Verify: `docs/superpowers/specs/2026-07-06-assistant-user-tenancy-design.md`
- Modify only tests directly related to failures introduced by this feature.

- [ ] **Step 1: Run all Java tests**

Run: `.\mvnw.cmd test`

Expected: all tests PASS.

- [ ] **Step 2: Run all Python unit tests**

Run: `.\scripts\run-python.ps1 -m pytest tests_python -q`

Expected: all non-live tests PASS.

- [ ] **Step 3: Run frontend contracts and build**

Run from `frontend`: `node --test tests/*.test.cjs`

Run from `frontend`: `npm run build`

Expected: all contracts PASS and Vite build exits 0.

- [ ] **Step 4: Apply V16 to staging and inspect data/indexes**

Before migration, insert representative Alice/Bob sessions. Apply V16, assert zero null user IDs, and run `SHOW INDEX` for both tables. Use `EXPLAIN` on list and direct-access queries and verify the tenant composite indexes are selected.

- [ ] **Step 5: Perform two-user acceptance**

Alice creates a project/session/message/memory. Bob must receive 404 for Alice's identifiers and must not retrieve Alice's memory. Rename Alice and verify access/recall still succeeds through user ID. Confirm both users can still query shared detection and RAG data.

- [ ] **Step 6: Confirm clean scope**

Run: `git status --short`

Expected: no uncommitted feature changes; pre-existing `docs/项目亮点与面试指南.md` remains untouched.
