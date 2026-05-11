# Salesforce Scheduled Flow — Setup Guide

This flow runs on the first business day of each month, queries all stale accounts, builds a Slack Block Kit payload, and POSTs it to the NORAM sales pod group DM via an Incoming Webhook.

---

## Prerequisites

### 1. Remote Site Setting
Slack webhooks must be whitelisted before Salesforce can POST to them.

**Setup → Security → Remote Site Settings → New**

| Field | Value |
|---|---|
| Remote Site Name | `Slack_Webhooks` |
| Remote Site URL | `https://hooks.slack.com` |
| Active | ✅ |

---

## 2. Flow Overview

**Flow type:** Scheduled — Autolaunched Flow  
**Object:** Account  
**Schedule:** Monthly, 1st of month, 09:00 AM (your timezone)

---

## 3. Flow Steps

### Step 1 — Get Records (Stale Accounts)
- **Object:** Account  
- **Filter:** `Stale_Account__c = True`  
- **Sort:** Account Name ascending  
- **Store:** All records in a collection variable `varStaleAccounts`

### Step 2 — Text Template: Header Block
Create a text template `tmplSlackHeader` with this static JSON header:

```
{"blocks":[{"type":"header","text":{"type":"plain_text","text":":warning: Rules of Engagement — Stale Accounts Review","emoji":true}},{"type":"section","text":{"type":"mrkdwn","text":"The following accounts are flagged stale. Please *DROP* or *KEEP* each one by EOD Friday.\n\n*DROP* — moves to Sales Operations\n*KEEP* — clears stale flag"}},{"type":"divider"}
```

### Step 3 — Loop: For Each Account
Loop over `varStaleAccounts`. Inside the loop:

**3a. Assignment — Build account block**

Use an Assignment element to append to a text variable `varAccountBlocks`:

```
{"type":"section","text":{"type":"mrkdwn","text":"*{!varCurrentAccount.Name}*\nOwner: {!varCurrentAccount.Owner.Name}\nLast Activity: {!varCurrentAccount.LastActivityDate}"}},{"type":"actions","elements":[{"type":"button","text":{"type":"plain_text","text":":wastebasket: DROP","emoji":true},"style":"danger","action_id":"drop_account","value":"{!varCurrentAccount.Id}","confirm":{"title":{"type":"plain_text","text":"Drop this account?"},"text":{"type":"mrkdwn","text":"Transfers to Sales Operations. Confirm?"},"confirm":{"type":"plain_text","text":"Yes, drop it"},"deny":{"type":"plain_text","text":"Cancel"}}},{"type":"button","text":{"type":"plain_text","text":":white_check_mark: KEEP","emoji":true},"style":"primary","action_id":"keep_account","value":"{!varCurrentAccount.Id}"}]},{"type":"divider"}
```

> **Tip:** Use a Formula field or Flow formula to concatenate the loop variable's Id and Owner safely.

### Step 4 — Text Template: Footer + Close JSON
Create `tmplSlackFooter`:

```
{"type":"context","elements":[{"type":"mrkdwn","text":"Automated by Rules of Engagement | Run: {!$Flow.CurrentDateTime}"}]}]}
```

### Step 5 — Assignment: Assemble Final Payload
Concatenate into `varFinalPayload`:
```
{tmplSlackHeader} + {varAccountBlocks} + {tmplSlackFooter}
```

### Step 6 — HTTP Callout (Action)
Use a **Core Action: HTTP Callout** (available in Summer '23+) or an **Apex Action** calling `System.HttpRequest`.

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | Your Slack Incoming Webhook URL |
| Headers | `Content-Type: application/json` |
| Body | `{!varFinalPayload}` |

> If HTTP Callout Core Action isn't available in your org, use an Invocable Apex class — see the Apex snippet below.

---

## 4. Apex Fallback (if HTTP Callout Core Action unavailable)

```apex
public class SlackWebhookCallout {
    @InvocableMethod(label='Post to Slack Webhook')
    public static void post(List<String> payloads) {
        String webhookUrl = Label.Slack_Stale_Accounts_Webhook; // Custom Label
        HttpRequest req = new HttpRequest();
        req.setEndpoint(webhookUrl);
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setBody(payloads[0]);
        new Http().send(req);
    }
}
```

Store the webhook URL in a Custom Label (`Setup → Custom Labels → New`) named `Slack_Stale_Accounts_Webhook`.

---

## 5. Salesforce Connected App (for Lambda write-back)

**Setup → App Manager → New Connected App**

| Field | Value |
|---|---|
| Connected App Name | `Rules of Engagement Lambda` |
| Enable OAuth Settings | ✅ |
| Callback URL | `https://login.salesforce.com/services/oauth2/success` |
| Selected OAuth Scopes | `api`, `refresh_token` |
| Enable Client Credentials Flow | ✅ (recommended for server-to-server) |

After saving:
- Note the **Consumer Key** (= `SF_CLIENT_ID`) and **Consumer Secret** (= `SF_CLIENT_SECRET`)
- Create a dedicated integration user with a Profile that has edit access to Account.OwnerId and Account.Stale_Account__c
- Store credentials in AWS SSM (see `terraform/ssm.tf`)
