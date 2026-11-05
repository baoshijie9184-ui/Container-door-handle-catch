const assert = require('node:assert/strict')
const test = require('node:test')
const { readFrontendFile, readProjectFile } = require('./helpers/project-source.cjs')

{
  const serviceBlock = (compose, name) => {
    const marker = `  ${name}:`
    const start = compose.indexOf(marker)
    assert.notEqual(start, -1, `missing service ${name}`)
    const remainder = compose.slice(start + marker.length)
    const nextSection = remainder.search(/\n  [\w-]+:|\nvolumes:|\nnetworks:/)
    return nextSection === -1 ? remainder : remainder.slice(0, nextSection)
  }

  test('compose declares two private Spring Boot instances with explicit ECS configuration', () => {
    const compose = readProjectFile('compose.nginx.yml')
    assert.match(compose, /^\s{2}backend-1:/m)
    assert.match(compose, /^\s{2}backend-2:/m)
    assert.doesNotMatch(serviceBlock(compose, 'backend-1'), /ports:/)
    assert.doesNotMatch(serviceBlock(compose, 'backend-2'), /ports:/)
    assert.match(compose, /SERVER_PORT:\s*8080/)
    assert.match(compose, /env_file:\s*\n\s*-\s*\$\{DOORHANDLE_ENV_FILE:\?[^}]+\}/)
    assert.doesNotMatch(compose, /host\.docker\.internal|host-gateway/)
  })

  test('backend image uses Maven build and non-root Java runtime', () => {
    const dockerfile = readProjectFile('deploy', 'backend', 'Dockerfile')
    assert.match(dockerfile, /FROM maven:.* AS build/)
    assert.match(dockerfile, /mvnw\.cmd|\.\/mvnw|mvn .*package/)
    assert.match(dockerfile, /FROM eclipse-temurin:17-jre/)
    assert.match(dockerfile, /chown -R app:app \/app/)
    assert.match(dockerfile, /USER app/)
    assert.match(dockerfile, /actuator\/health/)
  })

  test('nginx serves Vue and balances API traffic across both backends', () => {
    const nginx = readProjectFile('deploy', 'nginx', 'nginx.conf')
    assert.match(nginx, /upstream doorhandle_backend\s*{[\s\S]*least_conn;/)
    assert.match(nginx, /server backend-1:8080 max_fails=3 fail_timeout=10s;/)
    assert.match(nginx, /server backend-2:8080 max_fails=3 fail_timeout=10s;/)
    assert.match(nginx, /location \/api\/\s*{[\s\S]*proxy_pass http:\/\/doorhandle_backend;/)
    assert.match(nginx, /try_files \$uri \$uri\/ \/index\.html;/)
    assert.match(nginx, /location \/assets\/\s*{[\s\S]*immutable/)
  })

  test('nginx keeps assistant SSE responses unbuffered', () => {
    const nginx = readProjectFile('deploy', 'nginx', 'nginx.conf')
    assert.match(nginx, /location = \/api\/chat-assistant\/messages\/stream/)
    assert.match(nginx, /proxy_buffering off;/)
    assert.match(nginx, /proxy_cache off;/)
    assert.match(nginx, /proxy_read_timeout 300s;/)
  })

  test('compose exposes only nginx to the host', () => {
    const compose = readProjectFile('compose.nginx.yml')
    assert.match(compose, /^\s{2}nginx:/m)
    assert.match(compose, /NGINX_PORT:-80}:80/)
    assert.match(compose, /condition:\s*service_healthy/)
  })

  test('deployment environment requires explicit ECS service endpoints and credentials', () => {
    const env = readProjectFile('deploy', 'docker.env.example')
    const gitignore = readProjectFile('.gitignore')
    for (const key of ['DB_URL', 'DB_USERNAME', 'DB_PASSWORD', 'REDIS_HOST', 'APP_KAFKA_BOOTSTRAP_SERVERS']) {
      assert.match(env, new RegExp(`^${key}=[ \\t]*\\r?$`, 'm'))
    }
    assert.doesNotMatch(env, /host\.docker\.internal|jdbc:mysql:\/\/(?:localhost|127\.0\.0\.1)/)
    assert.match(env, /JWT_SECRET=replace-with-at-least-32-random-characters/)
    assert.doesNotMatch(env, /sk-[A-Za-z0-9]{16,}/)
    assert.match(gitignore, /^deploy\/\*\.env\r?$/m)
    assert.match(gitignore, /^!deploy\/\*\.env\.example\r?$/m)
  })

  test('deployment guide documents standalone Compose fallback', () => {
    const guide = readProjectFile('docs', 'nginx-compose-deployment.md')
    assert.match(guide, /docker-compose -f compose\.nginx\.yml/)
  })
}

{
  test('retains the declared Python dependency versions for managed environments', () => {
    const environment = readProjectFile('environment.yml')

    assert.match(environment, /^name:\s*leetcode\s*$/m)
    assert.match(environment, /python=3\.10/)
    assert.match(environment, /playwright==1\.60\.0/)
    assert.match(environment, /pytest>=8\.0\.0/)
    assert.match(environment, /requests>=2\.31\.0/)
    assert.match(environment, /Pillow>=10\.0\.0/)
  })

  test('retires the Windows Python runtime wrapper before it can start a local process', () => {
    const runner = readProjectFile('scripts', 'run-python.ps1')

    assert.match(runner, /throw 'Runtime and tests are ECS-only/)
    assert.match(runner, /docs\/ECS-only-runtime\.md/)
    assert.doesNotMatch(runner, /conda\s+run|Start-Process|&\s*(?:conda|python)/i)
  })

  test('keeps editor analysis while disabling local Python tests and the batch launcher', () => {
    const settings = JSON.parse(readProjectFile('.vscode', 'settings.json'))
    const batchLauncher = readProjectFile('tests_python', 'run_test.bat')

    assert.equal(typeof settings['python.defaultInterpreterPath'], 'string')
    assert.equal(settings['python.testing.pytestEnabled'], false)
    assert.equal(settings['python.testing.unittestEnabled'], false)
    assert.equal(settings['python.testing.autoTestDiscoverOnSaveEnabled'], false)
    assert.match(batchLauncher, /Runtime and tests are ECS-only/)
    assert.match(batchLauncher, /^exit \/b 1\s*$/m)
    assert.doesNotMatch(batchLauncher, /conda\s+run|python\s+-m\s+pytest|agent_live_smoke\.py/i)
  })

  test('lets Playwright resolve its installed Chromium browser', () => {
    const browserSmokeTest = readProjectFile('frontend', 'tests', 'test_browser.py')
    const frontendTest = readProjectFile('frontend', 'tests', 'test_frontend.py')

    assert.doesNotMatch(browserSmokeTest, /executable_path/)
    assert.doesNotMatch(frontendTest, /executable_path/)
    assert.match(browserSmokeTest, /chromium\.launch\(headless=True\)/)
    assert.match(frontendTest, /chromium\.launch\(headless=True\)/)
  })

  test('documents ECS execution and local editing and builds', () => {
    const readme = readProjectFile('README.md')
    const guide = readProjectFile('docs', 'ECS-only-runtime.md')

    assert.match(readme, /本地编辑与构建/)
    assert.match(readme, /mvn -DskipTests=true clean package/)
    assert.match(readme, /前端开发服务器和测试必须在 ECS 上启动/)
    assert.match(guide, /本地仅编辑、编译和打包/)
    assert.match(guide, /单元\/集成测试全部在 ECS 执行/)
    assert.match(guide, /Status=Stopped/)
    assert.match(guide, /StoppedMode=StopCharging/)
  })
}

test('tests\\layout-sidebar-fixed.test.cjs', () => {
  const source = readFrontendFile('src', 'layout', 'index.vue')

  assert.match(
    source,
    /\.layout-shell\s*\{[\s\S]*height:\s*100vh;[\s\S]*overflow:\s*hidden;/,
    'layout-shell should lock the viewport height and prevent page scrolling'
  )

  assert.match(
    source,
    /\.layout-sidebar\s*\{[\s\S]*height:\s*100%;[\s\S]*min-height:\s*0;[\s\S]*overflow-y:\s*auto;/,
    'layout-sidebar should stay pinned within the viewport'
  )

  assert.match(
    source,
    /\.layout-content\s*\{[\s\S]*overflow-y:\s*auto;/,
    'layout-content should own vertical scrolling'
  )

  console.log('layout sidebar fixed assertions passed')
})
