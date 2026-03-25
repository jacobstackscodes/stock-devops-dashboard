pipeline {
    agent any

    stages {

        stage('Build Docker Images') {
            steps {
                sh 'docker compose build'
            }
        }

        stage('Restart Application Containers') {
            steps {
                sh 'docker compose down --remove-orphans || true'
                sh 'docker compose up -d --build'
            }
        }

        stage('Verify Running Containers') {
            steps {
                sh 'docker ps'
            }
        }

    }
}