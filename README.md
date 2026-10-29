# Genie User Churn Analysis

A Declarative Automation Bundle (DAB) that answers two questions about Genie adoption at a customer: **are we losing business users?** and **why?**

## What's inside

```
.
├── databricks.yml              # Bundle config (variables, targets)
├── resources/
│   ├── genie_churn_job.job.yml # Daily serverless job (ingest -> gold)
│   └── genie_churn_app.app.yml # Streamlit Databricks App
├── src/
│   ├── notebooks/
│   │   ├── 01_ingest_genie_telemetry.ipynb   # Reads audit logs + Genie API (or generates synthetic data)
│   │   └── 02_build_gold_tables.ipynb        # Lifecycle, cohort, AI enrichment, churn drivers
│   └── app/
│       ├── app.py              # Streamlit app
│       ├── app.yaml            # App env config
│       └── requirements.txt
├── skill/
│   └── SKILL.md                # Genie Code skill for ad-hoc churn health checks
└── README.md
```

## Gold tables produced

| Table | Grain | Purpose |
| --- | --- | --- |
| `gold_user_lifecycle` | user | Active / At Risk / Churned status, activity and quality stats |
| `gold_monthly_user_health` | month | New, active, churned, at-risk, dormant, net change, churn rate |
| `gold_cohort_retention` | cohort x month | Month-N retention curves |
| `gold_enriched_messages` | message | Rephrase flag, latency bucket, AI failure reason, comment sentiment |
| `gold_churn_driver_summary` | lifecycle status | Churned vs active comparison |
| `gold_failure_reasons` | space x reason x status | What goes wrong, for whom |
| `gold_space_health` | space | Per-space quality and churn |
| `gold_user_risk` | user | Primary churn reason + 0-100 risk score |

## Prerequisites

* Databricks workspace with Unity Catalog enabled
* Workspace admin or metastore admin (for `system.access.audit`)
* A SQL warehouse (serverless recommended)
* Databricks CLI >= 0.281.0
* (Optional) Service principal with **CAN MANAGE** on Genie spaces to pull conversation text

## Quick start

```bash
# Clone and configure
git clone https://github.com/siddeshujjni/Genie_User_Churn_Analysis.git
cd Genie_User_Churn_Analysis

# Edit databricks.yml -> set your catalog, schema, warehouse
# Edit src/app/app.yaml -> set DATABRICKS_WAREHOUSE_ID, CATALOG, SCHEMA

# Validate
databricks bundle validate -t dev

# Deploy (dev uses synthetic data for a safe demo)
databricks bundle deploy -t dev

# Run the job
databricks bundle run genie_churn_job -t dev

# Deploy to production (reads real audit logs)
databricks bundle deploy -t prod
databricks bundle run genie_churn_job -t prod
```

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `catalog` | `main` | Unity Catalog catalog |
| `schema` | `genie_churn` | Schema for all raw and gold tables |
| `warehouse_id` | lookup | SQL warehouse for the app |
| `data_mode` | `production` | `production` or `synthetic` (demo) |
| `lookback_days` | `180` | Days of Genie history to ingest |
| `churn_days` | `30` | Days of inactivity = churned |
| `at_risk_days` | `14` | Days of inactivity = at risk |
| `include_conversation_text` | `true` | Pull question/answer text from the Genie API |

## Using the Genie Code skill

Copy `skill/SKILL.md` into your `.assistant/skills/genie-user-churn-analysis/` folder. Then ask Genie Code:

> "Run a Genie churn health check for this workspace"

It will run the queries from the skill directly against `system.access.audit`.

## Architecture

```
system.access.audit ──┐
                      ├─ 01_ingest ─► raw_* tables ─► 02_build_gold ─► gold_* tables ─► Streamlit App
Genie API ────────────┘                                    │
                                                    AI functions:
                                                    ai_classify (failure reason)
                                                    ai_analyze_sentiment (feedback)
```

## Security notes

* The app runs as a service principal. Grant it `USE CATALOG`, `USE SCHEMA`, and `SELECT` on the gold schema.
* Question text and Genie responses are customer data. The `include_conversation_text` parameter lets you skip API ingestion if not permitted.
* The `user_attributes_table` parameter enriches users with department/role from an HR or identity table without hard-coding the source.

