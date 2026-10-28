// Windows Jenkins controls the existing Linux ECS. No cloud-start operation is performed here.
pipeline {
    agent { node { label ''; customWorkspace "${params.BUILD_WORKSPACE}" } }
    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timestamps()
        timeout(time: 90, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '15', artifactNumToKeepStr: '5'))
    }
    triggers { pollSCM('H/5 * * * *') }
    parameters {
        choice(name: 'ACTION', choices: ['verify', 'verify-deploy', 'rehearse', 'rollback'], description: '默认仅验证；最终验收后才选择生产发布或回滚')
        booleanParam(name: 'PRODUCTION_RELEASE_ENABLED', defaultValue: false, description: '开发阶段保持关闭；最终验收通过后才允许生产发布或回滚')
        booleanParam(name: 'REHEARSAL_KEEP', defaultValue: false, description: '仅在隔离演练全部通过后保留候选环境，供立即进行浏览器验收；不修改生产入口')
        string(name: 'COMPATIBLE_BACKEND_IMAGE', defaultValue: '', description: '隔离演练可选：已存在且独立验收、支持身份/MCP 协议及写入暂停的旧版后端 sha256 镜像；不可使用候选冒充回滚基线')
        string(name: 'COMPATIBLE_RUNNER_IMAGE', defaultValue: '', description: '隔离演练可选：已存在且已审阅、支持当前固定 Fetch 协议的不可变 runner sha256 镜像；不修改生产运行器')
        string(name: 'REHEARSAL_MEMORY_EXTRACTION_MODEL', defaultValue: '', description: '隔离演练可选：明确指定同一百炼接入中的提炼模型；先核对其免费额度和用完即停，不变更向量模型或生产配置')
        choice(name: 'BUILD_NPM_REGISTRY', choices: ['https://registry.npmjs.org', 'https://registry.npmmirror.com'], description: '仅本次镜像构建使用的 npm 注册表，不写入生产私有环境或修改锁文件')
        string(name: 'BUILD_WORKSPACE', defaultValue: 'D:/AI/lunwen1/DoorHandleCatch/work/jenkins/workspace', description: '专用工作区；不能使用开发源码目录')
        string(name: 'DEPLOY_HOST', defaultValue: "${params.DEPLOY_HOST ?: ''}", description: '原 ECS 当前公网 IP；保留最近一次配置，节省停机后重新核对')
        string(name: 'DEPLOY_PORT', defaultValue: "${params.DEPLOY_PORT ?: '443'}", description: '保留最近验证的 SSH 端口；当前使用 443 TLS 入口')
        choice(name: 'SSH_TRANSPORT', choices: ['tls', 'direct'], description: '默认使用已验证的 TLS 通道，校验证书和 SSH 主机公钥；直连需另行验证端口')
        string(name: 'SSH_TLS_CA_FILE', defaultValue: 'D:/AI/lunwen1/DoorHandleCatch/work/cloud/ssh-tls/server.crt', description: '经云助手核验的服务器公有证书，不含私钥')
        string(name: 'OPENSSL_EXE', defaultValue: 'D:/ruanjian/Git/usr/bin/openssl.exe', description: '本机已有 Git OpenSSL 客户端')
        string(name: 'REMOTE_ROOT', defaultValue: '/home/ecs-user/doorhandle-ci', description: '保存版本与回滚状态的目录')
        string(name: 'REMOTE_RUNTIME', defaultValue: '/home/ecs-user/doorhandle-release-20261014', description: '已有部署目录，含私有 deploy/cloud.env 和 PTH 构建上下文')
        string(name: 'PYTHON_EXE', defaultValue: 'D:/ruanjian/anaconda3/envs/leetcode/python.exe', description: '本机已有测试环境，须安装 CI 测试依赖')
    }
    stages {
        stage('Checkout trusted branch') {
            steps {
                script {
                    if (isUnix()) { error('This pipeline requires the existing Windows Jenkins node.') }
                    if (params.ACTION in ['verify-deploy', 'rollback'] && !params.PRODUCTION_RELEASE_ENABLED) {
                        error('Production publishing is disabled during development. Complete final acceptance before enabling the release action.')
                    }
                    def buildRoot = pwd().replace('\\', '/')
                    dir('artifacts') {
                        if (pwd().replace('\\', '/') != "${buildRoot}/artifacts") {
                            error('Artifact cleanup must stay within this build workspace.')
                        }
                        deleteDir()
                    }
                }
                script {
                    def revision = checkout scm
                    env.GIT_BRANCH = revision.GIT_BRANCH
                    env.GIT_COMMIT = revision.GIT_COMMIT
                    def branch = env.BRANCH_NAME ?: env.GIT_BRANCH ?: ''
                    if (!(branch in ['java-cloud', 'origin/java-cloud'])) {
                        error('Deployment job must check out the trusted java-cloud branch.')
                    }
                    env.RELEASE_TAG = "ci-${env.BUILD_NUMBER}-${env.GIT_COMMIT.take(12)}"
                }
            }
        }
        stage('Deploy preflight') {
            when { expression { params.ACTION != 'verify' } }
            steps {
                withCredentials([
                    sshUserPrivateKey(credentialsId: 'doorhandle-ecs-ssh', keyFileVariable: 'DEPLOY_KEY', usernameVariable: 'DEPLOY_USER'),
                    file(credentialsId: 'doorhandle-ecs-known-hosts', variable: 'DEPLOY_KNOWN_HOSTS')
                ]) {
                    pwsh '& ./script/jenkins/pipeline.ps1 -Action Preflight'
                }
            }
        }
        stage('Verify') {
            when { expression { params.ACTION != 'rollback' } }
            steps { pwsh '& ./script/jenkins/verify.ps1 -PythonExe $env:PYTHON_EXE' }
            post { always { junit testResults: '**/target/surefire-reports/TEST-*.xml,artifacts/python-tests.xml', allowEmptyResults: true } }
        }
        stage('Package source') {
            when { expression { params.ACTION in ['verify-deploy', 'rehearse'] } }
            steps { pwsh '& ./script/jenkins/pipeline.ps1 -Action Package' }
        }
        stage('Rehearse application') {
            when { expression { params.ACTION == 'rehearse' } }
            steps {
                withCredentials([
                    sshUserPrivateKey(credentialsId: 'doorhandle-ecs-ssh', keyFileVariable: 'DEPLOY_KEY', usernameVariable: 'DEPLOY_USER'),
                    file(credentialsId: 'doorhandle-ecs-known-hosts', variable: 'DEPLOY_KNOWN_HOSTS')
                ]) {
                    pwsh '& ./script/jenkins/pipeline.ps1 -Action Rehearse'
                }
            }
        }
        stage('Deploy or rollback') {
            when { expression { params.ACTION in ['verify-deploy', 'rollback'] } }
            steps {
                withCredentials([
                    sshUserPrivateKey(credentialsId: 'doorhandle-ecs-ssh', keyFileVariable: 'DEPLOY_KEY', usernameVariable: 'DEPLOY_USER'),
                    file(credentialsId: 'doorhandle-ecs-known-hosts', variable: 'DEPLOY_KNOWN_HOSTS')
                ]) {
                    pwsh '& ./script/jenkins/pipeline.ps1 -Action Publish'
                }
            }
        }
    }
    post {
        always { archiveArtifacts artifacts: 'artifacts/*.json,artifacts/*.xml', allowEmptyArchive: true, fingerprint: true }
        success { echo 'Checks completed. Deployment status is recorded in the Publish stage; verify-only builds do not deploy.' }
        failure { echo 'Pipeline failed. Check the failed stage; an ECS start or database migration is never automatic.' }
    }
}
