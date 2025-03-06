#!/usr/bin/env groovy

String cron_string = ""
String poll_cron_string = ""

if ( BRANCH_NAME == "development" ) {
    cron_string = "0 4 * * *"
    poll_cron_string = "*/15 * * * *"
}

if ( BRANCH_NAME == "test" )  {cron_string = "0 5 * * *"  }
if ( BRANCH_NAME == "production" ) { cron_string = "" }

pipeline {
    agent { label 'sd-jenkins-agent' }

    options {
        disableConcurrentBuilds()
        buildDiscarder(logRotator( numToKeepStr: '10', daysToKeepStr: '7'))
    }            

    triggers {
        cron(cron_string)
        pollSCM(poll_cron_string)
    } 

    stages {

// ----- BUILD -----
        stage('Build') {
            options { timeout(time: 45, unit: 'MINUTES') }

            steps {
                sh "export IMG_VERSION=${env.BUILD_ID} && make APPLICATION=fraud jenkins-build"
            }
        }

        stage('Test') {
            options { timeout(time: 45, unit: 'MINUTES') }

            steps {
                sh "export IMG_VERSION=${env.BUILD_ID} && make APPLICATION=fraud jenkins-test"
            }
        }

        stage('Build for production') {
            options { timeout(time: 45, unit: 'MINUTES') }

            steps {
                sh "export IMG_VERSION=${env.BUILD_ID} && make APPLICATION=fraud jenkins-build-prod"
                sh "export IMG_VERSION=${env.BUILD_ID} && make APPLICATION=fraud jenkins-repo-push"
            }
        }

// ----- DEVELOPMENT ENVIRONMENT (Development) -----
        stage('Development Environment') {
            when { branch "development" }

            steps {
                echo 'Deploying to development environment'
                sh "curl --fail -X POST http://porthost:9000/api/webhooks/e77020bc-aee7-483b-bc95-e520129628fc" // fraud external
                sh "curl --fail -X POST http://porthost:9000/api/webhooks/e255bc01-8911-4131-81ac-c9587822d75d" // fraud internal
            }
            
        }

// ----- TEST ENVIRONMENT -----
        stage('Test Environment') {
            when { branch "test" }

            steps {
                echo 'Deploying to test environment'
                sh "curl --fail -X POST http://porthost:9000/api/webhooks/55738fdb-5685-4c64-a0db-4adaeb1a93db" // fraud external
                sh "curl --fail -X POST http://porthost:9000/api/webhooks/b2423b29-63df-4917-abdc-d0a6e63bfdb4" // fraud internal
            }
        }

// ----- PRODUCTION ENVIRONMENT -----
        stage('Production Environment') {
            when { branch "production" }

            steps {
                echo 'Deploying to production environment'
                // No automated deployment to production
            }
        }
    }

     post {
        success {
            echo 'Successfullly build!'
        }
        failure {  
            mail bcc: '', body: "<b>Build failed</b><br>Project: ${env.JOB_NAME} <br>Build Number: ${env.BUILD_NUMBER} <br> Build url: ${env.BUILD_URL}", cc: '', charset: 'UTF-8', from: 'jenkins@softdesign.dk', mimeType: 'text/html', replyTo: '', subject: "ERROR CI: Project name -> ${env.JOB_NAME}", to: "jenkins@softdesign.dk";
        }
        aborted {
            script {
                currentBuild.result = 'ABORTED'
            }
        }
    }
}
