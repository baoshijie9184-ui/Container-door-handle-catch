const assert = require('node:assert/strict')
const test = require('node:test')
const { readFrontendFile, readProjectFile } = require('./helpers/project-source.cjs')

test('tests\\chat-business-card-contract.test.cjs', () => {
  const source = readFrontendFile('src', 'components', 'chat', 'ChatBusinessCard.vue')

  assert.match(source, /payload\.value\.sources/)
  assert.match(source, /source-strip/)
  assert.match(source, /来源/)

  console.log('chat business card source contract assertions passed')
})

test('tests\\chat-confirm-action-guard-contract.test.cjs', () => {
  const storeSource = readFrontendFile('src', 'stores', 'chatAssistant.js')
  const listSource = readFrontendFile('src', 'components', 'chat', 'ChatMessageList.vue')
  const cardSource = readFrontendFile('src', 'components', 'chat', 'ChatPendingActionCard.vue')

  assert.match(storeSource, /confirmingActionIds/)
  assert.match(storeSource, /confirmingActionIds\.value\.has\(actionId\)/)
  assert.match(storeSource, /confirmingActionIds\.value\.add\(actionId\)/)
  assert.match(storeSource, /confirmingActionIds\.value\.delete\(actionId\)/)

  assert.match(listSource, /:busy="confirmingActionIds\.has\(item\.actionId\)"/)
  assert.match(cardSource, /busy:\s*\{\s*type:\s*Boolean/)
  assert.match(cardSource, /:disabled="busy"/)

  console.log('chat confirm action guard contract assertions passed')
})

{
  test('question helper keeps only user messages and builds stable keys', async () => {
    const helperSource = readFrontendFile('src', 'utils', 'chatMessageNavigation.js')
    const helperUrl = `data:text/javascript;base64,${Buffer.from(helperSource).toString('base64')}`
    const { buildChatMessageKey, buildQuestionItems } = await import(helperUrl)
    const messages = [
      { id: 7, role: 'user', content: '讲解 Kafka', createdAt: '2026-07-05T10:00:00Z' },
      { id: 8, role: 'assistant', content: 'Kafka 是事件流平台' },
      { role: 'user', content: '消息存在哪里', createdAt: '2026-07-05T10:01:00Z' }
    ]

    assert.equal(buildChatMessageKey(messages[0], 0), 'message-7')
    assert.deepEqual(buildQuestionItems(messages), [
      { key: 'message-7', content: '讲解 Kafka', createdAt: '2026-07-05T10:00:00Z' },
      { key: 'message-user-2026-07-05T10:01:00Z-2', content: '消息存在哪里', createdAt: '2026-07-05T10:01:00Z' }
    ])
  })

  test('navigator is accessible and supports dismiss interactions', () => {
    const source = readFrontendFile('src', 'components', 'chat', 'ChatQuestionNavigator.vue')
    assert.match(source, /aria-label="查看历史提问"/)
    assert.match(source, /:aria-expanded="String\(open\)"/)
    assert.match(source, /aria-controls="chat-question-list"/)
    assert.match(source, /event\.key === 'Escape'/)
    assert.match(source, /event\.stopPropagation\(\)/)
    assert.match(source, /document\.addEventListener\('pointerdown'/)
    assert.match(source, /questions\.length/)
  })

  test('message list exposes smooth location and temporary highlight', () => {
    const source = readFrontendFile('src', 'components', 'chat', 'ChatMessageList.vue')
    assert.match(source, /:data-message-key="buildChatMessageKey\(item, idx\)"/)
    assert.match(source, /scrollIntoView/)
    assert.match(source, /question-locate-highlight/)
    assert.match(source, /prefers-reduced-motion/)
    assert.match(source, /defineExpose\(\{ locateMessage \}\)/)
  })

  test('drawer integrates current-session questions with the message list', () => {
    const source = readFrontendFile('src', 'components', 'chat', 'ChatAssistantDrawer.vue')
    assert.match(source, /ChatQuestionNavigator/)
    assert.match(source, /buildQuestionItems\(chatStore\.messages\)/)
    assert.match(source, /messageListRef\.value\?\.locateMessage\(key\)/)
    assert.match(source, /:questions="questionItems"/)
  })
}

{
  const launcherSource = readFrontendFile('src', 'components', 'chat', 'ChatAssistantLauncher.vue')
  const drawerSource = readFrontendFile('src', 'components', 'chat', 'ChatAssistantDrawer.vue')
  const sidebarSource = readFrontendFile('src', 'components', 'chat', 'ChatSidebar.vue')
  const layoutSource = readFrontendFile('src', 'layout', 'index.vue')

  test('assistant launcher clamps persisted coordinates on mount and resize', () => {
    assert.match(launcherSource, /ref="launcherRef"/)
    assert.match(launcherSource, /const clampToViewport\s*=\s*\(\)\s*=>/)
    assert.match(launcherSource, /window\.addEventListener\('resize', clampToViewport\)/)
    assert.match(launcherSource, /window\.removeEventListener\('resize', clampToViewport\)/)
    assert.match(launcherSource, /nextTick\(clampToViewport\)/)
  })

  test('assistant drawer recalculates its width from the current viewport', () => {
    assert.match(drawerSource, /:size="drawerSize"/)
    assert.match(drawerSource, /v-if="!isMobile"/)
    assert.match(drawerSource, /const viewportWidth = ref\(window\.innerWidth\)/)
    assert.match(drawerSource, /const isMobile = computed\(/)
    assert.match(drawerSource, /const drawerSize = computed\(/)
    assert.match(drawerSource, /const handleViewportResize\s*=\s*\(\)\s*=>/)
    assert.match(drawerSource, /window\.addEventListener\('resize', handleViewportResize\)/)
    assert.match(drawerSource, /window\.removeEventListener\('resize', handleViewportResize\)/)
    assert.doesNotMatch(drawerSource, /const MAX_WIDTH\s*=/)
  })

  test('assistant session sidebar defaults to compact mode on mobile', () => {
    assert.match(drawerSource, /<ChatSidebar\s+:compact="isMobile"\s*\/>/)
    assert.match(sidebarSource, /defineProps\(\{[\s\S]*compact:/)
    assert.match(sidebarSource, /const collapsed = ref\(props\.compact\)/)
    assert.match(sidebarSource, /watch\(\(\) => props\.compact/)
  })

  test('application shell uses fluid viewport-aware spacing', () => {
    assert.match(layoutSource, /padding:\s*clamp\(/)
    assert.match(layoutSource, /gap:\s*clamp\(/)
  })
}

test('tests\\chat-text-source-contract.test.cjs', () => {
  const source = readFrontendFile('src', 'components', 'chat', 'ChatMessageList.vue')

  assert.match(source, /SOURCE_PATTERN/)
  assert.match(source, /messageSourceText/)
  assert.match(source, /messageBodyContent/)
  assert.match(source, /msg-source-strip/)
  assert.match(source, /msg-source-chip/)

  console.log('chat text source contract assertions passed')
})

test('tests\\chat-voice-input-contract.test.cjs', () => {
  const apiSource = readFrontendFile('src', 'api', 'chatAssistant.js')
  const composerSource = readFrontendFile('src', 'components', 'chat', 'ChatComposer.vue')

  assert.match(apiSource, /transcribeChatVoice/)
  assert.match(apiSource, /\/api\/chat-assistant\/voice\/transcribe/)
  assert.match(apiSource, /FormData/)

  assert.match(composerSource, /MediaRecorder/)
  assert.match(composerSource, /chooseSupportedMimeType/)
  assert.match(composerSource, /MediaRecorder\.isTypeSupported/)
  assert.match(composerSource, /selectedVoiceMimeType/)
  assert.match(composerSource, /MAX_RECORDING_SECONDS/)
  assert.match(composerSource, /recordingSeconds/)
  assert.match(composerSource, /recordingTimer/)
  assert.match(composerSource, /startRecordingTimer/)
  assert.match(composerSource, /clearRecordingTimer/)
  assert.match(composerSource, /recording/)
  assert.match(composerSource, /voiceTranscribing/)
  assert.match(composerSource, /transcribeChatVoice/)
  assert.match(composerSource, /draft\.value = text/)
  assert.match(composerSource, /aria-label="语音输入"/)
  assert.match(composerSource, /voiceHint\.value = '未识别到语音，请靠近麦克风后重试'/)
  assert.match(composerSource, /onBeforeUnmount\(\(\) => \{[\s\S]*voiceTranscribing\.value = false/)
  assert.match(composerSource, /onBeforeUnmount\(\(\) => \{[\s\S]*audioChunks = \[\]/)

  console.log('chat voice input contract assertions passed')
})

test('tests\\business-trace-presets-contract.test.cjs', () => {
  const presetSource = readFrontendFile('src', 'config', 'businessTracePresets.js')
  const traceComposableSource = readFrontendFile('src', 'composables', 'useTraceReports.js')
  const businessSeedEmptyHintSource = readFrontendFile('src', 'components', 'BusinessSeedEmptyHint.vue')
  const userManualSource = readFrontendFile('src', 'views', 'UserManual.vue')
  const dbReadmeSource = readProjectFile('src', 'main', 'resources', 'db', 'README.md')
  const userGuideSource = readProjectFile('docs', 'system-user-guide.md')
  const businessSeedStartScript = readProjectFile('scripts', 'start-backend-with-business-seed.ps1')
  const businessSeedSources = [
    readProjectFile('src', 'main', 'resources', 'db', 'business-seed-new-features.sql'),
    readProjectFile('src', 'main', 'resources', 'db', 'business-seed-more-features.sql'),
    readProjectFile('src', 'main', 'resources', 'db', 'business-seed-trace-rich.sql')
  ]
  const normalizedPages = [
    readFrontendFile('src', 'views', 'ImageDetection.vue'),
    readFrontendFile('src', 'views', 'quality', 'QualityQueue.vue'),
    readFrontendFile('src', 'views', 'quality', 'DefectEvidenceGallery.vue'),
    readFrontendFile('src', 'views', 'quality', 'WorkOrderTrace.vue'),
    readFrontendFile('src', 'views', 'quality', 'BatchTrace.vue'),
    readFrontendFile('src', 'views', 'inspection', 'InspectionHistory.vue'),
    readFrontendFile('src', 'views', 'inspection', 'InspectionWorkbench.vue')
  ]
  const migrationSource = readProjectFile('src', 'main', 'resources', 'db', 'migration-V13-business-seed-data-normalization.sql')

  assert.match(presetSource, /businessWorkOrderNos/)
  assert.match(presetSource, /businessBatchNos/)
  assert.match(presetSource, /WO-SH-A-001/)
  assert.match(presetSource, /BATCH-SH-A-20260615-001/)
  assert.doesNotMatch(presetSource, /DEMO|demo|示例|演示/)

  assert.match(traceComposableSource, /businessWorkOrderNos/)
  assert.match(traceComposableSource, /businessBatchNos/)
  assert.doesNotMatch(traceComposableSource, /demoWorkOrderNos|demoBatchNos|loadDemoWorkOrderTrace|loadDemoBatchTrace/)

  for (const source of normalizedPages) {
    assert.doesNotMatch(source, /demoWorkOrderNos|demoBatchNos|useDemoWorkOrder|useDemoBatch/)
    assert.doesNotMatch(source, /loadDemoWorkOrderTrace|loadDemoBatchTrace/)
    assert.doesNotMatch(source, /示例工单|示例批次|上方示例/)
  }

  for (const source of businessSeedSources) {
    assert.doesNotMatch(source, /WO-DEMO-|ALERT-DEMO-|demo_trace_|demo_task_ext_|demo\/device|demo\/evidence|demo\/tasks|demo\/trace/)
    assert.doesNotMatch(source, /演示数据：|扩展演示：|追溯演示：/)
  }

  assert.match(dbReadmeSource, /业务预置数据/)
  assert.match(dbReadmeSource, /APP_BUSINESS_SEED_ENABLED=true/)
  assert.match(dbReadmeSource, /start-backend-with-business-seed\.ps1/)
  assert.doesNotMatch(userGuideSource, /初始化演示数据/)
  assert.match(businessSeedEmptyHintSource, /APP_BUSINESS_SEED_ENABLED=true/)
  assert.match(businessSeedEmptyHintSource, /业务预置数据导入/)
  assert.match(businessSeedEmptyHintSource, /to="\/manual"/)
  assert.match(userManualSource, /首次验收没有工单、批次、质检数据怎么办/)
  assert.match(userManualSource, /APP_BUSINESS_SEED_ENABLED/)
  assert.match(userManualSource, /mvnw\.cmd spring-boot:run/)
  assert.match(userManualSource, /start-backend-with-business-seed\.ps1/)
  assert.match(businessSeedStartScript, /APP_BUSINESS_SEED_ENABLED\s*=\s*'true'/)
  assert.match(businessSeedStartScript, /mvnw\.cmd spring-boot:run/)

  assert.match(migrationSource, /REPLACE\(`work_order_no`, 'WO-DEMO-', 'WO-'\)/)
  assert.match(migrationSource, /ALERT-BIZ-/)
  assert.match(migrationSource, /演示数据：/)
  assert.match(migrationSource, /扩展演示：/)
  assert.match(migrationSource, /追溯演示：/)

  console.log('business trace presets contract assertions passed')
})
