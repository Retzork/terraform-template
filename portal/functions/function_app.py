import azure.functions as func
import json
import logging
import os
import uuid
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential

app = func.FunctionApp()

STORAGE_CONNECTION = os.environ.get("STORAGE_CONNECTION_STRING")
LOGS_CONTAINER = os.environ.get("LOGS_CONTAINER", "deployment-logs")

# ACI configuration from environment
ACI_RESOURCE_GROUP = os.environ.get("ACI_RESOURCE_GROUP")
ACI_LOCATION = os.environ.get("ACI_LOCATION", "southeastasia")
ACI_SUBSCRIPTION_ID = os.environ.get("ACI_SUBSCRIPTION_ID")
STORAGE_ACCOUNT_NAME = os.environ.get("STORAGE_ACCOUNT_NAME")
STORAGE_ACCOUNT_KEY = os.environ.get("STORAGE_ACCOUNT_KEY")
TEMPLATES_SHARE = os.environ.get("TEMPLATES_SHARE", "templates")

# Managed Identity for Terraform inside ACI
ARM_CLIENT_ID = os.environ.get("ARM_CLIENT_ID")
ARM_TENANT_ID = os.environ.get("ARM_TENANT_ID")
ARM_SUBSCRIPTION_ID = os.environ.get("ARM_SUBSCRIPTION_ID")
ACI_IDENTITY_ID = os.environ.get("ACI_IDENTITY_ID")

# Template definitions
TEMPLATES = {
    "01": {
        "name": "Windows SQL Server",
        "description": "Standalone Windows VM with SQL Server 2017 Developer",
    },
    "02": {
        "name": "Windows SQL + Dynamics GP",
        "description": "Single VM with SQL Server and Dynamics GP 2018 from custom image",
    }
}


def _make_stack_id(template_id: str, subscription_id: str, resource_group_name: str) -> str:
    """Build a stable stack ID: {template_id}/{subscription_id}.{resource_group_name}"""
    return f"{template_id}/{subscription_id}.{resource_group_name}"


def _unflatten_stack_id(flat_id: str) -> str:
    """Convert flat stack ID (used in URLs) back to real stack ID.
    Flat: 01_dfaa40f0-0f72-4980-bd34-ccf9162a757d.SQL-RG
    Real: 01/dfaa40f0-0f72-4980-bd34-ccf9162a757d.SQL-RG
    Only the first _ is the separator (template_id is always 2 chars).
    """
    # Template ID is the part before the first _
    idx = flat_id.find("_")
    if idx == -1:
        return flat_id
    return flat_id[:idx] + "/" + flat_id[idx + 1:]


# ============================================================
# API Endpoints
# ============================================================

@app.route(route="templates", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_templates(req: func.HttpRequest) -> func.HttpResponse:
    """Return available templates."""
    return func.HttpResponse(
        json.dumps(TEMPLATES, indent=2),
        mimetype="application/json"
    )


@app.route(route="check-subscription", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def check_subscription(req: func.HttpRequest) -> func.HttpResponse:
    """Check if the deployment service can access a given subscription."""
    try:
        body = req.get_json()
        subscription_id = body.get("subscription_id", "").strip()

        if not subscription_id:
            return func.HttpResponse(
                json.dumps({"accessible": False, "error": "No subscription ID provided"}),
                status_code=400, mimetype="application/json"
            )

        try:
            credential = DefaultAzureCredential()
            token = credential.get_token("https://management.azure.com/.default")

            url = f"https://management.azure.com/subscriptions/{subscription_id}?api-version=2022-12-01"
            request = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json"
            })

            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode())
                return func.HttpResponse(
                    json.dumps({
                        "accessible": True,
                        "subscription_name": data.get("displayName", ""),
                        "subscription_id": subscription_id,
                        "state": data.get("state", "Unknown")
                    }),
                    mimetype="application/json"
                )

        except urllib.error.HTTPError as http_err:
            error_body = http_err.read().decode() if http_err.fp else ""
            return func.HttpResponse(
                json.dumps({
                    "accessible": False,
                    "error": f"HTTP {http_err.code}: Cannot access subscription",
                    "detail": error_body[:300]
                }),
                mimetype="application/json"
            )
        except Exception as auth_error:
            return func.HttpResponse(
                json.dumps({
                    "accessible": False,
                    "error": "Cannot verify access",
                    "detail": str(auth_error)[:300]
                }),
                mimetype="application/json"
            )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({"accessible": False, "error": str(e)}),
            status_code=500, mimetype="application/json"
        )


@app.route(route="check-resource-group", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def check_resource_group(req: func.HttpRequest) -> func.HttpResponse:
    """Check if a resource group already exists in the target subscription."""
    try:
        body = req.get_json()
        subscription_id = body.get("subscription_id", "").strip()
        resource_group_name = body.get("resource_group_name", "").strip()

        if not subscription_id or not resource_group_name:
            return func.HttpResponse(
                json.dumps({"error": "subscription_id and resource_group_name are required"}),
                status_code=400, mimetype="application/json"
            )

        credential = DefaultAzureCredential()
        token = credential.get_token("https://management.azure.com/.default")

        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/resourcegroups/{resource_group_name}?api-version=2022-09-01"
        )
        request = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json"
        })

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode())
                return func.HttpResponse(
                    json.dumps({
                        "exists": True,
                        "resource_group_name": data.get("name", resource_group_name),
                        "location": data.get("location", ""),
                        "provisioning_state": data.get("properties", {}).get("provisioningState", "")
                    }),
                    mimetype="application/json"
                )
        except urllib.error.HTTPError as http_err:
            if http_err.code == 404:
                return func.HttpResponse(
                    json.dumps({
                        "exists": False,
                        "resource_group_name": resource_group_name
                    }),
                    mimetype="application/json"
                )
            error_body = http_err.read().decode() if http_err.fp else ""
            return func.HttpResponse(
                json.dumps({
                    "exists": None,
                    "error": f"HTTP {http_err.code}: Cannot check resource group",
                    "detail": error_body[:300]
                }),
                mimetype="application/json"
            )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({"exists": None, "error": str(e)}),
            status_code=500, mimetype="application/json"
        )


@app.route(route="deploy", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def deploy(req: func.HttpRequest) -> func.HttpResponse:
    """Trigger a deployment by spinning up an ACI container."""
    return _trigger_aci(req, action="apply")


@app.route(route="destroy", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def destroy(req: func.HttpRequest) -> func.HttpResponse:
    """Trigger a destroy by spinning up an ACI container with terraform destroy."""
    return _trigger_aci(req, action="destroy")


def _trigger_aci(req: func.HttpRequest, action: str = "apply") -> func.HttpResponse:
    """Trigger an ACI container for apply or destroy."""
    try:
        body = req.get_json()
        template_id = body.get("template_id")
        variables = body.get("variables", {})
        stack_id = body.get("stack_id")  # For destroy, use the stack ID

        # For destroy, load variables from the saved stack vars
        if action == "destroy" and stack_id:
            stack_vars = _load_stack_vars(stack_id)
            if stack_vars:
                template_id = stack_vars.get("template_id", template_id)
                variables = stack_vars.get("variables", variables)
            else:
                return func.HttpResponse(
                    json.dumps({"error": f"Stack not found: {stack_id}. Cannot destroy."}),
                    status_code=404, mimetype="application/json"
                )

        if template_id not in TEMPLATES:
            return func.HttpResponse(
                json.dumps({"error": f"Unknown template: {template_id}"}),
                status_code=400, mimetype="application/json"
            )

        # Derive stack ID from variables (for apply)
        if not stack_id:
            subs_id = variables.get("subscription_id", "")
            rg_name = variables.get("resource_group_name", "")
            if not subs_id or not rg_name:
                return func.HttpResponse(
                    json.dumps({"error": "subscription_id and resource_group_name are required"}),
                    status_code=400, mimetype="application/json"
                )
            stack_id = _make_stack_id(template_id, subs_id, rg_name)

        # Operation ID for this specific run (for ACI naming and tfvars file)
        operation_id = f"{action}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        # Save full variables to stack (overwrite on each apply)
        _save_stack_vars(stack_id, template_id, variables)

        # Write operation log
        log_entry = {
            "stack_id": stack_id,
            "operation_id": operation_id,
            "template_id": template_id,
            "template_name": TEMPLATES[template_id]["name"],
            "action": action,
            "status": "starting",
            "started_at": datetime.utcnow().isoformat(),
            "variables": {k: v for k, v in variables.items() if "password" not in k.lower()},
            "logs": [f"{action.capitalize()} queued. Starting container..."]
        }
        _write_stack_log(stack_id, log_entry)

        # Generate tfvars content
        tfvars_lines = []
        for key, value in variables.items():
            if isinstance(value, (int, float)):
                tfvars_lines.append(f'{key} = {value}')
            elif isinstance(value, dict):
                obj_lines = [f'{key} = {{']
                for k, v in value.items():
                    obj_lines.append(f'  {k} = "{v}"')
                obj_lines.append('}')
                tfvars_lines.append('\n'.join(obj_lines))
            else:
                tfvars_lines.append(f'{key} = "{value}"')
        tfvars_content = "\n".join(tfvars_lines)

        # Upload tfvars to file share (use stack_id-safe name)
        tfvars_filename = stack_id.replace("/", "_")
        _upload_tfvars(tfvars_filename, tfvars_content)

        # Create ACI container
        _create_aci(stack_id, tfvars_filename, template_id, action, operation_id)

        return func.HttpResponse(
            json.dumps({
                "stack_id": stack_id,
                "operation_id": operation_id,
                "status": "started"
            }),
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Deploy error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500, mimetype="application/json"
        )


@app.route(route="status/{stack_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_status(req: func.HttpRequest) -> func.HttpResponse:
    """Get latest operation status for a stack."""
    stack_id_param = req.route_params.get("stack_id")

    # The URL uses _ instead of / to avoid route issues
    # Reconstruct: first _ is the / separator between template_id and subs.rg
    # Format: {template_id}_{subscription_id}.{resource_group_name}
    log_filename = stack_id_param  # already flat (uses _)
    stack_id = _unflatten_stack_id(stack_id_param)

    # Try file share first (_logs directory - ACI writes here)
    try:
        from azure.storage.fileshare import ShareFileClient
        file_client = ShareFileClient(
            account_url=f"https://{STORAGE_ACCOUNT_NAME}.file.core.windows.net",
            share_name=TEMPLATES_SHARE,
            file_path=f"_logs/{log_filename}.json",
            credential=STORAGE_ACCOUNT_KEY
        )
        data = json.loads(file_client.download_file().readall())
        return func.HttpResponse(json.dumps(data), mimetype="application/json")
    except Exception as e:
        logging.info(f"File share read failed for {stack_id}: {e}")

    # Fallback to blob storage
    try:
        blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_service.get_container_client(LOGS_CONTAINER)
        blob = container.get_blob_client(f"{log_filename}.json")
        data = json.loads(blob.download_blob().readall())
        return func.HttpResponse(json.dumps(data), mimetype="application/json")
    except Exception:
        pass

    return func.HttpResponse(
        json.dumps({"error": f"Stack not found: {stack_id}"}),
        status_code=404, mimetype="application/json"
    )


@app.route(route="check-resources/{stack_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def check_resources(req: func.HttpRequest) -> func.HttpResponse:
    """Check resources from the Terraform state file using a stack ID."""
    stack_id_param = req.route_params.get("stack_id")
    stack_id = _unflatten_stack_id(stack_id_param)
    log_filename = stack_id_param

    # Parse stack_id: {template_id}/{subscription_id}.{resource_group_name}
    parts = stack_id.split("/", 1)
    if len(parts) != 2:
        return func.HttpResponse(
            json.dumps({"error": f"Invalid stack ID format: {stack_id}"}),
            status_code=400, mimetype="application/json"
        )

    template_id = parts[0]
    subs_rg = parts[1]  # subscription_id.resource_group_name

    # State key matches what deploy.sh uses
    state_key = f"{stack_id}.tfstate"

    # Get latest log for status info
    log_filename = stack_id.replace("/", "_")
    deploy_log = None
    try:
        from azure.storage.fileshare import ShareFileClient
        file_client = ShareFileClient(
            account_url=f"https://{STORAGE_ACCOUNT_NAME}.file.core.windows.net",
            share_name=TEMPLATES_SHARE,
            file_path=f"_logs/{log_filename}.json",
            credential=STORAGE_ACCOUNT_KEY
        )
        deploy_log = json.loads(file_client.download_file().readall())
    except Exception:
        try:
            blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
            container = blob_service.get_container_client(LOGS_CONTAINER)
            blob = container.get_blob_client(f"{log_filename}.json")
            deploy_log = json.loads(blob.download_blob().readall())
        except Exception:
            pass

    # Read the state file
    try:
        blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_service.get_container_client("tfstate")
        blob = container.get_blob_client(state_key)
        state_data = json.loads(blob.download_blob().readall())
    except Exception:
        return func.HttpResponse(
            json.dumps({
                "stack_id": stack_id,
                "template_id": template_id,
                "template_name": TEMPLATES.get(template_id, {}).get("name", "Unknown"),
                "status": deploy_log.get("status", "unknown") if deploy_log else "unknown",
                "error": "State file not found. Deployment may still be in progress or was never completed.",
                "resources": []
            }),
            mimetype="application/json"
        )

    # Parse state file
    resources = []
    outputs = {}

    state_outputs = state_data.get("outputs", {})
    for key, val in state_outputs.items():
        if "admin" in key.lower():
            continue
        outputs[key] = val.get("value", val) if isinstance(val, dict) else val

    for res in state_data.get("resources", []):
        if res.get("mode") != "managed":
            continue
        res_type = res.get("type", "")
        res_name = res.get("name", "")
        for instance in res.get("instances", []):
            attrs = instance.get("attributes", {})
            resource_info = {
                "type": res_type,
                "name": attrs.get("name", res_name),
                "terraform_name": f"{res_type}.{res_name}",
            }
            if "location" in attrs:
                resource_info["location"] = attrs["location"]
            if "size" in attrs:
                resource_info["size"] = attrs["size"]
            if "ip_address" in attrs:
                resource_info["ip_address"] = attrs["ip_address"]
            if "private_ip_address" in attrs:
                resource_info["private_ip"] = attrs["private_ip_address"]
            if "disk_size_gb" in attrs:
                resource_info["disk_size_gb"] = attrs["disk_size_gb"]
            if "storage_account_type" in attrs:
                resource_info["storage_type"] = attrs["storage_account_type"]
            resources.append(resource_info)

    return func.HttpResponse(
        json.dumps({
            "stack_id": stack_id,
            "template_id": template_id,
            "template_name": TEMPLATES.get(template_id, {}).get("name", "Unknown"),
            "status": deploy_log.get("status", "unknown") if deploy_log else "unknown",
            "started_at": deploy_log.get("started_at", "") if deploy_log else "",
            "outputs": outputs,
            "resources": resources,
            "resource_count": len(resources),
        }),
        mimetype="application/json"
    )


# ============================================================
# Helper Functions
# ============================================================

def _write_stack_log(stack_id: str, log_data: dict):
    """Write stack operation log to blob storage."""
    blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
    container = blob_service.get_container_client(LOGS_CONTAINER)
    log_filename = stack_id.replace("/", "_")
    blob = container.get_blob_client(f"{log_filename}.json")
    blob.upload_blob(json.dumps(log_data, indent=2), overwrite=True)


def _save_stack_vars(stack_id: str, template_id: str, variables: dict):
    """Save full variables (including passwords) for a stack. Used for destroy."""
    blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
    container = blob_service.get_container_client("tfstate")
    vars_key = f"_vars/{stack_id}.json"
    data = {"template_id": template_id, "variables": variables, "updated_at": datetime.utcnow().isoformat()}
    blob = container.get_blob_client(vars_key)
    blob.upload_blob(json.dumps(data), overwrite=True)


def _load_stack_vars(stack_id: str) -> dict:
    """Load saved variables for a stack."""
    try:
        blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_service.get_container_client("tfstate")
        vars_key = f"_vars/{stack_id}.json"
        blob = container.get_blob_client(vars_key)
        return json.loads(blob.download_blob().readall())
    except Exception:
        return None


def _upload_tfvars(filename: str, tfvars_content: str):
    """Upload tfvars file to the file share so ACI can read it directly."""
    from azure.storage.fileshare import ShareFileClient, ShareDirectoryClient

    dir_client = ShareDirectoryClient(
        account_url=f"https://{STORAGE_ACCOUNT_NAME}.file.core.windows.net",
        share_name=TEMPLATES_SHARE,
        directory_path="_tfvars",
        credential=STORAGE_ACCOUNT_KEY
    )
    try:
        dir_client.create_directory()
    except Exception:
        pass

    file_client = ShareFileClient(
        account_url=f"https://{STORAGE_ACCOUNT_NAME}.file.core.windows.net",
        share_name=TEMPLATES_SHARE,
        file_path=f"_tfvars/{filename}.tfvars",
        credential=STORAGE_ACCOUNT_KEY
    )
    file_client.upload_file(tfvars_content.encode("utf-8"))


def _create_aci(stack_id: str, tfvars_filename: str, template_id: str, action: str, operation_id: str):
    """Create an Azure Container Instance to run Terraform."""

    credential = DefaultAzureCredential()
    token = credential.get_token("https://management.azure.com/.default")

    # ACI name: must be DNS-safe, max 63 chars, unique per operation
    import hashlib
    stack_hash = hashlib.md5(stack_id.encode()).hexdigest()[:10]
    container_group_name = f"tf-{action}-{stack_hash}-{operation_id}"[:63]

    # Log filename for ACI to write to (same as what status endpoint reads)
    log_filename = stack_id.replace("/", "_")

    container_body = {
        "location": ACI_LOCATION,
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {
                ACI_IDENTITY_ID: {}
            }
        },
        "properties": {
            "containers": [{
                "name": "terraform",
                "properties": {
                    "image": "hashicorp/terraform:1.9",
                    "resources": {
                        "requests": {"cpu": 1, "memoryInGB": 1.5}
                    },
                    "environmentVariables": [
                        {"name": "ARM_USE_MSI", "value": "true"},
                        {"name": "ARM_CLIENT_ID", "value": ARM_CLIENT_ID},
                        {"name": "ARM_TENANT_ID", "value": ARM_TENANT_ID},
                        {"name": "ARM_SUBSCRIPTION_ID", "value": ARM_SUBSCRIPTION_ID},
                        {"name": "TF_ACTION", "value": action},
                        {"name": "STACK_ID", "value": stack_id},
                        {"name": "DEPLOY_ID", "value": log_filename},
                        {"name": "TEMPLATE_ID", "value": template_id},
                        {"name": "TFVARS_FILENAME", "value": tfvars_filename},
                        {"name": "STORAGE_ACCOUNT_NAME", "value": STORAGE_ACCOUNT_NAME},
                        {"name": "STORAGE_ACCOUNT_KEY", "secureValue": STORAGE_ACCOUNT_KEY},
                        {"name": "LOGS_CONTAINER", "value": LOGS_CONTAINER},
                        {"name": "ACI_CONTAINER_GROUP", "value": container_group_name},
                        {"name": "ACI_RESOURCE_GROUP", "value": ACI_RESOURCE_GROUP},
                        {"name": "ACI_SUBSCRIPTION_ID", "value": ACI_SUBSCRIPTION_ID},
                    ],
                    "command": [
                        "/bin/sh", "-c",
                        "apk add --no-cache curl bash && "
                        "cp -r /mnt/templates/$TEMPLATE_ID /work && "
                        "cd /work && "
                        "cp /mnt/templates/_tfvars/$TFVARS_FILENAME.tfvars terraform.tfvars && "
                        "sh /mnt/templates/deploy.sh"
                    ],
                    "volumeMounts": [{
                        "name": "templates",
                        "mountPath": "/mnt/templates"
                    }]
                }
            }],
            "osType": "Linux",
            "restartPolicy": "Never",
            "volumes": [{
                "name": "templates",
                "azureFile": {
                    "shareName": TEMPLATES_SHARE,
                    "storageAccountName": STORAGE_ACCOUNT_NAME,
                    "storageAccountKey": STORAGE_ACCOUNT_KEY
                }
            }]
        }
    }

    url = (
        f"https://management.azure.com/subscriptions/{ACI_SUBSCRIPTION_ID}"
        f"/resourceGroups/{ACI_RESOURCE_GROUP}"
        f"/providers/Microsoft.ContainerInstance/containerGroups/{container_group_name}"
        f"?api-version=2023-05-01"
    )

    data = json.dumps(container_body).encode()
    request = urllib.request.Request(url, data=data, method="PUT", headers={
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/json"
    })

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode())
            logging.info(f"ACI created: {container_group_name}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        logging.error(f"ACI creation failed: {e.code} - {error_body}")
        # Check for transitioning error (concurrent operation on same stack)
        if "ContainerGroupTransitioning" in error_body or "still transitioning" in error_body:
            raise Exception("An operation is already running for this stack. Please wait for it to finish and try again.")
        raise Exception(f"Failed to create container: {error_body[:200]}")
