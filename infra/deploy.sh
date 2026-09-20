#!/usr/bin/env bash
# One-shot deploy: DynamoDB table + IAM role + Lambda + public Function URL.
# Function URLs give HTTPS for free, which the Web Speech API requires — the
# microphone will not work over plain http on a public address.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
NAME=khatam
TABLE="${NAME}-events"
ROLE="${NAME}-lambda-role"
FN="${NAME}-api"
MODEL="${KHATAM_BEDROCK_MODEL:-us.anthropic.claude-opus-5}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

say(){ printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "DynamoDB table"
if out=$(aws dynamodb create-table --table-name "$TABLE" --region "$REGION" \
  --attribute-definitions AttributeName=shop_id,AttributeType=S AttributeName=sk,AttributeType=S \
  --key-schema AttributeName=shop_id,KeyType=HASH AttributeName=sk,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST 2>&1); then
  echo "created"
elif grep -q ResourceInUseException <<<"$out"; then
  echo "already exists"
else
  echo "$out" >&2; exit 1      # AccessDenied and friends must not look like success
fi
aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION"

say "IAM role"
if out=$(aws iam create-role --role-name "$ROLE" --assume-role-policy-document '{
  "Version":"2012-10-17",
  "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]
}' 2>&1); then
  echo "created"
elif grep -q EntityAlreadyExists <<<"$out"; then
  echo "already exists"
else
  echo "$out" >&2; exit 1
fi

aws iam attach-role-policy --role-name "$ROLE" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null
aws iam put-role-policy --role-name "$ROLE" --policy-name khatam-data --policy-document "{
  \"Version\":\"2012-10-17\",
  \"Statement\":[
    {\"Effect\":\"Allow\",
     \"Action\":[\"dynamodb:PutItem\",\"dynamodb:Query\",\"dynamodb:BatchWriteItem\",\"dynamodb:DeleteItem\"],
     \"Resource\":\"arn:aws:dynamodb:${REGION}:${ACCOUNT}:table/${TABLE}\"},
    {\"Effect\":\"Allow\",\"Action\":[\"bedrock:InvokeModel\"],\"Resource\":\"*\"}
  ]}" >/dev/null
echo "policies attached"

say "Building package"
BUILD="$(mktemp -d)"
# pydantic_core is a compiled extension: building on macOS ARM produces a
# wheel Lambda cannot import. Pin the target platform explicitly.
"$ROOT/.venv/bin/pip" install -q --target "$BUILD" \
  --platform manylinux2014_x86_64 --python-version 3.12 \
  --implementation cp --only-binary=:all: \
  fastapi mangum pydantic strands-agents 2>&1 | tail -3
# boto3/botocore ship in the Lambda runtime; dropping them halves the zip.
rm -rf "$BUILD"/boto3* "$BUILD"/botocore* "$BUILD"/pip* "$BUILD"/setuptools*
cp -r "$ROOT/backend/khatam" "$ROOT/backend/api.py" "$BUILD/"
mkdir -p "$BUILD/data" "$BUILD/frontend"
cp "$ROOT/data/catalog.json" "$BUILD/data/"
cp -r "$ROOT/frontend/." "$BUILD/frontend/"
find "$BUILD" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
( cd "$BUILD" && zip -qr /tmp/khatam.zip . )
echo "zip: $(du -h /tmp/khatam.zip | cut -f1)"

say "Lambda"
ENVJSON="Variables={KHATAM_TABLE=$TABLE,KHATAM_BEDROCK_MODEL=$MODEL}"
if aws lambda get-function --function-name "$FN" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FN" --zip-file fileb:///tmp/khatam.zip \
    --region "$REGION" >/dev/null
  aws lambda wait function-updated --function-name "$FN" --region "$REGION"
  aws lambda update-function-configuration --function-name "$FN" --region "$REGION" \
    --timeout 30 --memory-size 1024 --environment "$ENVJSON" >/dev/null
  echo "updated"
else
  echo "waiting for the new IAM role to propagate…"; sleep 12
  aws lambda create-function --function-name "$FN" --region "$REGION" \
    --runtime python3.12 --handler api.handler \
    --role "arn:aws:iam::${ACCOUNT}:role/${ROLE}" \
    --zip-file fileb:///tmp/khatam.zip --timeout 30 --memory-size 1024 \
    --environment "$ENVJSON" >/dev/null
  echo "created"
fi
aws lambda wait function-updated --function-name "$FN" --region "$REGION"

say "Public HTTPS URL (API Gateway)"
# Not a Lambda Function URL: those return 403 on this account despite a
# correct resource policy. HTTPS is non-negotiable either way — the Web
# Speech API will not open a microphone on a plain-http origin.
API_ID="$(aws apigatewayv2 get-apis --region "$REGION" \
  --query "Items[?Name=='${NAME}-http'].ApiId | [0]" --output text)"
if [ "$API_ID" = "None" ] || [ -z "$API_ID" ]; then
  API_ID="$(aws apigatewayv2 create-api --region "$REGION" --name "${NAME}-http" \
    --protocol-type HTTP \
    --cors-configuration AllowOrigins='*',AllowMethods='*',AllowHeaders='*' \
    --query ApiId --output text)"
  echo "api created: $API_ID"
else
  echo "api exists: $API_ID"
fi

FN_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FN}"
# create-integration rejects a bare function ARN; it wants the invoke URI.
INT_ID="$(aws apigatewayv2 get-integrations --region "$REGION" --api-id "$API_ID" \
  --query 'Items[0].IntegrationId' --output text 2>/dev/null)"
if [ "$INT_ID" = "None" ] || [ -z "$INT_ID" ]; then
  INT_ID="$(aws apigatewayv2 create-integration --region "$REGION" --api-id "$API_ID" \
    --integration-type AWS_PROXY --payload-format-version 2.0 \
    --integration-uri "arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/${FN_ARN}/invocations" \
    --query IntegrationId --output text)"
  for rk in 'ANY /' 'ANY /{proxy+}'; do
    aws apigatewayv2 create-route --region "$REGION" --api-id "$API_ID" \
      --route-key "$rk" --target "integrations/$INT_ID" >/dev/null
  done
  aws apigatewayv2 create-stage --region "$REGION" --api-id "$API_ID" \
    --stage-name '$default' --auto-deploy >/dev/null
  echo "routes created"
fi

# Re-add every time: a stale statement from a previous API id silently blocks
# invocation, and add-permission refuses to overwrite a duplicate statement id.
aws lambda remove-permission --region "$REGION" --function-name "$FN" \
  --statement-id apigw-invoke >/dev/null 2>&1 || true
aws lambda add-permission --region "$REGION" --function-name "$FN" \
  --statement-id apigw-invoke --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT}:${API_ID}/*/*" >/dev/null

URL="$(aws apigatewayv2 get-api --api-id "$API_ID" --region "$REGION" \
        --query ApiEndpoint --output text)"
printf '\n\033[1;32m  %s\033[0m\n\n' "$URL"
rm -rf "$BUILD"
