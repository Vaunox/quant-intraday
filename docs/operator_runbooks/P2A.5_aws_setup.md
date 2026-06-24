# P2A.5 — AWS account preparation (operator walkthrough)

**Subtask:** P2A.5 (Phase 2A — Operator Actions). See the master blueprint, Part IV, and Part II
**"Cloud compute policy (AWS)"** (the authoritative account-hygiene rules this implements).
**Depends on:** none. Can run any time before P2.8.
**Audience:** the operator. This touches your AWS account, payment method, credits, MFA, and
credentials — all operator-only. The AI provides every step, the IAM policy, the Budgets config,
and the `aws/` config file; **the AI never holds your AWS credentials**.

---

## 0. Goal and scope

**Goal:** an AWS account **prepared** (hygiene + guardrails) so the P2.8 cloud research run and the
Phase-8 engine VPS are friction-free later — with **zero compute resources launched now**.

> ⛔ **NOTHING is launched in P2A.5.** No EC2 instance, no S3 bucket, no NAT Gateway, no Elastic
> IP. Those come later, in the subtask that needs them (S3 bucket + first spot run in **P2.8**;
> engine VPS + EIP in **P5A.1 / Phase 8**; NAT — **never**, per the cloud policy). P2A.5 only sets
> up the account so those moves are cheap and safe.

**This subtask is account hygiene only:** account exists → root secured → IAM user (least-priv) →
credits applied → Budgets armed → verify `aws sts get-caller-identity` → record.

---

## 1. Prerequisites & cost

- A **payment method** (AWS requires one even on free tier / with credits).
- Your **$150 credit code**, if you have one (AWS Activate / a promo). Not required to *prepare*
  the account — you can apply it whenever it's in hand.
- **No project spend in P2A.5** — nothing billable is created. (Account creation itself is free.)
- ~30–45 minutes. The AWS console UI changes often; if a screen differs from this script, tell me
  what you see and I'll map it.

---

## 2. Security model (Part II cloud policy — non-negotiable)

- **Never use the root account for project work.** Root is for account-level settings only, then
  locked away.
- **MFA on root *and* the IAM user.**
- **Region: `ap-south-1` (Mumbai)** for everything (latency to NSE; intra-region transfer is free).
- **Credentials never in the repo.** The IAM user's access key lives in your AWS credentials store
  (`~/.aws/credentials`, outside the repo) — never committed, never logged. Only **non-secret
  identifiers** (region, account ID, IAM ARN) go in the committed `aws/` config.

---

## 3. Step-by-step

### Step 1 — Create / sign in to the AWS account
1. If new: go to **https://aws.amazon.com → Create an AWS Account**; set the root email, a strong
   password, account name (e.g. `quant-intraday`), and add the payment method. Choose **Basic
   support (free)**.
2. If using an existing personal account: just sign in (as root, this once, to do Steps 2–6).

### Step 2 — Secure the root user
1. Console → **IAM → Dashboard** → enable **MFA on the root user** (authenticator app).
2. Do **not** create root access keys. If any exist, delete them.
3. After Steps 3–6, stop using root entirely.

### Step 3 — Apply the $150 credits (if you have a code)
1. Console → **Billing and Cost Management → Credits → Redeem credit** → paste the code.
2. Confirm the credit balance shows under **Credits**. (Skip if you don't have a code yet.)

### Step 4 — Create the project IAM user (+ MFA)
1. **IAM → Users → Create user**, name e.g. `quant-intraday-ops`.
2. Enable **console access** (set a password) **and** create an **access key** for **CLI /
   programmatic** use. **Copy the access key ID + secret once** (the secret is shown once).
   ⚠️ Don't paste them into chat or the repo — they go to `~/.aws/credentials` (Step 7).
3. After creating the user, enable **MFA on this IAM user** too.

### Step 5 — Attach the least-privilege policy
Create a customer-managed policy (IAM → Policies → Create policy → JSON) named
`quant-intraday-ops-policy` and attach it to the user. Least-privilege per Part II: read the
project S3 prefix, manage **spot** EC2 **in ap-south-1 only**, write CloudWatch logs — nothing
more. (S3/EC2 grants are for *later* use; no resources are created now.)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "WhoAmI",
      "Effect": "Allow",
      "Action": ["sts:GetCallerIdentity"],
      "Resource": "*"
    },
    {
      "Sid": "RegionLockedCompute",
      "Effect": "Allow",
      "Action": ["ec2:*", "cloudwatch:*", "logs:*"],
      "Resource": "*",
      "Condition": { "StringEquals": { "aws:RequestedRegion": "ap-south-1" } }
    },
    {
      "Sid": "ProjectS3",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::quant-intraday-*",
        "arn:aws:s3:::quant-intraday-*/*"
      ]
    },
    {
      "Sid": "DenyEverywhereButMumbai",
      "Effect": "Deny",
      "NotAction": ["sts:*", "iam:*", "s3:*", "budgets:*", "ce:*", "cur:*", "support:*"],
      "Resource": "*",
      "Condition": { "StringNotEquals": { "aws:RequestedRegion": "ap-south-1" } }
    }
  ]
}
```
*(`ec2:*` scoped to ap-south-1 is the pragmatic "manage spot EC2" grant; it can be tightened to
the specific RunInstances/spot actions later. The explicit region-deny is belt-and-suspenders so
nothing runs outside Mumbai. We refine S3 to the exact bucket once P2.8 creates it.)*

### Step 6 — Arm the cost guardrails (Budgets)
1. **Billing → Budgets → Create budget → Cost budget**. Set a small monthly amount (e.g. your
   credit balance, or a low cap like $20).
2. Add **alert thresholds at 50%, 80%, 100%** with **email notifications** to you. (Part II's
   "Cost guardrails".)
3. *(Optional backup)* a **CloudWatch billing alarm** (in `us-east-1`, where billing metrics live)
   as a second line of defense.

### Step 7 — Store the IAM credentials (outside the repo)
On your machine, put the IAM user's access key where the AWS CLI reads it natively — **not** in the
repo:
```powershell
# installs the key into %USERPROFILE%\.aws\credentials (outside the repo)
aws configure
#   AWS Access Key ID:     <paste>
#   AWS Secret Access Key: <paste>
#   Default region name:   ap-south-1
#   Default output format: json
```
*(If `aws` isn't installed: `winget install -e --id Amazon.AWSCLI`, then reopen the terminal.)*
This is the "secrets interface" for AWS tooling — credentials in `~/.aws/`, outside git, read by
the CLI/boto3's standard chain. (Phase 8 swaps this for AWS Secrets Manager on the VPS.)

### Step 8 — Verify (least-privilege check)
```powershell
aws sts get-caller-identity                 # -> your IAM user ARN + account ID (auth works)
aws ec2 describe-instances --region us-east-1   # -> should be DENIED (region-locked to Mumbai)
aws ec2 describe-instances --region ap-south-1   # -> allowed (empty list; nothing launched yet)
```
The first proves the IAM user authenticates; the second proves it can't act outside `ap-south-1`;
the third proves Mumbai access works and **nothing is running** (empty).

---

## 4. The `aws/` config (non-secret, committed)

After Step 8, the AI writes `aws/config.yaml` with the **non-secret identifiers** — region,
account ID, IAM user ARN — so the project has them on hand. No keys, no secrets. (If you'd rather
not publish your 12-digit account ID, say so and we'll gitignore `aws/` instead of committing it.)

---

## 5. Acceptance checklist (subtask "Done when")

- [ ] IAM user runs `aws sts get-caller-identity` from your machine (auth works).
- [ ] Least-privilege confirmed (an out-of-region action is denied).
- [ ] AWS **Budgets** alerts configured (50/80/100%).
- [ ] Credits applied & visible (if a code was available).
- [ ] **MFA on root** and **MFA on the IAM user**.
- [ ] `docs/PROGRESS.md` records prep complete — **date + account-ID-tail only** (never the keys).
- [ ] **No** EC2 / S3 / NAT / EIP created.

---

## 6. References (Ground Rule 9)

- Master blueprint, Part IV — **P2A.5**; Part II — **"Cloud compute policy (AWS)"** (account
  hygiene, cost guardrails, region lock, "what an AI agent must NOT do without approval").
- Prior: **P2A.4** (`docs/operator_runbooks/P2A.4_research_env.md`). Next: **P2A.6** (final P2.7
  run on real data) — which is **local**, not cloud; AWS gets used in **P2.8**.
