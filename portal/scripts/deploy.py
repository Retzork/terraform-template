"""
Deploy script that runs inside ACI container.
Executes terraform init + apply and streams logs to Azure Blob Storage.
"""
import os
import sys
import json
import subprocess
from datetime import datetime
from azure.storage.blob import BlobServiceClient

# Environment variables
DEPLOY_ID = os.environ["DEPLOY_ID"]
TEMPLATE_ID = os.environ["TEMPLATE_ID"]
STORAGE_ACCOUNT_NAME = os.environ["STORAGE_ACCOUNT_NAME"]
STORAGE_ACCOUNT_KEY = os.environ["STORAGE_ACCOUNT_KEY"]
LOGS_CONTAINER = os.environ["LOGS_CONTAINER"]

WORK_DIR = "/work"

# Connect to blob storage
connection_string = (
    f"DefaultEndpointsProtocol=https;"
    f"AccountName={STORAGE_ACCOUNT_NAME};"
    f"AccountKey={STORAGE_ACCOUNT_KEY};"
    f"EndpointSuffix=core.windows.net"
)
blob_service = BlobServiceClient.from_connection_string(connection_string)
container_client = blob_service.get_container_client(LOGS_CONTAINER)


def update_log(status: str, logs: list, outputs=None):
    """Write current status to blob storage."""
    log_data = {
        "deploy_id": DEPLOY_ID,
        "template_id": TEMPLATE_ID,
        "status": status,
        "started_at": START_TIME,
        "logs": logs
    }
    if outputs:
        log_data["outputs"] = outputs
    if status in ("completed", "failed", "timeout"):
        log_data["completed_at"] = datetime.utcnow().isoformat()

    blob = container_client.get_blob_client(f"{DEPLOY_ID}.json")
    blob.upload_blob(json.dumps(log_data, indent=2), overwrite=True)


def run_command(cmd: list, logs: list, timeout: int = 600) -> tuple:
    """Run a command and capture output."""
    try:
        result = subprocess.run(
            cmd, cwd=WORK_DIR,
            capture_output=True, text=True, timeout=timeout
        )
        if result.stdout:
            logs.append(result.stdout)
        if result.stderr and result.returncode != 0:
            logs.append(f"STDERR: {result.stderr}")
        return result.returncode, logs
    except subprocess.TimeoutExpired:
        logs.append(f"ERROR: Command timed out after {timeout}s")
        return -1, logs


if __name__ == "__main__":
    START_TIME = datetime.utcnow().isoformat()
    logs = [f"Container started at {START_TIME}"]
    logs.append(f"Template: {TEMPLATE_ID}")
    logs.append(f"Deploy ID: {DEPLOY_ID}")
    logs.append("")

    update_log("running", logs)

    # Step 1: Terraform init
    logs.append("=== terraform init ===")
    update_log("running", logs)

    rc, logs = run_command(["terraform", "init", "-no-color", "-input=false"], logs, timeout=120)
    update_log("running", logs)

    if rc != 0:
        logs.append("FAILED: terraform init failed")
        update_log("failed", logs)
        sys.exit(1)

    logs.append("Init successful.")
    logs.append("")

    # Step 2: Terraform plan
    logs.append("=== terraform plan ===")
    update_log("running", logs)

    rc, logs = run_command(["terraform", "plan", "-no-color", "-input=false", "-out=tfplan"], logs, timeout=120)
    update_log("running", logs)

    if rc != 0:
        logs.append("FAILED: terraform plan failed")
        update_log("failed", logs)
        sys.exit(1)

    logs.append("Plan successful.")
    logs.append("")

    # Step 3: Terraform apply
    logs.append("=== terraform apply ===")
    update_log("running", logs)

    rc, logs = run_command(["terraform", "apply", "-no-color", "-input=false", "-auto-approve", "tfplan"], logs, timeout=600)
    update_log("running", logs)

    if rc != 0:
        logs.append("FAILED: terraform apply failed")
        update_log("failed", logs)
        sys.exit(1)

    logs.append("Apply successful.")
    logs.append("")

    # Step 4: Get outputs
    logs.append("=== Outputs ===")
    result = subprocess.run(
        ["terraform", "output", "-json", "-no-color"],
        cwd=WORK_DIR, capture_output=True, text=True
    )

    outputs = None
    if result.returncode == 0 and result.stdout.strip():
        try:
            outputs = json.loads(result.stdout)
            for key, val in outputs.items():
                value = val.get("value", val) if isinstance(val, dict) else val
                logs.append(f"  {key} = {value}")
        except json.JSONDecodeError:
            logs.append(result.stdout)

    logs.append("")
    logs.append("=== Deployment Complete ===")
    update_log("completed", logs, outputs)

    print("Deployment completed successfully.")
