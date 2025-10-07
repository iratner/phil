### Docker Deployment
```bash
docker build --platform linux/amd64 -t gcr.io/twa-developer-ilya-test/bosun-service:v0.0.9 .
```

```bash
docker push gcr.io/twa-developer-ilya-test/bosun-service:v0.0.9
```

```bash
cloud run deploy bosun-service --image gcr.io/twa-developer-ilya-test/bosun-service:v0.0.9 --platform managed --region us-east1 --timeout 200s --port 8080
```

### Service Account Setup
```bash
gcloud iam service-accounts create SERVICE_ACCOUNT_NAME \
  --description="DESCRIPTION" \
  --display-name="DISPLAY_NAME"
```

### Set Project
```bash
 gcloud config set project PROJECT_ID
```


### Gateway Setup
```bash
gcloud api-gateway api-configs create CONFIG_ID \
--api=SERVICE_ID --openapi-spec=PATH_TO_SPEC \
--project=PROJECT --backend-auth-service-account=SERVICE_ACCOUNT_EMAIL
```

```bash
gcloud api-gateway gateways create GATEWAY_ID \
--api=SERVICE_ID --api-config=CONFIG_ID \
--location=us-west2 --project=PROJECT
```


```bash
gcloud api-gateway gateways update GATEWAY_ID \
--api=SERVICE_ID --api-config=CONFIG_ID --location=us-east1 --project=PROJECT
```