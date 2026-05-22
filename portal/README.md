# Terraform Deployment Portal

A serverless self-service portal for deploying Azure infrastructure templates.

## Architecture

```
User Browser
    |
    v
Azure Static Web App (Free tier) --- frontend/
    |
    v (API calls)
Azure Functions (Consumption/Y1) --- functions/
    |
    v
Terraform CLI (runs in Function container)
    |
    v
Azure Resources (target subscription)
```

## Cost when idle: ~$0/month
- Static Web App: Free tier
- Function App: Consumption plan (1M free executions/month, pay only when triggered)
- Storage: ~$0.01/month for logs

## Structure

```
portal/
├── terraform/          # Infrastructure for the portal itself
│   ├── main.tf
│   └── terraform.tfvars
├── functions/          # Azure Function App (Python)
│   ├── function_app.py
│   ├── requirements.txt
│   └── host.json
└── frontend/           # Static Web App (HTML/CSS/JS)
    ├── index.html      # Landing - pick a template
    ├── form.html       # Form - fill variables
    ├── logs.html       # Logs - monitor deployment
    ├── style.css
    ├── app.js
    └── staticwebapp.config.json
```

## Deployment Steps

1. Deploy portal infrastructure:
   ```
   cd portal/terraform
   terraform init
   terraform apply
   ```

2. Deploy the Function App code:
   ```
   cd portal/functions
   func azure functionapp publish <function-app-name>
   ```

3. Deploy the Static Web App:
   - Link to a GitHub repo, or
   - Use Azure CLI: `az staticwebapp deploy`

4. Link the Function App as the Static Web App's backend API.

## Pages

1. **Landing** (index.html) - Shows available templates with descriptions
2. **Form** (form.html) - Dynamic form based on template variables with defaults
3. **Logs** (logs.html) - Shows deployment status and terraform output (manual refresh)
