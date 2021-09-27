node('docker') {
    ansiColor('xterm') {
        cleanWs()
        def dockerImageUrl = "docker.nexus.yamoney.ru/yamoney/ubuntu-18-04-ym-cloud"
        def version
        def branchName = 'master'
        def dockerRepoURL = 'docker-ym.nexus.yamoney.ru'
        def credentials = [bitbucket: '45d976f8-a1fb-4b55-892e-a7add19dc44f',
                       nexus: 'svcJenkinsProdUser',
                       vault: 'svcJenkinsProdUser'
                       ]
        def env = 'prod'

        try {
            docker.image("${dockerImageUrl}").inside("-v /var/run/docker.sock:/var/run/docker.sock --net=host --group-add docker") {
                stage('checkout') {
                    echo 'Fetching releasebot source from git'
                    checkout ([$class: 'GitSCM',
                               branches: [[name: branchName]],
                               extensions: [[$class: 'RelativeTargetDirectory', relativeTargetDir: '']],
                               userRemoteConfigs: [[credentialsId: credentials.bitbucket,
                               url: 'ssh://git@bitbucket.yooteam.ru/infra-services/releasebot-assistant.git']]])
                    notifyBitbucket(buildStatus: 'INPROGRESS')
                }

                stage('prepare configs') {
                    withCredentials([usernamePassword(credentialsId: credentials.vault, usernameVariable: 'JenkinsUser', passwordVariable: 'JenkinsPassword')]) {
                        env.VAULT_ADDR = 'https://vault.yamoney.ru'
                        env.VAULT_AUTHTYPE = 'ldap'
                        env.VAULT_USER = "${JenkinsUser}"
                        env.VAULT_PASSWORD = "${JenkinsPassword}"
                    }
                    ansiblePlaybook credentialsId: credentials.jenkins,
                                    playbook: './ansible/site.yml',
                                    extras: "-e @./ansible/group_vars/${admintools_env}.yml"
                    notifyBitbucket(buildStatus: 'INPROGRESS')
                }

                stage('build releasebot') {
                    withDockerRegistry([ url: "https://${dockerRepoURL}", credentialsId: "${credentials.nexus}" ]) {
                        version = readFile 'src/version.txt'
                        sh "DOCKER_SERVER=https://${dockerRepoURL} docker build -f admintools-python.Dockerfile . -t ${dockerRepoURL}/yamoney/yamoney-backend-admintools:${version}"
                        sh "DOCKER_SERVER=https://${dockerRepoURL} docker push ${dockerRepoURL}/yamoney/yamoney-backend-admintools:${version}"
                        sh "DOCKER_SERVER=https://${dockerRepoURL} docker build -f admintools-haproxy.Dockerfile . -t ${dockerRepoURL}/yamoney/yamoney-backend-admintools-haproxy:${version}"
                        sh "DOCKER_SERVER=https://${dockerRepoURL} docker push ${dockerRepoURL}/yamoney/yamoney-backend-admintools-haproxy:${version}"
                        notifyBitbucket(buildStatus: 'INPROGRESS')
                    }
                }

                stage('run on server') {
                   env.KUBECONFIG = './kubeconfig'
                   env.ADMINTOOLS_VERSION = "${version}"
                   env.HAPROXY_VERSION = "${version}"
                   env.VAULT_TOKEN = readFile 'chart/token'
                   if (!is_prod) {
                       sh "cd chart && helmfile -e ${admintools_env} destroy && helmfile -e ${admintools_env} apply"
                   } else {
                       sh "cd chart && helmfile -e ${admintools_env} apply"
                   }
                   sh 'rm -rf ./*'
                }
                currentBuild.result = 'SUCCESS'
                notifyBitbucket(buildStatus: 'SUCCESSFUL')
            }
        } catch(err) {
            echo "Exception thrown:\n ${err}"
            notifyBitbucket(buildStatus: 'FAILED')
            currentBuild.result = 'FAILED'
        } finally {
            echo 'remove artifacts'
            sh "rm -rf ${WORKSPACE}/*"
        }
    }
}
