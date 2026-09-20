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

say "Public HTTPS URL"
aws lambda create-function-url-config --function-name "$FN" --region "$REGION" \
  --auth-type NONE --cors '{"AllowOrigins":["*"],"AllowMethods":["*"],"AllowHeaders":["*"]}' \
  >/dev/null 2>&1 || true
aws lambda add-permission --function-name "$FN" --region "$REGION" \
  --statement-id public-url --action lambda:InvokeFunctionUrl \
  --principal '*' --function-url-auth-type NONE >/dev/null 2>&1 || true

URL="$(aws lambda get-function-url-config --function-name "$FN" --region "$REGION" \
        --query FunctionUrl --output text)"
printf '\n\033[1;32m  %s\033[0m\n\n' "$URL"
rm -rf "$BUILD"
