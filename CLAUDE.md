# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Flight Hunter** is a serverless, event-driven flight price tracker built on AWS. Users submit flight search requests via a web UI, and the system polls for deals hourly, using an LLM to filter results against user preferences before sending SMS/email alerts.

## Architecture

```
Frontend (Index.html / S3)
    │
    ▼
API Gateway (POST /send-otp)
    │
    ▼
Lambda (Docker container on ECR)
    ├── SEND_OTP → generate OTP → SNS SMS → DynamoDB (5-min TTL)
    ├── VERIFY_OTP → validate OTP → save search to DynamoDB (7-day TTL)
    ├── ANALYZE_REQUEST → Gemini LLM analysis
    └── (EventBridge hourly) → poll DynamoDB → Fly-Scraper API → Gemini filter → SNS alert
```

**Key technologies:** AWS Lambda (Docker), DynamoDB, SNS, EventBridge, API Gateway v2, SSM Parameter Store, CloudFormation, Playwright, Google Gemini 1.5 Flash, Fly-Scraper via RapidAPI.

## Key Files

| File | Purpose |
|------|---------|
| `docker/lambda_function.py` | Central Lambda handler — all backend logic |
| `docker/local_test.py` | Local test runner for flight search + AI analysis |
| `docker/requirements.txt` | Python dependencies |
| `docker/dockerfile` | Container image (Playwright Python 1.40.0-jammy base) |
| `components.yaml` | CloudFormation — all backend AWS resources |
| `flightprojectbucket.yaml` | CloudFormation — S3 static hosting for frontend |
| `Index.html` | Frontend UI (vanilla JS, voice input, chat-style interface) |
| `parametersforapi.md` | Fly-Scraper API parameter reference |

## Local Development & Testing

```bash
# Run local tests (flight search + Gemini analysis)
cd docker
python local_test.py
```

The test script exercises entity ID resolution (airport code → API ID), Skyscanner/Fly-Scraper API calls, and Gemini-based flight deal evaluation without deploying to AWS. Edit the `test_search` dict at the bottom of `local_test.py` to change test parameters.

## Build & Deploy

```bash
# Build Docker image
cd docker
docker build -t flight-hunter-worker .

# Push to ECR (replace placeholders)
aws ecr get-login-password --region <REGION> | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com
docker tag flight-hunter-worker:latest <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/flight-hunter-worker:latest
docker push <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/flight-hunter-worker:latest

# Deploy backend
aws cloudformation deploy \
  --template-file components.yaml \
  --stack-name flight-hunter-backend \
  --parameter-overrides ECRImageUri=<YOUR_ECR_IMAGE_URI> \
  --capabilities CAPABILITY_IAM

# Store secrets in SSM
aws ssm put-parameter --name "/flights/rapidapi_key" --value "KEY" --type SecureString
aws ssm put-parameter --name "/flights/gemini_key"   --value "KEY" --type SecureString

# Deploy frontend
aws cloudformation deploy \
  --template-file flightprojectbucket.yaml \
  --stack-name flight-hunter-frontend \
  --parameter-overrides BucketName=<UNIQUE_BUCKET_NAME>
# Then upload Index.html with the correct API Gateway URL set as API_URL
```

## Lambda Action Routing

The Lambda dispatches on the `action` field in the POST body:

| Action | Behavior |
|--------|----------|
| `SEND_OTP` | Generate + SMS OTP via SNS; store in DynamoDB (5-min TTL) |
| `VERIFY_OTP` | Validate OTP; persist full search to DynamoDB (7-day TTL) |
| `ANALYZE_REQUEST` | Run user request through Gemini for analysis |
| `SCRAPE_ONE` | (Reserved) Playwright-based scraping |
| _(no body)_ | EventBridge hourly trigger — poll all active searches |

## DynamoDB Schema

Table: `flight-hunter-ActiveSearches` (partition key: `contact`)

Relevant fields: `contact`, `username`, `src`, `dst`, `date`, `return`, `adults`, `children`, `infants`, `cabinClass`, `stops`, `notes`, `timestamp`, `ttl`

## AI Integration

- **Model:** `gemini-1.5-flash` (loaded via `google-generativeai`)
- **Prompt contract:** Gemini must return `{"match": bool, "sms": "<160-char message>"}` — keep this format stable when modifying prompts
- The LLM also interprets API error responses and formats human-readable explanations
- `openai_key` is stored in SSM but not currently used in the active code path

## Frontend Notes

- `Index.html` contains a hardcoded `API_URL` constant that must be updated after each backend deployment
- Voice input uses `webkitSpeechRecognition` (Chrome/Safari only)
- OTP flow: submit form → `SEND_OTP` → user enters OTP → `VERIFY_OTP` saves search
