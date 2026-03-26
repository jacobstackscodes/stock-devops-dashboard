pipeline {
agent any
environment {
    DOCKER_IMAGE = "stock-devops-pipeline-backend:latest"
}

stages {

    stage('Checkout SCM') {
        steps {
            git branch: 'main', url: 'https://github.com/jacobstackscodes/stock-devops-dashboard'
        }
    }

    stage('Build Docker Images') {
        steps {
            sh 'docker compose build'
        }
    }

    stage('Security Scan - Trivy') {
        steps {
            sh '''
            docker run --rm \
            -v /var/run/docker.sock:/var/run/docker.sock \
            aquasec/trivy:0.53.0 image stock-devops-pipeline-backend
            '''
        }
    }

    stage('Restart Application Containers') {
        steps {
            sh 'docker compose down || true'
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
