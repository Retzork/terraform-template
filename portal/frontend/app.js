// Configuration
const API_BASE = 'https://tf-runner-51447812.azurewebsites.net/api';

// Disk pricing per month in IDR (approximate, Southeast Asia region)
// Source: Azure pricing calculator, 1 USD ~ 16,000 IDR
const DISK_PRICING = {
    "Standard_LRS": { perGB: 640, label: "HDD" },         // ~$0.04/GB/mo
    "StandardSSD_LRS": { perGB: 1200, label: "SSD" },     // ~$0.075/GB/mo
    "Premium_LRS": { perGB: 2880, label: "Premium SSD" }  // ~$0.18/GB/mo
};

// Template definitions (embedded for static-only mode)
const TEMPLATES = {
    "01": {
        "name": "Windows SQL Server",
        "description": "Standalone Windows VM with SQL Server 2017 Developer",
        "variables": {
            "subscription_id": {"label": "Target Subscription ID", "type": "text", "default": "", "required": true},
            "resource_group_name": {"label": "Resource Group Name", "type": "text", "default": "SQL-RG", "required": true},
            "location": {"label": "Azure Region", "type": "select", "default": "southeastasia", "options": ["southeastasia", "eastasia", "eastus", "westus2", "westeurope"]},
            "vm_name": {"label": "VM Name", "type": "text", "default": "sql-vm-01", "required": true},
            "vm_size": {"label": "VM Size", "type": "select", "default": "Standard_D2s_v3", "options": ["Standard_D2s_v3", "Standard_D4s_v3", "Standard_D8s_v3", "Standard_B2ms"]},
            "user_username": {"label": "RDP User Username", "type": "text", "default": "GPAdmin", "required": true},
            "user_password": {"label": "RDP User Password", "type": "password", "default": "", "required": true},
            "os_disk_size_gb": {"label": "OS Disk Size (GB)", "type": "number", "default": 128, "disk": true},
            "os_disk_type": {"label": "OS Disk Type", "type": "select", "default": "StandardSSD_LRS", "options": ["StandardSSD_LRS", "Premium_LRS", "Standard_LRS"], "disk": true, "sizeField": "os_disk_size_gb"},
            "data_disk_size_gb": {"label": "SQL Data Disk Size (GB)", "type": "number", "default": 256, "disk": true},
            "data_disk_type": {"label": "SQL Data Disk Type", "type": "select", "default": "StandardSSD_LRS", "options": ["StandardSSD_LRS", "Premium_LRS", "Standard_LRS"], "disk": true, "sizeField": "data_disk_size_gb"},
            "log_disk_size_gb": {"label": "SQL Log Disk Size (GB)", "type": "number", "default": 256, "disk": true},
            "log_disk_type": {"label": "SQL Log Disk Type", "type": "select", "default": "StandardSSD_LRS", "options": ["StandardSSD_LRS", "Premium_LRS", "Standard_LRS"], "disk": true, "sizeField": "log_disk_size_gb"}
        }
    },
    "02": {
        "name": "Windows SQL + Dynamics GP",
        "description": "Single VM with SQL Server and Dynamics GP 2018 from custom image",
        "variables": {
            "subscription_id": {"label": "Target Subscription ID", "type": "text", "default": "", "required": true},
            "image_subscription_id": {"label": "Image Subscription ID", "type": "text", "default": "dfaa40f0-0f72-4980-bd34-ccf9162a757d", "required": true, "hidden": true},
            "resource_group_name": {"label": "Resource Group Name", "type": "text", "default": "GP-SQL-RG", "required": true},
            "location": {"label": "Azure Region", "type": "select", "default": "southeastasia", "options": ["southeastasia", "eastasia", "eastus", "westus2", "westeurope"]},
            "vm_name": {"label": "VM Name", "type": "text", "default": "gp-sql-01", "required": true},
            "vm_size": {"label": "VM Size", "type": "select", "default": "Standard_D4s_v3", "options": ["Standard_D2s_v3", "Standard_D4s_v3", "Standard_D8s_v3", "Standard_B2ms"]},
            "user_username": {"label": "RDP User Username", "type": "text", "default": "GPAdmin", "required": true},
            "user_password": {"label": "RDP User Password", "type": "password", "default": "", "required": true},
            "image_name": {"label": "Image Name", "type": "text", "default": "GP2018SQL", "hidden": true},
            "image_version": {"label": "Image Version", "type": "text", "default": "1.0.0", "hidden": true},
            "os_disk_size_gb": {"label": "OS Disk Size (GB)", "type": "number", "default": 128, "disk": true},
            "os_disk_type": {"label": "OS Disk Type", "type": "select", "default": "StandardSSD_LRS", "options": ["StandardSSD_LRS", "Premium_LRS", "Standard_LRS"], "disk": true, "sizeField": "os_disk_size_gb"},
            "data_disk_size_gb": {"label": "SQL Data Disk Size (GB)", "type": "number", "default": 256, "disk": true},
            "data_disk_type": {"label": "SQL Data Disk Type", "type": "select", "default": "StandardSSD_LRS", "options": ["StandardSSD_LRS", "Premium_LRS", "Standard_LRS"], "disk": true, "sizeField": "data_disk_size_gb"},
            "log_disk_size_gb": {"label": "SQL Log Disk Size (GB)", "type": "number", "default": 128, "disk": true},
            "log_disk_type": {"label": "SQL Log Disk Type", "type": "select", "default": "StandardSSD_LRS", "options": ["StandardSSD_LRS", "Premium_LRS", "Standard_LRS"], "disk": true, "sizeField": "log_disk_size_gb"}
        }
    }
};

// ============================================================
// Landing Page
// ============================================================
function selectTemplate(templateId) {
    window.location = `form.html?template=${templateId}`;
}

function searchDeployment() {
    const deployId = document.getElementById('search-deploy-id').value.trim();
    if (!deployId) {
        alert('Please enter a deployment ID');
        return;
    }
    window.location = `logs.html?id=${deployId}`;
}

// ============================================================
// Form Page
// ============================================================
async function loadForm(templateId) {
    try {
        const template = TEMPLATES[templateId];

        if (!template) {
            alert('Template not found');
            window.location = 'index.html';
            return;
        }

        document.getElementById('template-title').textContent = `Deploy: ${template.name}`;
        document.getElementById('template-desc').textContent = template.description;

        const formFields = document.getElementById('form-fields');
        formFields.innerHTML = '';

        // Add subscription check section at the top
        const subsCheck = document.createElement('div');
        subsCheck.className = 'subs-check-section';
        subsCheck.innerHTML = `
            <div class="form-group">
                <label for="subscription_id">Target Subscription ID</label>
                <div class="input-with-button">
                    <input type="text" id="subscription_id" name="subscription_id" required placeholder="Enter subscription ID">
                    <button type="button" class="btn btn-secondary btn-sm" onclick="checkSubscription()">Check Access</button>
                </div>
                <div id="subs-status" class="subs-status"></div>
            </div>
            <div class="form-group" id="rg-check-group" style="display:none;">
                <label for="resource_group_name">Resource Group Name</label>
                <div class="input-with-button">
                    <input type="text" id="resource_group_name" name="resource_group_name" required placeholder="Enter resource group name" value="${template.variables.resource_group_name?.default || ''}">
                    <button type="button" class="btn btn-secondary btn-sm" onclick="checkResourceGroup()">Check RG</button>
                </div>
                <div id="rg-status" class="subs-status"></div>
            </div>
        `;
        formFields.appendChild(subsCheck);

        for (const [key, config] of Object.entries(template.variables)) {
            // Skip subscription_id and resource_group_name (already added above)
            if (key === 'subscription_id') continue;
            if (key === 'resource_group_name') continue;
            // Skip hidden fields
            if (config.hidden) continue;

            const group = document.createElement('div');
            group.className = 'form-group';

            const label = document.createElement('label');
            label.textContent = config.label;
            label.setAttribute('for', key);
            group.appendChild(label);

            let input;
            if (config.type === 'select') {
                input = document.createElement('select');
                for (const opt of config.options) {
                    const option = document.createElement('option');
                    option.value = opt;
                    // For disk type selects, show pricing
                    if (config.disk && config.sizeField && DISK_PRICING[opt]) {
                        option.textContent = `${DISK_PRICING[opt].label} (${opt})`;
                    } else {
                        option.textContent = opt;
                    }
                    if (opt === config.default) option.selected = true;
                    input.appendChild(option);
                }
                // Add price display for disk type selects
                if (config.disk && config.sizeField) {
                    input.addEventListener('change', () => updateDiskPricing(key, config.sizeField));
                }
            } else {
                input = document.createElement('input');
                input.type = config.type === 'number' ? 'number' : config.type === 'password' ? 'password' : 'text';
                input.value = config.default || '';
                if (config.required) input.required = true;
                // Add price update listener for disk size fields
                if (config.disk && config.type === 'number') {
                    input.addEventListener('input', () => updateDiskPricingFromSize(key));
                }
            }

            input.id = key;
            input.name = key;
            group.appendChild(input);

            // Add pricing display for disk type fields
            if (config.disk && config.sizeField) {
                const priceDisplay = document.createElement('div');
                priceDisplay.className = 'disk-price';
                priceDisplay.id = `price-${key}`;
                group.appendChild(priceDisplay);
            }

            formFields.appendChild(group);
        }

        // Add hidden fields for defaults
        for (const [key, config] of Object.entries(template.variables)) {
            if (config.hidden) {
                const hidden = document.createElement('input');
                hidden.type = 'hidden';
                hidden.id = key;
                hidden.name = key;
                hidden.value = config.default || '';
                formFields.appendChild(hidden);
            }
        }

        // Initialize disk pricing displays
        setTimeout(() => {
            for (const [key, config] of Object.entries(template.variables)) {
                if (config.disk && config.sizeField) {
                    updateDiskPricing(key, config.sizeField);
                }
            }
        }, 100);

        // Handle form submit
        document.getElementById('deploy-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            await submitDeploy(templateId, template.variables);
        });

    } catch (error) {
        console.error('Error loading form:', error);
        alert('Failed to load template configuration');
    }
}

// ============================================================
// Disk Pricing
// ============================================================
function updateDiskPricing(typeFieldKey, sizeFieldKey) {
    const typeEl = document.getElementById(typeFieldKey);
    const sizeEl = document.getElementById(sizeFieldKey);
    const priceEl = document.getElementById(`price-${typeFieldKey}`);

    if (!typeEl || !sizeEl || !priceEl) return;

    const diskType = typeEl.value;
    const sizeGB = parseInt(sizeEl.value) || 0;
    const pricing = DISK_PRICING[diskType];

    if (pricing && sizeGB > 0) {
        const monthlyIDR = pricing.perGB * sizeGB;
        priceEl.textContent = `~Rp ${monthlyIDR.toLocaleString('id-ID')}/bulan (${sizeGB} GB × Rp ${pricing.perGB.toLocaleString('id-ID')}/GB)`;
        priceEl.className = 'disk-price';
    } else {
        priceEl.textContent = '';
    }
}

function updateDiskPricingFromSize(sizeFieldKey) {
    // Find the corresponding type field and update its pricing
    const templateId = new URLSearchParams(window.location.search).get('template');
    const template = TEMPLATES[templateId];
    if (!template) return;

    for (const [key, config] of Object.entries(template.variables)) {
        if (config.sizeField === sizeFieldKey) {
            updateDiskPricing(key, sizeFieldKey);
        }
    }
}

// ============================================================
// Subscription Check
// ============================================================
async function checkSubscription() {
    const subsId = document.getElementById('subscription_id').value.trim();
    const statusEl = document.getElementById('subs-status');

    if (!subsId) {
        statusEl.innerHTML = '<span class="status-error">Please enter a subscription ID</span>';
        return;
    }

    // UUID format check
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(subsId)) {
        statusEl.innerHTML = '<span class="status-error">Invalid subscription ID format. Expected UUID format.</span>';
        return;
    }

    statusEl.innerHTML = '<span class="status-checking">Checking access...</span>';

    try {
        const response = await fetch(`${API_BASE}/check-subscription`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subscription_id: subsId })
        });

        const result = await response.json();

        if (response.ok && result.accessible) {
            statusEl.innerHTML = `<span class="status-ok">&#10003; Access confirmed: ${result.subscription_name || subsId}</span>`;
            // Show resource group check section
            const rgGroup = document.getElementById('rg-check-group');
            if (rgGroup) rgGroup.style.display = 'block';
        } else {
            statusEl.innerHTML = `
                <span class="status-error">&#10007; Cannot access this subscription.</span>
                <div class="status-help">
                    <p>Our deployment service does not have access to this subscription. To fix this:</p>
                    <ol>
                        <li>Go to the Azure Portal → Subscriptions → <strong>${subsId}</strong></li>
                        <li>Navigate to <strong>Access control (IAM)</strong></li>
                        <li>Click <strong>Add role assignment</strong></li>
                        <li>Assign the <strong>Contributor</strong> role to our service principal</li>
                        <li>Also ensure our CLI tenant has access: run <code>az login --tenant &lt;tenant-id&gt;</code></li>
                    </ol>
                    <p>Contact your administrator if you don't have permission to assign roles.</p>
                </div>
            `;
        }
    } catch (error) {
        // If API is not available, show offline message with error code
        statusEl.innerHTML = `
            <span class="status-warning">&#9888; API not available (${error.message})</span>
            <div class="status-help">
                <p><strong>Error:</strong> The backend Function App is not deployed or not linked yet.</p>
                <p>To deploy manually, ensure the az CLI on the deployment server has access to this subscription:</p>
                <ol>
                    <li>Login to the correct tenant: <code>az login --tenant &lt;tenant-id&gt;</code></li>
                    <li>Verify access: <code>az account set --subscription ${subsId}</code></li>
                    <li>If it fails, ask the subscription owner to assign <strong>Contributor</strong> role to your account</li>
                </ol>
                <p class="status-error">Function App URL: <code>${API_BASE}/check-subscription</code></p>
            </div>
        `;
    }
}

// ============================================================
// Resource Group Check
// ============================================================
async function checkResourceGroup() {
    const subsId = document.getElementById('subscription_id').value.trim();
    const rgName = document.getElementById('resource_group_name').value.trim();
    const statusEl = document.getElementById('rg-status');

    if (!subsId) {
        statusEl.innerHTML = '<span class="status-error">Please check subscription access first</span>';
        return;
    }

    if (!rgName) {
        statusEl.innerHTML = '<span class="status-error">Please enter a resource group name</span>';
        return;
    }

    statusEl.innerHTML = '<span class="status-checking">Checking resource group...</span>';

    try {
        const response = await fetch(`${API_BASE}/check-resource-group`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subscription_id: subsId, resource_group_name: rgName })
        });

        const result = await response.json();

        if (response.ok && result.exists === true) {
            statusEl.innerHTML = `
                <span class="status-warning">&#9888; Resource group "<strong>${rgName}</strong>" already exists (${result.location}).</span>
                <div class="status-help">
                    <p>Deploying to an existing resource group will <strong>update or add resources</strong> using the stored Terraform state.</p>
                    <p>If you want a fresh deployment, use a different resource group name.</p>
                </div>
            `;
        } else if (response.ok && result.exists === false) {
            statusEl.innerHTML = `<span class="status-ok">&#10003; Resource group "${rgName}" does not exist. It will be created during deployment.</span>`;
        } else {
            statusEl.innerHTML = `<span class="status-error">&#10007; Cannot check resource group: ${result.error || 'Unknown error'}</span>`;
        }
    } catch (error) {
        statusEl.innerHTML = `<span class="status-warning">&#9888; API not available (${error.message}). Cannot verify resource group.</span>`;
    }
}

// ============================================================
// Deploy
// ============================================================
async function submitDeploy(templateId, variableDefs) {
    const variables = {};

    for (const [key, config] of Object.entries(variableDefs)) {
        const el = document.getElementById(key);
        if (!el) continue;
        let value = el.value;

        // Convert numbers
        if (config.type === 'number') {
            value = parseInt(value, 10);
        }

        variables[key] = value;
    }

    // Add hidden defaults for admin credentials and other required vars
    variables['admin_username'] = 'AIAdmin';
    variables['admin_password'] = '4RthaIT123$%^';
    variables['vnet_address_space'] = '10.0.0.0/16';
    variables['subnet_address_prefix'] = '10.0.1.0/24';

    // Add object variables (sql_image for template 01)
    if (templateId === '01') {
        variables['sql_image'] = {
            publisher: 'MicrosoftSQLServer',
            offer: 'sql2017-ws2019',
            sku: 'sqldev-gen2',
            version: 'latest'
        };
    }

    try {
        const response = await fetch(`${API_BASE}/deploy`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ template_id: templateId, variables })
        });

        const result = await response.json();

        if (response.ok) {
            document.getElementById('deploy-form').style.display = 'none';
            document.getElementById('deploy-status').style.display = 'block';
            document.getElementById('deploy-id').textContent = result.deploy_id;
            document.getElementById('log-link').href = `logs.html?id=${result.deploy_id}`;
        } else {
            alert(`Deployment failed: ${result.error}`);
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

// ============================================================
// Logs Page
// ============================================================
let logCollapsed = false;

async function refreshLogs() {
    const params = new URLSearchParams(window.location.search);
    const deployId = params.get('id');

    if (!deployId) return;

    try {
        const response = await fetch(`${API_BASE}/status/${deployId}`);
        const data = await response.json();

        if (response.ok) {
            document.getElementById('template-name').textContent = data.template_name || data.template_id;
            document.getElementById('started-at').textContent = data.started_at || '-';

            const badge = document.getElementById('status-badge');
            badge.textContent = data.status;
            badge.className = `badge badge-${data.status}`;

            // Render logs line-by-line
            const logOutput = document.getElementById('log-output');
            if (data.logs && data.logs.length > 0) {
                logOutput.innerHTML = data.logs.map(line => {
                    let cls = 'log-line';
                    if (line.includes('ERROR') || line.includes('Error:')) cls += ' error';
                    if (line.includes('complete') || line.includes('successful') || line.includes('Complete')) cls += ' success';
                    if (line.startsWith('===')) cls += ' section-header';
                    return `<div class="${cls}">${escapeHtml(line)}</div>`;
                }).join('');
                logOutput.scrollTop = logOutput.scrollHeight;
            } else {
                logOutput.innerHTML = '<p class="log-placeholder">No logs yet. Click Refresh.</p>';
            }

            // Show outputs ABOVE logs when completed (filter out admin_username)
            if (data.status === 'completed') {
                // Parse outputs from log lines (terraform output format: key = "value")
                const outputs = parseOutputsFromLogs(data.logs);
                if (Object.keys(outputs).length > 0) {
                    const section = document.getElementById('outputs-section');
                    section.style.display = 'block';
                    const tbody = document.getElementById('outputs-body');
                    tbody.innerHTML = '';
                    for (const [key, val] of Object.entries(outputs)) {
                        // Skip admin username - never show it
                        if (key === 'admin_username') continue;
                        const tr = document.createElement('tr');
                        const displayKey = formatOutputKey(key);
                        tr.innerHTML = `<td>${escapeHtml(displayKey)}</td><td><code>${escapeHtml(val)}</code></td>`;
                        tbody.appendChild(tr);
                    }
                }

                // Collapse log and show toggle
                const logToggle = document.getElementById('log-toggle');
                if (logToggle) {
                    logToggle.style.display = 'block';
                    collapseLog();
                }

                // Hide refresh notice
                const refreshNotice = document.getElementById('refresh-notice');
                if (refreshNotice) refreshNotice.style.display = 'none';
            }

            // Show destroy button for completed or failed deployments
            if (data.status === 'completed' || data.status === 'failed') {
                document.getElementById('destroy-btn').style.display = 'inline-block';
            }
        } else {
            document.getElementById('log-output').innerHTML =
                `<div class="log-line error">Deployment not found: ${deployId}</div>`;
        }
    } catch (error) {
        document.getElementById('log-output').innerHTML =
            `<div class="log-line error">Error fetching logs: ${error.message}</div>`;
    }
}

function parseOutputsFromLogs(logs) {
    const outputs = {};
    let inOutputs = false;
    for (const line of logs) {
        if (line.includes('=== Outputs ===')) {
            inOutputs = true;
            // The outputs might be on this same line after the header
            const afterHeader = line.split('=== Outputs ===')[1];
            if (afterHeader) {
                extractOutputPairs(afterHeader, outputs);
            }
            continue;
        }
        if (inOutputs && line.startsWith('===')) {
            break;
        }
        if (inOutputs && line.includes(' = ')) {
            extractOutputPairs(line, outputs);
        }
    }
    return outputs;
}

function extractOutputPairs(text, outputs) {
    // Remove trailing section markers
    text = text.replace(/===.*?===/g, '').trim();
    // Match patterns like: key = "value"
    const regex = /(\w+)\s*=\s*"([^"]*)"/g;
    let match;
    while ((match = regex.exec(text)) !== null) {
        outputs[match[1]] = match[2];
    }
    // Also try unquoted values (e.g. key = value without quotes)
    if (Object.keys(outputs).length === 0) {
        const parts = text.split(/\s{2,}/);
        for (const part of parts) {
            const m = part.trim().match(/^(\w+)\s*=\s*(.+)$/);
            if (m) {
                outputs[m[1]] = m[2].replace(/^"|"$/g, '');
            }
        }
    }
}

function formatOutputKey(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function toggleLog() {
    const logOutput = document.getElementById('log-output');
    const icon = document.getElementById('log-toggle-icon');
    if (logCollapsed) {
        logOutput.style.display = 'block';
        icon.innerHTML = '&#9660;';
        logCollapsed = false;
    } else {
        collapseLog();
    }
}

function collapseLog() {
    const logOutput = document.getElementById('log-output');
    const icon = document.getElementById('log-toggle-icon');
    logOutput.style.display = 'none';
    icon.innerHTML = '&#9654;';
    logCollapsed = true;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================================
// Destroy
// ============================================================
async function confirmDestroy() {
    const params = new URLSearchParams(window.location.search);
    const deployId = params.get('id');

    if (!confirm(`Are you sure you want to DESTROY all resources from deployment ${deployId}? This cannot be undone.`)) {
        return;
    }

    const btn = document.getElementById('destroy-btn');
    btn.disabled = true;
    btn.textContent = 'Destroying...';

    try {
        const response = await fetch(`${API_BASE}/destroy`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ deploy_id: deployId })
        });

        const result = await response.json();

        if (response.ok) {
            alert(`Destroy initiated. Deploy ID: ${result.deploy_id}\nRefresh to see progress.`);
            // Redirect to the destroy log
            window.location = `logs.html?id=${result.deploy_id}`;
        } else {
            alert(`Destroy failed: ${result.error}`);
            btn.disabled = false;
            btn.textContent = '🗑 Destroy';
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
        btn.disabled = false;
        btn.textContent = '🗑 Destroy';
    }
}

// ============================================================
// Resource Checker Page
// ============================================================
async function checkResources() {
    const deployId = document.getElementById('checker-deploy-id').value.trim();
    const resultsEl = document.getElementById('checker-results');
    const summaryEl = document.getElementById('checker-summary');

    if (!deployId) {
        alert('Please enter a deployment ID');
        return;
    }

    resultsEl.style.display = 'block';
    summaryEl.innerHTML = '<span class="status-checking">Checking resources...</span>';
    document.getElementById('checker-outputs').style.display = 'none';
    document.getElementById('checker-resources').style.display = 'none';
    document.getElementById('checker-actions').style.display = 'none';

    try {
        const response = await fetch(`${API_BASE}/check-resources/${deployId}`);
        const data = await response.json();

        if (!response.ok || data.error) {
            summaryEl.innerHTML = `
                <div class="status-error">&#10007; ${data.error || 'Deployment not found'}</div>
            `;
            return;
        }

        // Summary
        const statusClass = data.status === 'completed' ? 'status-ok' : data.status === 'failed' ? 'status-error' : 'status-warning';
        summaryEl.innerHTML = `
            <div class="checker-info">
                <p><strong>Template:</strong> ${escapeHtml(data.template_name)}</p>
                <p><strong>Resource Group:</strong> <code>${escapeHtml(data.resource_group_name)}</code></p>
                <p><strong>Last Deploy Status:</strong> <span class="${statusClass}">${escapeHtml(data.status)}</span></p>
                <p><strong>Started:</strong> ${escapeHtml(data.started_at || '-')}</p>
                <p><strong>Resources tracked:</strong> ${data.resource_count}</p>
            </div>
            <div class="checker-disclaimer">
                <p>&#9432; <strong>Note:</strong> This shows resources as tracked by Terraform state. It does not reflect changes made outside of Terraform (e.g. manual edits in Azure Portal, deleted resources, resized VMs). Only changes made through this portal are tracked here.</p>
            </div>
        `;

        // Outputs (filter admin)
        if (data.outputs && Object.keys(data.outputs).length > 0) {
            const outputsEl = document.getElementById('checker-outputs');
            outputsEl.style.display = 'block';
            const tbody = document.getElementById('checker-outputs-body');
            tbody.innerHTML = '';
            for (const [key, val] of Object.entries(data.outputs)) {
                if (key.toLowerCase().includes('admin')) continue;
                const tr = document.createElement('tr');
                const displayKey = formatOutputKey(key);
                const displayVal = typeof val === 'object' ? JSON.stringify(val) : String(val);
                tr.innerHTML = `<td>${escapeHtml(displayKey)}</td><td><code>${escapeHtml(displayVal)}</code></td>`;
                tbody.appendChild(tr);
            }
        }

        // Resources list
        if (data.resources && data.resources.length > 0) {
            const resourcesEl = document.getElementById('checker-resources');
            resourcesEl.style.display = 'block';
            const tbody = document.getElementById('checker-resources-body');
            tbody.innerHTML = '';
            for (const res of data.resources) {
                const tr = document.createElement('tr');
                const typeParts = res.type.split('_');
                const shortType = typeParts.slice(1).join(' ');
                let details = [];
                if (res.location) details.push(res.location);
                if (res.size) details.push(res.size);
                if (res.ip_address) details.push(`IP: ${res.ip_address}`);
                if (res.disk_size_gb) details.push(`${res.disk_size_gb} GB`);
                const detailStr = details.length > 0 ? ` (${details.join(', ')})` : '';
                tr.innerHTML = `<td>${escapeHtml(res.name)}</td><td>${escapeHtml(shortType)}</td><td>${escapeHtml(detailStr)}</td>`;
                tbody.appendChild(tr);
            }
        }

        // Actions
        const actionsEl = document.getElementById('checker-actions');
        actionsEl.style.display = 'flex';
        document.getElementById('checker-logs-link').href = `logs.html?id=${deployId}`;

    } catch (error) {
        summaryEl.innerHTML = `<div class="status-error">&#10007; Error: ${error.message}</div>`;
    }
}

async function checkerDestroy() {
    const deployId = document.getElementById('checker-deploy-id').value.trim();

    if (!confirm(`Are you sure you want to DESTROY all resources from deployment ${deployId}? This cannot be undone.`)) {
        return;
    }

    const btn = document.getElementById('checker-destroy-btn');
    btn.disabled = true;
    btn.textContent = 'Destroying...';

    try {
        const response = await fetch(`${API_BASE}/destroy`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ deploy_id: deployId })
        });

        const result = await response.json();

        if (response.ok) {
            window.location = `logs.html?id=${result.deploy_id}`;
        } else {
            alert(`Destroy failed: ${result.error}`);
            btn.disabled = false;
            btn.textContent = '🗑 Destroy Resources';
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
        btn.disabled = false;
        btn.textContent = '🗑 Destroy Resources';
    }
}
