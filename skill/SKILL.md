---
name: genie-user-churn-analysis
description: |
  Analyse Genie business-user adoption and churn in a customer workspace.
  Reads system.access.audit (aibiGenie / genieChat) and optionally the Genie Conversation API.
  Produces lifecycle status, monthly health, cohort retention, AI failure classification, and churn drivers.
---

# Genie User Churn Analysis

## When to use
Use this skill when asked to assess Genie adoption health, identify churning users, understand why users leave, or build a churn report for a customer.

## Data sources

| Source | How to access | What it provides |
| --- | --- | --- |
| `system.access.audit` | `SELECT` by workspace admin | Who asked what, when, feedback ratings, channel (webapp/slack/teams) |
| Genie Conversation API | Service principal with CAN MANAGE on spaces | Question text, Genie responses, status, timings |
| Customer identity table (optional) | Parameter `user_attributes_table` | Department, role enrichment |

## Definitions

* **Active:** asked a question within the last 14 days
* **At Risk:** last question 15-30 days ago
* **Churned:** no questions for more than 30 days
* **Problem message:** failed status, negative feedback, response > 60s, or Genie response indicates an error / missing data
* **Churn risk score (0-100):** 40% inactivity + 30% recent problem rate + 15% usage decline + 15% recent negative feedback

## Quick health check (run these queries)

### 1. Lifecycle summary
```sql
WITH ua AS (
  SELECT
    user_identity.email AS user_email,
    DATE(MIN(event_time)) AS first_q,
    DATE(MAX(event_time)) AS last_q,
    COUNT(*) AS questions
  FROM system.access.audit
  WHERE service_name IN ('aibiGenie','genieChat')
    AND action_name IN ('createConversationMessage','genieStartConversationMessage','createGenieChatResponse')
    AND user_identity.email LIKE '%@%'
    AND event_date >= current_date() - INTERVAL 180 DAYS
  GROUP BY 1
)
SELECT
  CASE
    WHEN DATEDIFF(current_date(), last_q) > 30 THEN 'Churned'
    WHEN DATEDIFF(current_date(), last_q) > 14 THEN 'At Risk'
    ELSE 'Active'
  END AS status,
  COUNT(*) users,
  ROUND(AVG(questions), 1) avg_questions
FROM ua GROUP BY 1 ORDER BY 1;
```

### 2. Monthly new vs churned
```sql
WITH um AS (
  SELECT CAST(DATE_TRUNC('MONTH', event_time) AS DATE) AS m, user_identity.email AS e
  FROM system.access.audit
  WHERE service_name IN ('aibiGenie','genieChat')
    AND action_name IN ('createConversationMessage','genieStartConversationMessage','createGenieChatResponse')
    AND user_identity.email LIKE '%@%'
    AND event_date >= current_date() - INTERVAL 180 DAYS
  GROUP BY ALL
),
fm AS (SELECT e, MIN(m) AS cm FROM um GROUP BY 1),
active AS (SELECT m, COUNT(DISTINCT e) active_users FROM um GROUP BY 1),
new_u AS (SELECT cm AS m, COUNT(*) new_users FROM fm GROUP BY 1),
churned AS (
  SELECT ADD_MONTHS(p.m, 1) AS m, COUNT(DISTINCT p.e) churned_users
  FROM um p LEFT JOIN um c ON p.e = c.e AND c.m = ADD_MONTHS(p.m, 1)
  WHERE c.e IS NULL GROUP BY 1
)
SELECT a.m, a.active_users, COALESCE(n.new_users,0) new_users, COALESCE(c.churned_users,0) churned_users
FROM active a LEFT JOIN new_u n USING (m) LEFT JOIN churned c USING (m) ORDER BY 1;
```

### 3. Feedback health by space
```sql
SELECT
  request_params['space_id'] AS space_id,
  COUNT(*) total_feedback,
  COUNT_IF(request_params['feedback_rating'] IN ('THUMBS_UP','POSITIVE')) positive,
  COUNT_IF(request_params['feedback_rating'] IN ('THUMBS_DOWN','NEGATIVE')) negative,
  ROUND(COUNT_IF(request_params['feedback_rating'] IN ('THUMBS_DOWN','NEGATIVE')) * 100.0 / COUNT(*), 1) neg_pct
FROM system.access.audit
WHERE service_name = 'aibiGenie' AND action_name = 'updateConversationMessageFeedback'
  AND event_date >= current_date() - INTERVAL 90 DAYS
GROUP BY 1 ORDER BY negative DESC;
```

## Full deployment
For ongoing monitoring, deploy the DAB from this repo:
1. `databricks bundle deploy -t prod` — creates the daily job and the Streamlit app
2. The job runs the two notebooks that build the gold tables
3. The app reads the gold tables and shows trends, cohort retention, at-risk users, and churn drivers

See [README.md](../README.md) for setup details.

## Important notes
* Audit logs use `THUMBS_UP` / `THUMBS_DOWN`, not POSITIVE / NEGATIVE.
* Genie One chat events (Slack/Teams) are under `service_name = 'genieChat'` and have no `space_id`.
* The Conversation API needs CAN MANAGE to list all users' conversations in a space.
* The API has a 200,000 conversation limit per space.
