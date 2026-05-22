#!/bin/sh
# Deploy/Destroy script for ACI - streams terraform output to log file in real-time
# Each line of terraform output is immediately written to the JSON log on the file share,
# so users can see progress by refreshing the logs page.

START_TIME=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
ACTION="${TF_ACTION:-apply}"
LOG_FILE="/mnt/templates/_logs/${DEPLOY_ID}.json"
LINES_FILE="/tmp/log_lines.txt"

mkdir -p /mnt/templates/_logs
: > "$LINES_FILE"

# ============================================================
# Logging functions
# ============================================================
add_line() {
  printf '%s\n' "$1" >> "$LINES_FILE"
}

flush_log() {
  local status="$1"
  # Build JSON log from accumulated lines
  local json_lines=""
  while IFS= read -r line || [ -n "$line" ]; do
    escaped=$(printf '%s' "$line" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g')
    if [ -z "$json_lines" ]; then
      json_lines="\"${escaped}\""
    else
      json_lines="${json_lines},\"${escaped}\""
    fi
  done < "$LINES_FILE"

  printf '{"deploy_id":"%s","template_id":"%s","action":"%s","status":"%s","started_at":"%s","logs":[%s]}\n' \
    "$DEPLOY_ID" "$TEMPLATE_ID" "$ACTION" "$status" "$START_TIME" "$json_lines" > "$LOG_FILE"
}

# Run a terraform command and stream its output line-by-line to the log.
# Writes output to a temp file so we can check success/failure after.
# Usage: run_streaming <command> [args...]
run_streaming() {
  local outfile="/tmp/tf_cmd_output.txt"
  : > "$outfile"

  # Use a fifo to stream output while also capturing it
  local fifo="/tmp/tf_fifo"
  rm -f "$fifo"
  mkfifo "$fifo"

  # Run terraform in background, output to fifo
  "$@" > "$fifo" 2>&1 &
  local cmd_pid=$!

  # Read from fifo line by line, stream to log
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s\n' "$line" >> "$outfile"
    add_line "$line"
    flush_log "running"
  done < "$fifo"

  wait $cmd_pid
  local rc=$?

  rm -f "$fifo"
  return $rc
}

# ============================================================
# Start
# ============================================================
echo "=== Starting ${ACTION} ==="

add_line "Container started at ${START_TIME}"
add_line "Template: ${TEMPLATE_ID}"
add_line "Deploy ID: ${DEPLOY_ID}"
add_line "Action: ${ACTION}"
add_line ""
flush_log "running"

# Extract resource_group_name from terraform.tfvars for state key
RG_NAME=$(grep 'resource_group_name' terraform.tfvars | head -1 | sed 's/.*= *"\(.*\)"/\1/')
if [ -z "$RG_NAME" ]; then
  RG_NAME="${DEPLOY_ID}"
fi
STATE_KEY="${TEMPLATE_ID}/${RG_NAME}.tfstate"

add_line "State key: ${STATE_KEY}"
add_line ""
flush_log "running"

# ============================================================
# Terraform init (streamed)
# ============================================================
add_line "=== terraform init ==="
flush_log "running"

run_streaming terraform init -no-color -input=false \
  -backend-config="storage_account_name=${STORAGE_ACCOUNT_NAME}" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=${STATE_KEY}" \
  -backend-config="access_key=${STORAGE_ACCOUNT_KEY}"
INIT_RC=$?

if [ $INIT_RC -ne 0 ]; then
  add_line ""
  add_line "FAILED: terraform init failed (exit code ${INIT_RC})"
  flush_log "failed"
  exit 1
fi

add_line ""
add_line "Init successful."
add_line ""
flush_log "running"

# ============================================================
# Terraform apply/destroy (streamed)
# ============================================================
if [ "$ACTION" = "destroy" ]; then
  add_line "=== terraform destroy ==="
  flush_log "running"
  run_streaming terraform destroy -no-color -input=false -auto-approve
  TF_RC=$?
else
  add_line "=== terraform apply ==="
  flush_log "running"
  run_streaming terraform apply -no-color -input=false -auto-approve
  TF_RC=$?
fi

if [ $TF_RC -ne 0 ]; then
  add_line ""
  add_line "FAILED: terraform ${ACTION} failed (exit code ${TF_RC})"
  flush_log "failed"
  exit 1
fi

add_line ""
add_line "${ACTION} successful."
add_line ""

# ============================================================
# Outputs (only for apply)
# ============================================================
if [ "$ACTION" = "apply" ]; then
  add_line "=== Outputs ==="
  flush_log "running"
  run_streaming terraform output -no-color
  add_line ""
fi

add_line "=== ${ACTION} Complete ==="
flush_log "completed"
echo "=== ${ACTION} Complete ==="
