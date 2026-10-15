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
        choice(name: 'ACTION', choices: ['verify-deploy', 'verify', 'rollback'], description: '验证发布、仅验证，或回滚到上一次成功发布')
        string(name: 'BUILD_WORKSPACE', defaultValue: 'D:/AI/lunwen1/DoorHandleCatch/work/jenkins/workspace', description: '专用工作区；不能使用开发源码目录')
        string(name: 'DEPLOY_HOST', defaultValue: "${params.DEPLOY_HOST ?: ''}", description: '原 ECS 当前公网 IP；保留最近一次配置，节省停机后重新核对')
        string(name: 'DEPLOY_PORT', defaultValue: '443', description: '当前已验证的 TLS/SSH 入口')
        choice(name: 'SSH_TRANSPORT', choices: ['tls', 'direct'], description: '当前网络使用校验证书的 TLS 传输；直连仅适用于允许普通 SSH 的网络')
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
            when { expression { params.ACTION == 'verify-deploy' } }
            steps { pwsh '& ./script/jenkins/pipeline.ps1 -Action Package' }
        }
        stage('Deploy or rollback') {
            when { expression { params.ACTION != 'verify' } }
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
