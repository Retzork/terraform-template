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

        # Use Function App's managed identity to check subscription
        try:
            credential = DefaultAzureCredential()
            token = credential.get_token("https://management.azure.com/.default")

            # Check subscription access
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
        source_deploy_id = body.get("deploy_id")  # For destroy, reference the original deploy

        # For destroy, get template_id and variables from the original deployment log
        if action == "destroy" and source_deploy_id:
            try:
                from azure.storage.fileshare import ShareFileClient
                file_client = ShareFileClient(
                    account_url=f"https://{STORAGE_ACCOUNT_NAME}.file.core.windows.net",
                    share_name=TEMPLATES_SHARE,
                    file_path=f"_logs/{source_deploy_id}.json",
                    credential=STORAGE_ACCOUNT_KEY
                )
                original_log = json.loads(file_client.download_file().readall())
                template_id = original_log.get("template_id", template_id)
                variables = original_log.get("variables", variables)
            except Exception:
                # Fallback to blob
                try:
                    blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
                    container = blob_service.get_container_client(LOGS_CONTAINER)
                    blob = container.get_blob_client(f"{source_deploy_id}.json")
                    original_log = json.loads(blob.download_blob().readall())
                    template_id = original_log.get("template_id", template_id)
                    variables = original_log.get("variables", variables)
                except Exception:
                    pass

        if template_id not in TEMPLATES:
            return func.HttpResponse(
                json.dumps({"error": f"Unknown template: {template_id}"}),
                status_code=400, mimetype="application/json"
            )

        action_label = "destroy" if action == "destroy" else "deploy"
        deploy_id = f"{template_id}-{action_label}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        # Write initial log
        log_entry = {
            "deploy_id": deploy_id,
            "template_id": template_id,
            "template_name": TEMPLATES[template_id]["name"],
            "action": action,
            "status": "starting",
            "started_at": datetime.utcnow().isoformat(),
            "variables": {k: v for k, v in variables.items() if "password" not in k.lower()},
            "logs": [f"{action.capitalize()} queued. Starting container..."]
        }
        _write_log(deploy_id, log_entry)

        # Generate tfvars content
        tfvars_lines = []
        for key, value in variables.items():
            if isinstance(value, (int, float)):
                tfvars_lines.append(f'{key} = {value}')
            elif isinstance(value, dict):
                # HCL object format
                obj_lines = [f'{key} = {{']
                for k, v in value.items():
                    obj_lines.append(f'  {k} = "{v}"')
                obj_lines.append('}')
                tfvars_lines.append('\n'.join(obj_lines))
            else:
                tfvars_lines.append(f'{key} = "{value}"')
        tfvars_content = "\n".join(tfvars_lines)

        # Upload tfvars to file share so ACI can read it directly (avoids shell escaping issues)
        _upload_tfvars(deploy_id, tfvars_content)

        # Create ACI container
        _create_aci(deploy_id, template_id, action)

        return func.HttpResponse(
            json.dumps({"deploy_id": deploy_id, "status": "started"}),
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Deploy error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500, mimetype="application/json"
        )


@app.route(route="status/{deploy_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_status(req: func.HttpRequest) -> func.HttpResponse:
    """Get deployment status and logs from file share (ACI writes there) or blob storage."""
    deploy_id = req.route_params.get("deploy_id")

    # First try file share (_logs directory) - ACI writes here
    try:
        from azure.storage.fileshare import ShareFileClient
        file_client = ShareFileClient(
            account_url=f"https://{STORAGE_ACCOUNT_NAME}.file.core.windows.net",
            share_name=TEMPLATES_SHARE,
            file_path=f"_logs/{deploy_id}.json",
            credential=STORAGE_ACCOUNT_KEY
        )
        data = json.loads(file_client.download_file().readall())
        return func.HttpResponse(json.dumps(data), mimetype="application/json")
    except Exception as e:
        logging.info(f"File share read failed for {deploy_id}: {e}")

    # Fallback to blob storage (initial log written by Function App)
    try:
        blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_service.get_container_client(LOGS_CONTAINER)
        blob = container.get_blob_client(f"{deploy_id}.json")
        data = json.loads(blob.download_blob().readall())
        return func.HttpResponse(json.dumps(data), mimetype="application/json")
    except Exception:
        pass

    return func.HttpResponse(
        json.dumps({"error": f"Deployment not found: {deploy_id}"}),
        status_code=404, mimetype="application/json"
    )


@app.route(route="check-resources/{deploy_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def check_resources(req: func.HttpRequest) -> func.HttpResponse:
    """Check resources from the Terraform state file using a deployment ID."""
    deploy_id = req.route_params.get("deploy_id")

    # Step 1: Get deployment log to find template_id and resource_group_name
    deploy_log = None

    # Try file share first
    try:
        from azure.storage.fileshare import ShareFileClient
        file_client = ShareFileClient(
            account_url=f"https://{STORAGE_ACCOUNT_NAME}.file.core.windows.net",
            share_name=TEMPLATES_SHARE,
            file_path=f"_logs/{deploy_id}.json",
            credential=STORAGE_ACCOUNT_KEY
        )
        deploy_log = json.loads(file_client.download_file().readall())
    except Exception:
        pass

    # Fallback to blob
    if not deploy_log:
        try:
            blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
            container = blob_service.get_container_client(LOGS_CONTAINER)
            blob = container.get_blob_client(f"{deploy_id}.json")
            deploy_log = json.loads(blob.download_blob().readall())
        except Exception:
            pass

    if not deploy_log:
        return func.HttpResponse(
            json.dumps({"error": f"Deployment not found: {deploy_id}"}),
            status_code=404, mimetype="application/json"
        )

    template_id = deploy_log.get("template_id", "")
    variables = deploy_log.get("variables", {})
    rg_name = variables.get("resource_group_name", deploy_id)
    state_key = f"{template_id}/{rg_name}.tfstate"

    # Step 2: Read the state file from tfstate blob container
    try:
        blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_service.get_container_client("tfstate")
        blob = container.get_blob_client(state_key)
        state_data = json.loads(blob.download_blob().readall())
    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "deploy_id": deploy_id,
                "template_id": template_id,
                "template_name": TEMPLATES.get(template_id, {}).get("name", "Unknown"),
                "resource_group_name": rg_name,
                "status": deploy_log.get("status", "unknown"),
                "error": "State file not found. Deployment may still be in progress or was never completed.",
                "resources": []
            }),
            mimetype="application/json"
        )

    # Step 3: Parse state file to extract resources and outputs
    resources = []
    outputs = {}

    # Extract outputs (filter out admin_username)
    state_outputs = state_data.get("outputs", {})
    for key, val in state_outputs.items():
        if "admin" in key.lower():
            continue
        outputs[key] = val.get("value", val) if isinstance(val, dict) else val

    # Extract resources
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
            # Add useful attributes based on resource type
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
            "deploy_id": deploy_id,
            "template_id": template_id,
            "template_name": TEMPLATES.get(template_id, {}).get("name", "Unknown"),
            "resource_group_name": rg_name,
            "status": deploy_log.get("status", "unknown"),
            "started_at": deploy_log.get("started_at", ""),
            "outputs": outputs,
            "resources": resources,
            "resource_count": len(resources),
        }),
        mimetype="application/json"
    )


def _write_log(deploy_id: str, log_data: dict):
    """Write deployment log to blob storage."""
    blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
    container = blob_service.get_container_client(LOGS_CONTAINER)
    blob = container.get_blob_client(f"{deploy_id}.json")
    blob.upload_blob(json.dumps(log_data, indent=2), overwrite=True)


def _upload_tfvars(deploy_id: str, tfvars_content: str):
    """Upload tfvars file to the file share so ACI can read it directly."""
    from azure.storage.fileshare import ShareFileClient, ShareDirectoryClient

    # Ensure _tfvars directory exists
    dir_client = ShareDirectoryClient(
        account_url=f"https://{STORAGE_ACCOUNT_NAME}.file.core.windows.net",
        share_name=TEMPLATES_SHARE,
        directory_path="_tfvars",
        credential=STORAGE_ACCOUNT_KEY
    )
    try:
        dir_client.create_directory()
    except Exception:
        pass  # Directory may already exist

    # Upload the tfvars file
    file_client = ShareFileClient(
        account_url=f"https://{STORAGE_ACCOUNT_NAME}.file.core.windows.net",
        share_name=TEMPLATES_SHARE,
        file_path=f"_tfvars/{deploy_id}.tfvars",
        credential=STORAGE_ACCOUNT_KEY
    )
    file_client.upload_file(tfvars_content.encode("utf-8"))


def _create_aci(deploy_id: str, template_id: str, action: str = "apply"):
    """Create an Azure Container Instance to run Terraform."""

    # Get token using managed identity
    credential = DefaultAzureCredential()
    token = credential.get_token("https://management.azure.com/.default")

    container_group_name = f"tf-{action}-{deploy_id}"[:63]  # ACI name limit

    # ACI container definition with User-Assigned Managed Identity
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
                        {"name": "DEPLOY_ID", "value": deploy_id},
                        {"name": "TEMPLATE_ID", "value": template_id},
                        {"name": "STORAGE_ACCOUNT_NAME", "value": STORAGE_ACCOUNT_NAME},
                        {"name": "STORAGE_ACCOUNT_KEY", "secureValue": STORAGE_ACCOUNT_KEY},
                        {"name": "LOGS_CONTAINER", "value": LOGS_CONTAINER},
                    ],
                    "command": [
                        "/bin/sh", "-c",
                        "apk add --no-cache curl bash && "
                        "cp -r /mnt/templates/$TEMPLATE_ID /work && "
                        "cd /work && "
                        "cp /mnt/templates/_tfvars/$DEPLOY_ID.tfvars terraform.tfvars && "
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

    # Create ACI via REST API
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
        raise Exception(f"Failed to create container: {error_body[:200]}")
