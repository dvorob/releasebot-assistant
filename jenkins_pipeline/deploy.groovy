node('docker') {
    ansiColor('xterm') {
        cleanWs()
        def dockerImageUrl = "docker.nexus.yamoney.ru/yamoney/ubuntu-20-04-ym"
        def registry = 'docker-ym.nexus.yooteam.ru'
        def image = 'releasebot-assistant'
        def home_dir = '/var/lib/jenkins/workspace/Common/releasebot/assistant'
        def image_version = "0.${BUILD_NUMBER}"
        def credentials = [
                        jenkins  : '45d976f8-a1fb-4b55-892e-a7add19dc44f',
                        bitbucket: '45d976f8-a1fb-4b55-892e-a7add19dc44f',
                        vault: 'svcJenkinsProdUser',
                        registryCredentialsId: 'svcJenkinsProdUser'
                        ]
        try {
            docker.image("${dockerImageUrl}").inside("-v /var/run/docker.sock:/var/run/docker.sock --net=host --group-add docker") {
                stage('docker build && push') {
                    echo 'Fetching repo'
                    checkout ([$class: 'GitSCM',
                        branches: [[name: branchName]],
                        extensions: [[$class: 'RelativeTargetDirectory', relativeTargetDir: '']],
                        userRemoteConfigs: [[credentialsId: credentials.bitbucket,
                        url: 'ssh://git@bitbucket.yamoney.ru/admin-tools/releasebot-assistant.git']]])

                    echo 'Build & push docker image'
                    def commit_id = sh(script:"git rev-parse --short HEAD", returnStdout: true).trim()
                    def prepare_tag_yaml = ["releasebot": ["tag": image_version]]
                    writeYaml file: 'tag-values.yaml', data: prepare_tag_yaml
                    withDockerRegistry([ url: "https://${registry}", credentialsId: credentials.registryCredentialsId ]) {
                        def image_build = docker.build("${registry}/yamoney/${image}", "-f Dockerfile --pull .")
                        image_build.push(image_version)
                        image_build.push('latest')
                    }
                    notifyBitbucket(buildStatus: 'INPROGRESS')
                }
                stage('get secret from vault') {
                    // set credential for get secret from Vault
                    withCredentials([usernamePassword(credentialsId: credentials.vault, usernameVariable: 'JenkinsUser', passwordVariable: 'JenkinsPassword')]) {
                        env.VAULT_ADDR = 'https://vault.yamoney.ru'
                        env.VAULT_AUTHTYPE = 'ldap'
                        env.VAULT_USER = "${JenkinsUser}"
                        env.VAULT_PASSWORD = "${JenkinsPassword}"
                    }
                    ansiblePlaybook credentialsId: credentials.jenkins,
                                    playbook: './ansible/site.yml',
                                    colorized: true
                    notifyBitbucket(buildStatus: 'INPROGRESS')
                }
                stage('helm lint') {
                    echo 'Linting helm'
                    sh '''
                    cd ./deploy &&
                    helm lint . --kubeconfig ../ansible/kubeconfig.yml -f values.yaml -f ../ansible/secret_values.yml -n releasebot
                    '''
                    notifyBitbucket(buildStatus: 'INPROGRESS')
                }
                stage('helm install') {
                    sh '''
                    cd ./deploy &&
                    helm upgrade --install releasebot-assistant . --kubeconfig ../ansible/kubeconfig.yml -f ../ansible/secret_values.yml -f ../tag-values.yaml -n releasebot
                    '''
                }
                notifyBitbucket(buildStatus: 'SUCCESSFUL')
                currentBuild.result = 'SUCCESS'
            }
        } catch(Exception e) {
                println "Error: ${e.message}"
                notifyBitbucket(buildStatus: 'FAILED')
                currentBuild.result = 'FAILED'
        } finally {
                sh '''
                rm -rf ${home_dir}/ansible
                '''
        }
    }
}
