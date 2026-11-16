#!/usr/bin/env bash
# Creates the GCP resources for the prototype. You can run it again: each step
# checks if the resource is already there.
#
#   PROJECT_ID=<your-project-id> scripts/setup-gcp.sh
#
# Result:
#   - a project in the BigQuery sandbox (no billing account),
#   - the service account dca-agent with read-only BigQuery rights,
#   - the dataset dca_views for the threshold views (ADR 0005),
#   - your user can impersonate dca-agent (no key file).
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID or GOOGLE_CLOUD_PROJECT}"
SA_NAME="${SA_NAME:-dca-agent}"
DATASET="${DATASET:-dca_views}"
# thelook_ecommerce is in the US multi-region. The views must be in the same location.
LOCATION="${LOCATION:-US}"

USER_EMAIL="$(gcloud config get-value account 2>/dev/null)"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Project: ${PROJECT_ID}, user: ${USER_EMAIL}, service account: ${SA_EMAIL}"

if ! gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud projects create "${PROJECT_ID}" --name="data-chat-assistant"
fi
gcloud config set project "${PROJECT_ID}"

gcloud services enable \
  bigquery.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  generativelanguage.googleapis.com \
  --project "${PROJECT_ID}"

if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --project "${PROJECT_ID}" \
    --display-name="Data Chat Assistant agent (read-only BigQuery)"
fi

# The agent can run query jobs in the project. It cannot create or change tables.
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.jobUser" \
  --condition=None >/dev/null

# Your user can get short-lived tokens for the service account.
gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --project "${PROJECT_ID}" \
  --member="user:${USER_EMAIL}" \
  --role="roles/iam.serviceAccountTokenCreator" >/dev/null

if ! bq --project_id="${PROJECT_ID}" show --dataset "${PROJECT_ID}:${DATASET}" >/dev/null 2>&1; then
  bq --project_id="${PROJECT_ID}" --location="${LOCATION}" mk --dataset \
    --description="Threshold views for the data chat assistant (ADR 0005)" \
    "${PROJECT_ID}:${DATASET}"
fi

# The agent can read the views in this dataset only. The public dataset is readable by all users.
# Dataset IAM bindings through bq need allowlisting, so we add a READER access entry.
ACCESS_FILE="$(mktemp)"
bq --project_id="${PROJECT_ID}" show --format=prettyjson "${PROJECT_ID}:${DATASET}" > "${ACCESS_FILE}"
python3 - "${ACCESS_FILE}" "${SA_EMAIL}" <<'PY'
import json, sys
path, sa = sys.argv[1], sys.argv[2]
dataset = json.load(open(path))
entry = {"role": "READER", "userByEmail": sa}
if entry not in dataset["access"]:
    dataset["access"].append(entry)
json.dump({"access": dataset["access"]}, open(path, "w"))
PY
bq --project_id="${PROJECT_ID}" update --source "${ACCESS_FILE}" "${PROJECT_ID}:${DATASET}" >/dev/null
rm -f "${ACCESS_FILE}"

echo
echo "Done. Next steps:"
echo "  gcloud auth application-default login --impersonate-service-account=${SA_EMAIL}"
echo "  Put GOOGLE_CLOUD_PROJECT=${PROJECT_ID} in .env"
