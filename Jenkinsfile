pipeline {
agent any

environment {
    DOCKER_IMAGE = "jacobstackscodes/stock-devops-backend:latest"
}

stages {

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
            aquasec/trivy:0.69.3 image stock-devops-pipeline-backend
            '''
        }
    }

    stage('Tag Docker Image') {
        steps {
            sh 'docker tag stock-devops-pipeline-backend:latest $DOCKER_IMAGE'
        }
    }

    stage('Push Image to DockerHub') {
        steps {
            withCredentials([usernamePassword(credentialsId: 'dockerhub-creds', usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
                sh '''
                echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin
                docker push $DOCKER_IMAGE
                docker logout
                '''
            }
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
