# Project Highlights Document Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create one index and five independent, code-focused Markdown guides for the project's five highlights, following the structure of the supplied like-system reference guide.

**Architecture:** Keep the existing overview document and add a focused `docs/project-highlights/` documentation set. Each guide owns one technical boundary, uses real source snippets and paths, and follows the same architecture → code index → Step flow → mechanism → code explanation → summary → interview sequence.

**Tech Stack:** Markdown, Java/Spring Boot, StateGraph, Kafka, Python/ONNX, Vue/Pinia, Nginx, Docker Compose

---

## File Structure

- Create `docs/project-highlights/README.md`: navigation, summaries, reading order, and interview usage.
- Create `docs/project-highlights/01-hermes-multi-agent-memory.md`: StateGraph, routing, memory, confirmation, checkpoint, and guard details.
- Create `docs/project-highlights/02-intelligent-business-assistant.md`: UI-to-Agent business interaction, SSE, cards, sessions, voice, and ownership isolation.
- Create `docs/project-highlights/03-kafka-image-detection.md`: OSS upload, Kafka events, Python Worker, ONNX inference, offset handling, and idempotency.
- Create `docs/project-highlights/04-model-quality-traceability.md`: model validation/lifecycle and the review-disposition-rework traceability workflow.
- Create `docs/project-highlights/05-nginx-docker-deployment.md`: frontend/backend images, Compose topology, Nginx proxy/load balancing, SSE, and security.
- Modify `docs/项目亮点与面试指南.md`: add links to the five deep-dive guides while retaining its overview role.

### Task 1: Create the documentation index

**Files:**
- Create: `docs/project-highlights/README.md`

- [ ] **Step 1: Create the index headings**

Add project positioning, a five-row navigation table, recommended reading order, and guidance for using the documents during interview preparation.

- [ ] **Step 2: Verify all target links are declared**

Run:

```powershell
rg -n "01-hermes|02-intelligent|03-kafka|04-model|05-nginx" docs/project-highlights/README.md
```

Expected: all five filenames appear.

- [ ] **Step 3: Commit the index**

```powershell
git add docs/project-highlights/README.md
git commit -m "docs: add project highlight guide index"
```

### Task 2: Write the Hermes Multi-Agent and memory guide

**Files:**
- Create: `docs/project-highlights/01-hermes-multi-agent-memory.md`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/stategraph/config/StateGraphConfiguration.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImpl.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/stategraph/core/CompiledGraph.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/stategraph/checkpoint/MySqlCheckpointer.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/service/Mem0Client.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/service/RagKnowledgeService.java`

- [ ] **Step 1: Write architecture and code index sections**

Include an ASCII graph showing input → checkpoint/RAG/Mem0 → router → slot filling or specialist Agent → confirmation/responder/fallback.

- [ ] **Step 2: Write the Step-by-Step execution flow**

Cover state creation, context recovery, RAG retrieval, Mem0 retrieval, route selection, slot collection, specialist execution, human confirmation, checkpoint save/resume, response, and asynchronous memory storage.

- [ ] **Step 3: Add real code snippets with explanations**

Explain graph construction, `CONTEXT_KEYS`, `buildStateWithContext`, memory injection, `confirmAction`, `CompiledGraph.resume`, and guard checks.

- [ ] **Step 4: Add mechanism summaries and interview Q&A**

Include memory-layer comparison, action state transitions, guard behavior, limitations, improvements, and at least six interview questions.

- [ ] **Step 5: Validate and commit**

```powershell
rg -n "整体架构|代码位置索引|详细流程|代码详解|关键设计总结|面试" docs/project-highlights/01-hermes-multi-agent-memory.md
git add docs/project-highlights/01-hermes-multi-agent-memory.md
git commit -m "docs: explain hermes agent architecture"
```

Expected: every required section is found before commit.

### Task 3: Write the intelligent business assistant guide

**Files:**
- Create: `docs/project-highlights/02-intelligent-business-assistant.md`
- Reference: `frontend/src/components/chat/ChatAssistantDrawer.vue`
- Reference: `frontend/src/stores/chatAssistant.js`
- Reference: `frontend/src/api/chatAssistant.js`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/controller/ChatAssistantController.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ChatSessionServiceImpl.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/mapper/ChatPendingActionMapper.java`

- [ ] **Step 1: Document the frontend-to-business-service architecture**

Show drawer/composer → Pinia → SSE API → controller → orchestrator → specialist service → structured card/confirmation response.

- [ ] **Step 2: Document the detailed interaction flows**

Cover normal query, structured card response, write action confirmation, SSE lifecycle, voice transcription, session ownership, and error rendering.

- [ ] **Step 3: Add code and line-by-line explanations**

Explain SSE endpoint, emitter events, Pinia stream processing, message persistence, owner verification, and conditional pending-action transition.

- [ ] **Step 4: Add API table, design summary, limitations, and interview Q&A**

Clearly distinguish natural-language orchestration from direct LLM SQL execution.

- [ ] **Step 5: Validate and commit**

```powershell
rg -n "整体架构|代码位置索引|详细流程|SSE|代码详解|面试" docs/project-highlights/02-intelligent-business-assistant.md
git add docs/project-highlights/02-intelligent-business-assistant.md
git commit -m "docs: explain intelligent business assistant"
```

### Task 4: Write the Kafka image detection guide

**Files:**
- Create: `docs/project-highlights/03-kafka-image-detection.md`
- Reference: `frontend/src/services/singleImageKafkaDetection.js`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceImpl.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/service/detection/DetectionTaskEventPublisher.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/service/detection/DetectionTaskFinishedEventListener.java`
- Reference: `kafka_detection_worker.py`
- Reference: `oss_result_uploader.py`

- [ ] **Step 1: Document the asynchronous architecture and code index**

Show browser → Spring task service → OSS → Kafka created topic → Python Worker/ONNX → OSS result → Kafka finished topic → Spring listener → browser polling.

- [ ] **Step 2: Write normal, retry, duplicate, stale-event, and partial-failure flows**

Use concrete sample values for `taskId`, `dispatchId`, `eventId`, task status, OSS keys, and event payloads.

- [ ] **Step 3: Add code and line-by-line explanations**

Explain task creation, upload confirmation claim, synchronous broker acknowledgement, worker processing, finished-event-before-offset-commit, and Java-side idempotency.

- [ ] **Step 4: Add event/status tables, tradeoffs, improvements, and interview Q&A**

Explicitly describe at-least-once semantics and why business idempotency remains necessary.

- [ ] **Step 5: Validate and commit**

```powershell
rg -n "整体架构|代码位置索引|详细流程|dispatchId|eventId|代码详解|面试" docs/project-highlights/03-kafka-image-detection.md
git add docs/project-highlights/03-kafka-image-detection.md
git commit -m "docs: explain kafka image detection pipeline"
```

### Task 5: Write the model governance and quality traceability guide

**Files:**
- Create: `docs/project-highlights/04-model-quality-traceability.md`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ModelServiceImpl.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/OnnxModelValidationService.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/ModelInfoServiceImpl.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceImpl.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/entity/ModelInfo.java`
- Reference: `src/main/java/com/ruanzhu/doorhandlecatch/entity/DetectionTask.java`

- [ ] **Step 1: Document model and quality-loop architecture**

Present model upload/validation/evaluation/deployment/usage/archive and detection/assignment/review/disposition/rework/recheck as connected but separate state flows.

- [ ] **Step 2: Document detailed model and quality workflows**

Include valid/invalid upload, default model behavior, strategy configuration, defect evidence, review validation, disposition branches, rework reset, and trace timeline generation.

- [ ] **Step 3: Add code and line-by-line explanations**

Explain ONNX validation status, model metadata updates, quality transition checks, evidence persistence, and batch/work-order report construction.

- [ ] **Step 4: Add status/metric tables, design summary, limitations, and interview Q&A**

Separate features implemented in code from suggested future automated rollout controls.

- [ ] **Step 5: Validate and commit**

```powershell
rg -n "整体架构|代码位置索引|模型生命周期|质量|代码详解|关键设计总结|面试" docs/project-highlights/04-model-quality-traceability.md
git add docs/project-highlights/04-model-quality-traceability.md
git commit -m "docs: explain model and quality traceability"
```

### Task 6: Write the Nginx and Docker Compose deployment guide

**Files:**
- Create: `docs/project-highlights/05-nginx-docker-deployment.md`
- Reference: `compose.nginx.yml`
- Reference: `deploy/nginx/nginx.conf`
- Reference: `deploy/nginx/Dockerfile`
- Reference: `deploy/backend/Dockerfile`
- Reference: `deploy/docker.env.example`

- [ ] **Step 1: Document the deployment topology and code index**

Show browser → Nginx static/API/SSE routes → two backend containers → external MySQL/Redis/Kafka/Mem0/OSS.

- [ ] **Step 2: Document startup and request flows**

Cover image builds, health-gated startup, static resource serving, SPA fallback, API proxy selection, SSE streaming, shared upload volume, and external host services.

- [ ] **Step 3: Add code and line-by-line explanations**

Explain Compose anchors, private backend exposure, `least_conn`, failure parameters, proxy headers, SSE buffering controls, multi-stage builds, and non-root permissions.

- [ ] **Step 4: Add configuration tables, failure analysis, production improvements, and interview Q&A**

State that Compose configuration was statically validated and distinguish it from a full runtime smoke test.

- [ ] **Step 5: Validate and commit**

```powershell
rg -n "整体架构|代码位置索引|详细流程|least_conn|SSE|代码详解|面试" docs/project-highlights/05-nginx-docker-deployment.md
git add docs/project-highlights/05-nginx-docker-deployment.md
git commit -m "docs: explain nginx compose deployment"
```

### Task 7: Link the overview and run documentation verification

**Files:**
- Modify: `docs/项目亮点与面试指南.md`
- Verify: `docs/project-highlights/*.md`

- [ ] **Step 1: Add a deep-dive navigation section to the overview**

Link all five documents and clarify that the overview is for quick review while the split documents are source-level guides.

- [ ] **Step 2: Scan for placeholders and broken local links**

Run:

```powershell
rg -n "TODO|TBD|待补充|占位" docs/project-highlights docs/项目亮点与面试指南.md
$links = rg -o "\]\(([^)#]+\.md)(#[^)]+)?\)" docs/project-highlights docs/项目亮点与面试指南.md
```

Expected: no placeholders; every relative Markdown file target resolves from its containing document.

- [ ] **Step 3: Verify required structure in all five guides**

Run a PowerShell loop checking for `整体架构`, `代码位置索引`, `详细流程`, `代码详解`, `关键设计总结`, and `面试` in every numbered guide.

Expected: every guide contains every required section.

- [ ] **Step 4: Check Markdown and repository diff**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only intended documentation files remain changed.

- [ ] **Step 5: Commit the overview links and final verification adjustments**

```powershell
git add docs/项目亮点与面试指南.md docs/project-highlights
git commit -m "docs: complete project highlight deep dives"
```
