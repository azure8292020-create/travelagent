# ✈️ Serverless Flight Hunter

Automated flight price tracker and deal hunter, built with a serverless architecture on AWS.

This application allows users to set flight search criteria (origin, destination, date). It automatically polls for prices using the Skyscanner API (via RapidAPI), analyzes deals using OpenAI, and sends SMS/Email alerts via Amazon SNS when a good price is found.

## 🏗️ Architecture

The system is fully serverless and event-driven:

*   **Frontend**: Static HTML/JS hosted on **Amazon S3**.
*   **API**: **Amazon API Gateway** (HTTP API) handles user requests.
*   **Compute**: **AWS Lambda** (packaged as a Docker container) runs the scraping and logic.
*   **Database**: **Amazon DynamoDB** stores active search requests.
*   **Orchestration**: **Amazon EventBridge Scheduler** triggers the Lambda function every hour to check for new prices.
*   **Notifications**: **Amazon SNS** sends alerts to users.
*   **Configuration**: API keys are securely stored in **AWS Systems Manager (SSM) Parameter Store**.

### Diagram

```mermaid
graph TD
    subgraph Users
        User[User / Traveler]
    end

    subgraph ExternalServices ["External Services"]
        Skyscanner[RapidAPI / Skyscanner]
        OpenAI[OpenAI API]
    end

    subgraph AWSCloud ["AWS Cloud"]
        subgraph FrontendHosting ["Frontend Hosting"]
            S3[S3 Bucket<br/>(Static Website Hosting)]
        end

        subgraph EntryPoints ["Entry Points"]
            APIG[API Gateway<br/>(HTTP API)]
            EventBridge[EventBridge Scheduler<br/>(Hourly Trigger)]
        end

        subgraph Compute ["Compute"]
            ECR[Amazon ECR<br/>(Docker Image Registry)]
            Lambda[AWS Lambda<br/>(Scraper & Logic)<br/>Runtime: Docker]
        end

        subgraph StorageConfig ["Storage & Config"]
            DynamoDB[DynamoDB<br/>(Active Searches)]
            SSM[Systems Manager<br/>Parameter Store]
        end

        subgraph Notifications ["Notifications"]
            SNS[Amazon SNS<br/>(Flight Alerts)]
        end
    end

    %% Flows
    User -->|Visits| S3
    User -->|Submits Request| APIG
    APIG -->|Invokes| Lambda
    EventBridge -->|Triggers (Hourly)| Lambda
    
    ECR -.->|Pulls Image| Lambda
    
    Lambda -->|Reads/Writes| DynamoDB
    Lambda -->|Fetches Keys| SSM
    Lambda -->|Queries Flights| Skyscanner
    Lambda -->|Analyzes Deals| OpenAI
    Lambda -->|Publishes Alert| SNS
    
    SNS -.->|SMS/Email| User

    classDef service fill:#f9f9f9,stroke:#333,stroke-width:2px;
    classDef aws fill:#FF9900,stroke:#232F3E,stroke-width:2px,color:white;
    classDef external fill:#ddd,stroke:#333,stroke-dasharray: 5 5;
    
    class S3,APIG,EventBridge,Lambda,DynamoDB,SSM,SNS,ECR aws;
    class Skyscanner,OpenAI external;
```

## 🚀 Deployment Guide

### Prerequisites
1.  **AWS Account** with CLI configured.
2.  **Docker Desktop** installed.
3.  **RapidAPI Key** (subscribed to Skyscanner API).
4.  **OpenAI API Key**.

### Step 1: Push Docker Image to ECR
1.  Create an ECR repository:
    ```bash
    aws ecr create-repository --repository-name flight-hunter-worker
    ```
2.  Build and push the image (from the `docker` directory):
    ```bash
    cd docker
    aws ecr get-login-password --region <REGION> | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com
    docker build -t flight-hunter-worker .
    docker tag flight-hunter-worker:latest <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/flight-hunter-worker:latest
    docker push <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/flight-hunter-worker:latest
    ```

### Step 2: Deploy Backend Infrastructure
Deploy the `components.yaml` CloudFormation stack.
```bash
aws cloudformation deploy \
  --template-file components.yaml \
  --stack-name flight-hunter-backend \
  --parameter-overrides ECRImageUri=<YOUR_ECR_IMAGE_URI> \
  --capabilities CAPABILITY_IAM
```

### Step 3: Configure Secrets
Store your API keys in SSM Parameter Store so the Lambda can access them securely.
```bash
aws ssm put-parameter --name "/flights/rapidapi_key" --value "YOUR_RAPIDAPI_KEY" --type SecureString
aws ssm put-parameter --name "/flights/openai_key" --value "YOUR_OPENAI_KEY" --type SecureString
```

### Step 4: Deploy Frontend
1.  Deploy the S3 bucket stack:
    ```bash
    aws cloudformation deploy \
      --template-file flightprojectbucket.yaml \
      --stack-name flight-hunter-frontend \
      --parameter-overrides BucketName=<UNIQUE_BUCKET_NAME>
    ```
2.  **Update `Index.html`**: Replace the `API_URL` placeholder with the ApiUrl output from Step 2.
3.  Upload the frontend:
    ```bash
    aws s3 cp Index.html s3://<UNIQUE_BUCKET_NAME>/Index.html
    ```

## 🛠️ Usage
1.  Open the S3 Website URL.
2.  Enter your destination, dates, and phone number.
3.  Click "Start Tracking".
4.  You will receive an SMS/Email to confirm your subscription to the SNS topic. **Confirm it!**
5.  Wait for alerts when prices drop!

## 📂 Project Structure
*   `flightprojectbucket.yaml`: CFN template for S3 frontend hosting.
*   `components.yaml`: CFN template for backend resources (Lambda, DynamoDB, API Gateway, etc.).
*   `docker/`: Contains the `Dockerfile` and Python code (`lambda_function.py`) for the worker.
*   `Index.html`: The user interface.
