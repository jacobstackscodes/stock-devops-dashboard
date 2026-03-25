pipeline {
    agent any

    stages {

        stage('Checkout SCM') {
            steps {
                git 'https://github.com/jacobstackscodes/stock-devops-dashboard'
            }
        }

        stage('Build Docker Images') {
            steps {
                sh 'docker compose build'
            }
        }

        stage('Security Scan - Trivy') {
            steps {
                sh """
                docker run --rm \
                -v /var/run/docker.sock:/var/run/docker.sock \
                aquasec/trivy:0.69.3 image stock-devops-pipeline-backend
                """
            }
        }

        stage('Restart Application Containers') {
            steps {
                sh 'docker compose down --remove-orphans'
                sh 'docker compose up -d'
            }
        }

        stage('Verify Running Containers') {
            steps {
                sh 'docker ps'
            }
        }

    }
}