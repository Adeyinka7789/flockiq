# FlockIQ User Manual

**Version:** 1.0  
**Date:** June 2026  
**Product:** FlockIQ — AI-Powered Poultry Farm Management  
**Published by:** ADM Tech Hub

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Daily Farm Operations](#2-daily-farm-operations)
3. [Understanding Your AI Insights](#3-understanding-your-ai-insights)
4. [Farm Credit Score](#4-farm-credit-score)
5. [Market Intelligence](#5-market-intelligence)
6. [Batch Management](#6-batch-management)
7. [Billing and Subscription](#7-billing-and-subscription)
8. [Account and Team Management](#8-account-and-team-management)
9. [Support](#9-support)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Getting Started

### 1.1 What is FlockIQ?

FlockIQ is an AI-powered poultry farm management platform built for Nigerian and West African farmers. It replaces paper logbooks with a structured digital system that tracks mortality, feed consumption, egg production, water usage, vaccinations, and financials — and then turns that data into actionable insights.

Key capabilities:

- ✅ Real-time breed-specific benchmarks for broilers (Cobb 500, Ross 308) and layers (Hy-Line Brown, ISA Brown)
- ✅ AI anomaly detection that alerts you when mortality or production drifts outside normal ranges
- ✅ Farm Credit Score — a bankable record of your farm's performance history
- ✅ Market Intelligence — crowdsourced feed prices and a hatchery directory with farmer reviews
- ✅ Works on any browser; no app download required
- ✅ Works offline — records sync automatically when connectivity is restored

### 1.2 System Requirements

FlockIQ is a web application. No installation is required.

| Requirement | Minimum | Recommended |
|---|---|---|
| Browser | Chrome 90+, Firefox 90+, Safari 15+, Edge 90+ | Chrome (latest) |
| Internet connection | 2G/EDGE (offline mode available) | 3G or Wi-Fi |
| Device | Smartphone, tablet, or computer | Tablet or laptop |
| Screen width | 320px | 768px or wider |

> ⚠️ **Internet Explorer is not supported.** Please use a modern browser.

### 1.3 Creating Your Account

1. Navigate to **[https://app.flockiq.com/signup/](https://app.flockiq.com/signup/)**.
2. Fill in your **full name**, **email address**, **phone number**, and choose a **password**.
3. Select your **country** and **state/region** — this sets your currency (₦ NGN) and timezone (WAT).
4. Enter your **farm or business name** — this becomes your organisation name and subdomain (e.g., `obasanjofarm.flockiq.com`).
5. Click **Create Account**.

You will be redirected to a verification page while a confirmation email is sent to the address you provided.

### 1.4 Email Verification

1. Check your inbox for an email from **FlockIQ \<noreply@flockiq.com\>** with the subject **"Confirm your FlockIQ account"**.
2. Click the **Verify Email** button in the email.
3. You will be redirected back to FlockIQ and logged in automatically.

> ⚠️ The verification link expires after **1 hour**. If it has expired, log in and click **Resend Verification Email** from the banner shown on your dashboard.

If you do not receive the email within 5 minutes, check your spam/junk folder. The sender address is `noreply@flockiq.com`.

### 1.5 Completing Onboarding

After verifying your email, FlockIQ guides you through a three-step setup:

**Step 1 — Create your Farm**

- Enter your farm's name, address, and location.
- A farm is the physical property. You can add multiple farms under one account.

**Step 2 — Add a House (Pen)**

- A house (or pen) is a structure on your farm where birds are kept.
- Enter the house name and capacity (maximum bird count).
- One farm can have many houses.

**Step 3 — Start your first Batch**

- A batch is one production cycle inside a house.
- Select the bird type (Broiler or Layer), breed, placement date, and number of birds placed (DOCs).
- Optionally select the hatchery where you purchased your day-old chicks.

Once all three steps are complete, your dashboard becomes active and data entry is unlocked.

### 1.6 Understanding Your Dashboard

The main dashboard (`/`) shows a real-time summary of your farm:

| Dashboard Card | What It Shows |
|---|---|
| **Active Batches** | All currently running production cycles across all farms |
| **Today's Tasks** | System-generated and custom tasks due today |
| **AI Insights** | Latest anomaly alerts, forecasts, and recommendations |
| **Weather** | Current conditions at your farm location |
| **Recent Activity** | A log of the last 10 data entries |
| **Farm Credit Score** | Your current grade and score (if at least 1 closed batch exists) |

The top navigation bar provides access to all sections: Farms, Batches, Production, Health, Finance, Market Intelligence, and Settings.

---

## 2. Daily Farm Operations

### 2.1 Logging Mortality

Record the number of birds that died on a given day.

**Where:** Navigate to **Batches → [Batch Name] → Mortality Log** and click **Record Mortality**.

**Fields:**

| Field | Description |
|---|---|
| **Date** | The date the deaths occurred (defaults to today) |
| **Count** | Number of birds that died |
| **Cause** | Optional — select from Newcastle Disease, Coccidiosis, Heat Stress, Injury, Unknown, etc. |
| **Notes** | Free-text observations |

**What happens after you save:**

- The batch's live bird count is automatically reduced.
- The system compares today's mortality against your rolling 30-day average.
- If the count is statistically unusual (Z-score > 2.5 or IQR outlier), an anomaly alert is created and sent to your farm manager via SMS and in-app notification.
- A financial write-down entry is posted to the farm ledger.

> ⚠️ You cannot log more deaths than the current live bird count. The form will reject this.

### 2.2 Logging Feed Consumption

Record how much feed was given to a batch today.

**Where:** **Batches → [Batch Name] → Feed Log → Record Feed**.

**Fields:**

| Field | Description |
|---|---|
| **Date** | Feed date (defaults to today) |
| **Feed Type** | Starter, Grower, Finisher, Layer Mash, Chick Mash |
| **Quantity (kg)** | Kilograms of feed given |
| **Brand** | Optional — TopFeeds, Chikun, Ultima, Animal Care, Hybrid, Other |

The system tracks cumulative feed consumption and uses it to calculate your batch's **Feed Conversion Ratio (FCR)** — the kilograms of feed required to produce one kilogram of live weight.

**Ideal FCR benchmarks:**

| Breed | Target FCR |
|---|---|
| Cobb 500 (Broiler) | ≤ 1.80 |
| Ross 308 (Broiler) | ≤ 1.75 |
| Hy-Line Brown (Layer) | ≤ 2.20 |
| ISA Brown (Layer) | ≤ 2.10 |

### 2.3 Logging Egg Production (Layers)

Record daily egg collection for a layer batch.

**Where:** **Batches → [Batch Name] → Production → Log Eggs**.

**Fields:**

| Field | Description |
|---|---|
| **Date** | Collection date |
| **Total Eggs** | Total eggs collected |
| **Cracked/Dirty** | Damaged eggs (subtracted from marketable count) |
| **Live Hen Count** | Current live hens on this date |

The system automatically calculates **Hen-Day Percentage (HDP)** — the proportion of live hens that laid an egg on that day. For Hy-Line Brown, the target HDP is ≥ 85%.

### 2.4 Logging Water Consumption

Record daily water consumption.

**Where:** **Batches → [Batch Name] → Water Log → Record Water**.

**Fields:**

| Field | Description |
|---|---|
| **Date** | Log date |
| **Volume (litres)** | Litres consumed |
| **Source** | Borehole, Municipal, Rainwater, Other |
| **Temperature (°C)** | Ambient temperature (used to calculate expected intake) |

The system compares actual consumption against the breed's expected intake (adjusted for heat — every degree above 25°C adds 10% to expected consumption). Significant drops trigger a water anomaly alert.

### 2.5 Recording Vaccinations

Track vaccination events per batch.

**Where:** **Health → Vaccinations → Record Vaccination**.

**Fields:**

| Field | Description |
|---|---|
| **Batch** | Select the target batch |
| **Vaccine Name** | e.g., Newcastle (Lasota), Gumboro, Marek's |
| **Date Administered** | Administration date |
| **Dose** | Quantity administered |
| **Method** | Drinking water, Eye drop, Injection, Spray |
| **Next Due Date** | System will send a reminder 48 hours before |
| **Administered By** | Staff member who performed the vaccination |

Vaccination reminders are sent via SMS and in-app notification at **07:00** on the morning the next dose is due.

### 2.6 Managing Tasks and Reminders

FlockIQ generates daily tasks automatically at midnight based on your active batches. You can also create custom tasks.

**Auto-generated tasks include:**

- Daily mortality count
- Daily feed weighing
- Daily egg collection (layers)
- Daily water log
- Weekly weight sampling (broilers)
- Upcoming vaccination reminders

**Where to view:** **Tasks** from the top navigation bar.

**Creating a custom task:**

1. Click **New Task**.
2. Enter the task title, assign it to a team member, and set a due date.
3. The assigned user receives an in-app notification.

**Completing a task:** Click the checkbox next to the task. Incomplete tasks trigger a daily report sent to the farm manager at **18:00**.

---

## 3. Understanding Your AI Insights

### 3.1 AI Daily Brief

The AI Daily Brief appears at the top of your dashboard each morning. It is generated overnight (between 01:00 and 06:30 WAT) and covers:

- **Mortality anomaly status** — whether yesterday's mortality was normal or suspicious
- **Egg production forecast** — predicted hen-day percentage for the next 14 days (layer batches only)
- **Feed efficiency summary** — how your current FCR compares to breed benchmark
- **Weather-adjusted water requirement** — litres needed today based on current temperature
- **Upcoming vaccinations** — any doses due in the next 7 days

> ⚠️ AI insights require at least **21 days of production data** for the egg forecast model and at least **7 days of mortality data** for anomaly detection.

### 3.2 Farm Memory

Farm Memory is FlockIQ's learning system. Every night, the platform recomputes baseline performance metrics from your closed batches:

- Average mortality rate by batch age and season
- Average FCR by breed
- Typical egg production curve for your flock

These baselines make anomaly detection progressively more accurate over time — the more batches you complete, the smarter your alerts become.

Farm Memory data feeds directly into your **Farm Credit Score** (see Section 4).

### 3.3 Proactive Alerts

Alerts are sent via **SMS** (to your registered phone number) and **in-app notifications** (bell icon in the top navigation). The following events trigger automatic alerts:

| Alert | Trigger Condition |
|---|---|
| **Mortality Anomaly** | Today's deaths are more than 2.5 standard deviations above your 30-day average |
| **Water Drop** | Water consumption is more than 20% below expected for ambient temperature |
| **Production Drop** | Layer HDP drops more than 10 percentage points in 3 days |
| **Vaccination Due** | Vaccine booster is due within 48 hours |
| **Incomplete Tasks** | Tasks not marked complete by 18:00 each day |
| **Trial Expiring** | Your free trial ends in 7, 3, or 1 day |
| **Subscription Expiring** | Your paid plan expires in 7, 3, or 1 day |

All alerts also appear in the **Notifications** panel (bell icon). Click any notification to see the detail and take action.

### 3.4 Harvest Timing Optimizer

For broiler batches, FlockIQ monitors live weight progression and market price data to recommend an optimal harvest window.

**Where:** **Batches → [Batch Name] → Analytics → Harvest Recommendation**.

The recommendation considers:

- Current FCR trajectory (if FCR is worsening, earlier harvest may be more profitable)
- Live bird market price trend from the Market Intelligence module
- Remaining days to reach target weight based on breed standard

The recommendation is marked as **"Sell Now"**, **"Wait"**, or **"Monitor"** with a brief explanation.

### 3.5 Feed Efficiency Analysis

**Where:** **Batches → [Batch Name] → Analytics → Feed Efficiency**.

This page compares your batch's actual FCR week-by-week against the breed standard:

| FCR Rating | Meaning |
|---|---|
| **Excellent** | FCR is 5% or more better than target |
| **Good** | FCR meets the breed target |
| **Acceptable** | FCR is within 10% above target |
| **Poor** | FCR exceeds target by more than 10% |

A **poor** rating sustained for two or more weeks triggers a recommendation to review your feeding programme.

---

## 4. Farm Credit Score

### 4.1 What Is the Farm Credit Score?

The Farm Credit Score is a 0–100 numerical rating of your farm's operational and financial performance. It is designed to serve as a credibility document when applying for farm input loans, feed credit, or grant programmes. The score is accompanied by a **grade** (A+ to F) and a **confidence level** based on how many production cycles you have completed.

### 4.2 How It Is Calculated

The score is computed from six weighted components:

| Component | Weight | What It Measures |
|---|---|---|
| **Financial Health** | 30% | Consistency of profit margin across batches |
| **Operational Consistency** | 20% | Regularity of daily data logging |
| **Mortality Management** | 20% | Mortality rate versus industry benchmark |
| **Feed Efficiency** | 15% | FCR versus breed benchmark (broilers); neutral for layers |
| **Platform Engagement** | 10% | Regularity of subscription payments |
| **Payment History** | 5% | Plan tier commitment (Yearly > Monthly > Cycle > Trial) |

**Financial Health scoring (per batch):**

| Profit Margin | Sub-Score |
|---|---|
| ≥ 30% | 100 |
| 20–29% | 80 |
| 10–19% | 60 |
| 0–9% | 40 |
| Negative | 20 |

**Mortality Management scoring:**

| Mortality Rate | Sub-Score |
|---|---|
| < 2% | 100 |
| 2–4.9% | 80 |
| 5–9.9% | 60 |
| 10–14.9% | 40 |
| ≥ 15% | 20 |

The system analyses your most recent 12 closed batches. Total score = weighted average of all six components, capped at 100.

**Grade scale:**

| Score | Grade |
|---|---|
| 90–100 | A+ |
| 80–89 | A |
| 70–79 | B |
| 60–69 | C |
| 50–59 | D |
| < 50 | F |

### 4.3 Confidence Levels

The confidence level indicates how much historical data backs the score:

| Closed Batches | Confidence Level |
|---|---|
| 1–2 | **Early** — treat as indicative only |
| 3–5 | **Growing** — increasingly reliable |
| 6+ | **Established** — strong historical basis |

A lender should place greater weight on an **Established** score than an **Early** one.

### 4.4 How to Improve Your Score

| Target Area | Actions That Help |
|---|---|
| Financial Health | Reduce feed wastage, improve FCR, review selling price |
| Operational Consistency | Log data every day — even if nothing happened |
| Mortality Management | Maintain biosecurity protocols, vaccinate on schedule |
| Feed Efficiency | Source quality DOCs, weigh feed accurately |
| Platform Engagement | Maintain a paid subscription, pay on time |
| Payment History | Upgrade to a Yearly plan for maximum points |

The score is recomputed automatically every night at **03:00 WAT**. Changes appear on your dashboard the next morning.

### 4.5 Downloading and Sharing Your PDF Report

**Where:** **Finance → Farm Credit Score → Download PDF Report**.

The PDF includes:

- Your farm name, organisation ID, and report date
- Overall score and grade with confidence level
- A bar chart of all six component scores
- Key statistics: average profit margin, average mortality rate, average FCR, total birds managed, months on platform
- A verification statement for lenders

The PDF is generated immediately and opens in a new browser tab for saving or printing.

> ✅ The report is branded with your farm logo if you have uploaded one in Settings.

### 4.6 Using Your Score with Lenders

When presenting the PDF to a financial institution or feed supplier:

1. Download the report and save the PDF.
2. Share it alongside your sales records and batch financial summaries (also exportable from Finance).
3. Your organisation ID (shown on the report) can be used by the lender to verify the report's authenticity with ADM Tech Hub.

---

## 5. Market Intelligence

### 5.1 Feed Price Tracker

The Feed Price Tracker is a crowdsourced database of feed prices submitted by FlockIQ users across Nigeria. Prices are aggregated anonymously — your individual submission is never displayed to other users.

**Where:** **Market → Feed Prices**.

**Reading the price chart:**

- Prices are shown per **25 kg bag** in Nigerian Naira (₦).
- Filter by **feed type** (Broiler Starter, Broiler Grower, Broiler Finisher, Layer Mash, Layer Chick Mash) and **brand**.
- A trend line shows price movement over the past 30 days.
- Regional data is available for all 36 states and FCT.

**Submitting a price report:**

1. Click **Report a Price**.
2. Select the feed type and brand.
3. Enter the price you paid per 25 kg bag.
4. Select your state and LGA (Local Government Area).
5. Click **Submit**.

Submissions are reviewed for obvious outliers before being included in the community average. Thank you for contributing — your reports help fellow farmers make better purchasing decisions.

### 5.2 Hatchery Directory

The Hatchery Directory lists verified and farmer-reported day-old chick (DOC) suppliers across Nigeria.

**Where:** **Market → Hatcheries**.

**What you can see:**

- Hatchery name, state, LGA, and contact information
- Bird types available (Broiler, Layer, Noiler, Turkey)
- **Verified** badge — indicates ADM Tech Hub has confirmed the hatchery is operating
- Community ratings — average scores for DOC quality, delivery reliability, and overall satisfaction

**Searching for a hatchery:**

- Filter by **state** and **bird type**.
- Click any listing to see the full profile including all farmer reviews.

### 5.3 Rating a Hatchery After Batch Close

When you close a batch, FlockIQ automatically checks whether that batch was linked to a hatchery (set at batch creation). If so, you will see a prompt: **"Rate your DOC supplier for this batch."**

**Rating criteria:**

| Criteria | Scale |
|---|---|
| DOC Quality | 1–5 stars |
| Survival Rate (%) | Your batch's actual survival rate |
| Delivery Reliability | 1–5 stars (on-time delivery) |
| Overall Rating | 1–5 stars |

You may also leave a written comment. Reviews are attributed to your farm anonymously — your name is never shown on the directory.

### 5.4 Suggesting a New Hatchery

If you purchased DOCs from a hatchery not listed in the directory:

1. On the Hatchery Directory page, click **Suggest a Hatchery**.
2. Enter the hatchery name, state, LGA, and any available contact details.
3. Submit for review.

Suggestions are reviewed by ADM Tech Hub within 5 business days. Verified listings are added to the directory and you receive an in-app notification when published.

---

## 6. Batch Management

### 6.1 Creating a Batch

**Where:** **Batches → New Batch** or from the Farms page, select a house and click **Start Batch**.

**Required fields:**

| Field | Description |
|---|---|
| **Batch Name** | A name to identify this production cycle (e.g., "March Broiler Run") |
| **Farm** | The farm this batch belongs to |
| **House** | The pen or house within the farm |
| **Bird Type** | Broiler or Layer |
| **Breed** | Select from Cobb 500, Ross 308, Hy-Line Brown, ISA Brown, or enter a custom breed name |
| **Placement Date** | The date day-old chicks were placed |
| **Initial Count** | Number of DOCs placed |

**Optional DOC tracking fields:**

| Field | Description |
|---|---|
| **Hatchery** | Select from the Hatchery Directory |
| **DOC Price per Chick (₦)** | Price paid per chick |
| **Supplier Name** | If the hatchery is not in the directory |

> ✅ Linking a hatchery at batch creation enables automatic post-close rating prompts and improves the hatchery directory's accuracy.

### 6.2 Understanding the Batch Lifecycle

A batch moves through these states:

```
Active → Closed (normal harvest)
Active → Culled (emergency culling, disease response)
```

**Active:** Data entry is fully open. All daily logs (mortality, feed, eggs, water) are accepted.

**Closed:** The batch has been harvested. Data entry is locked. Analytics and financial summaries are calculated. A hatchery rating prompt appears if applicable.

**Culled:** The batch was terminated early. The same analytics apply but the event is flagged separately in reports.

### 6.3 Closing a Batch

**Where:** **Batches → [Batch Name] → Close Batch**.

When closing a broiler batch, you will be prompted to enter:

- **Final bird count** (live birds at harvest)
- **Total live weight (kg)** — used for final FCR calculation
- **Sale price per kg (₦)** — used for revenue calculation
- **Harvest date**

When closing a layer batch, you will be prompted to enter:

- **Depletion count** (hens sold or culled at batch end)
- **Spent layer price per bird (₦)**
- **Closing date**

After closing, the system generates:

- A final **Batch Performance Report** (FCR, mortality rate, hen-day average)
- A **Profit & Loss Summary** for the batch
- An updated **Farm Credit Score** (recomputed at 03:00 the following night)

### 6.4 Reading Batch Analytics

**Where:** **Batches → [Batch Name] → Analytics**.

The analytics page shows:

| Section | Contents |
|---|---|
| **Performance Summary** | FCR, cumulative mortality rate, average HDP (layers), total days |
| **Weekly Trend Charts** | Mortality, feed consumption, egg production over time |
| **Breed Benchmark Comparison** | Your actual performance vs. the breed standard week by week |
| **Financial Summary** | Revenue, feed cost, medication cost, mortality loss, gross profit, margin |
| **AI Forecast** | Remaining predicted egg production for active layer batches |

All charts can be exported to PDF (requires `pdf_export` feature to be enabled on your plan).

---

## 7. Billing and Subscription

### 7.1 Plan Types

FlockIQ offers four billing options:

| Plan | Description | Best For |
|---|---|---|
| **Trial** | 14-day free access to all features | New users evaluating the platform |
| **Monthly** | Fixed monthly fee, billed every 30 days | Farms wanting flexible commitment |
| **Cycle** | Billed per active broiler batch | Farms with variable batch schedules |
| **Yearly** | Annual fee with a discount vs monthly | Established farms seeking the best value |

Plan prices are shown in Nigerian Naira (₦). All payments are processed by **Paystack** — a secure Nigerian payment gateway.

### 7.2 What Happens When Your Trial Expires

Your free trial runs for **14 days** from account creation. During the trial:

- All features are fully accessible.
- A trial countdown banner appears at the top of every page.
- Reminder notifications are sent 7, 3, and 1 day before expiry.

When the trial ends:

- Your account enters **read-only mode** — you can view all your data but cannot add new records.
- No data is deleted.
- A banner with a **Subscribe Now** button appears on your dashboard.

### 7.3 Renewing or Upgrading Your Plan

**Where:** **Settings → Billing** or click the subscription banner on your dashboard.

1. Select your preferred plan (Monthly, Cycle, or Yearly).
2. Click **Subscribe**.
3. You are redirected to the Paystack checkout page.
4. Enter your card details or bank account.
5. Upon successful payment, your account is immediately upgraded.

You will receive an email receipt from Paystack and an in-app notification confirming activation.

### 7.4 What Lapsed Access Means

If you are on a paid plan and your plan expires without renewal:

- Your account enters **lapsed** status.
- All existing data remains visible (read-only).
- Data entry (logging mortality, feed, eggs, etc.) is blocked.
- A **Renew Plan** button appears on your dashboard.

Lapsed access is different from trial expiry — lapsed accounts have a prior payment history and retain full data visibility indefinitely.

> ⚠️ No data is ever deleted due to subscription status. Your records are safe regardless of billing state.

### 7.5 Payment via Paystack

FlockIQ uses Paystack as its payment processor. Paystack supports:

- **Debit/Credit cards** (Mastercard, Visa, Verve)
- **Bank transfer**
- **USSD** (for supported Nigerian banks)

All transactions are in **Nigerian Naira (₦)**. Your card details are processed by Paystack — FlockIQ never stores card numbers.

---

## 8. Account and Team Management

### 8.1 Updating Your Profile

**Where:** Click your avatar or initials in the top-right corner → **Profile Settings**.

You can update:

- Full name and phone number
- State/region and timezone
- Profile photo
- Password (requires current password)

### 8.2 Adding Team Members

**Where:** **Settings → Team Members → Invite Member**.

1. Enter the new member's email address.
2. Select their **role** (see role table below).
3. Click **Send Invitation**.

The invited person receives an email with a sign-up link. Upon completing registration, they are automatically added to your organisation.

### 8.3 Role Permissions

| Role | Create/Edit Data | View Reports | Manage Team | Billing | Settings |
|---|---|---|---|---|---|
| **Owner** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Manager** | ✅ | ✅ | ✅ | ❌ | Partial |
| **Supervisor** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Data Entry** | ✅ (logs only) | ❌ | ❌ | ❌ | ❌ |
| **Vet Advisor** | Health only | Health only | ❌ | ❌ | ❌ |

> ✅ Only the **Owner** can access billing, cancel subscriptions, or delete the organisation.

### 8.4 Custom Domain Setup

On eligible plans, you can serve FlockIQ from your own domain (e.g., `app.myfarm.com`) instead of `myfarm.flockiq.com`.

**Where:** **Settings → Custom Domain**.

**Steps:**

1. Enter your domain in the Custom Domain field (e.g., `app.myfarm.com`).
2. Click **Generate Verification Token**.
3. Log in to your domain registrar (e.g., GoDaddy, Namecheap) and add the TXT record shown.
4. Return to FlockIQ and click **Verify Domain**.
5. DNS propagation may take up to 24 hours.
6. Once verified, point a CNAME record to `app.flockiq.com`.

> ⚠️ Do not complete Step 6 before Step 5. Pointing your CNAME before verification is complete will prevent the verification check from working.

### 8.5 Exporting Your Data (NDPR Compliance)

Under the Nigeria Data Protection Regulation (NDPR), you have the right to a copy of all data FlockIQ holds about you and your farm.

**Where:** **Settings → Data & Privacy → Export My Data**.

This generates a full export of:

- All batch records, mortality logs, feed logs, egg production logs, water logs
- Financial records (expenses, sales, ledger entries)
- Notification history
- Account details

The export is prepared as a downloadable ZIP file containing CSV and JSON files.

### 8.6 Deleting Your Account

**Where:** **Settings → Data & Privacy → Delete Account**.

> ⚠️ Account deletion is permanent. All your data will be erased after a 30-day cooling-off period. This action cannot be undone.

During the 30-day cooling-off period, you can cancel the deletion request by logging in and clicking **Cancel Deletion**.

---

## 9. Support

### 9.1 Submitting a Support Ticket

**Where:** **Help → Contact Support** or visit the in-app help page at `/help/`.

1. Describe your issue clearly, including what you were doing and what happened.
2. Attach a screenshot if relevant (drag and drop or browse).
3. Click **Submit Ticket**.

You will receive an email confirmation with your ticket number. Expect a response within **1 business day** during working hours (08:00–18:00 WAT, Monday–Friday).

### 9.2 Viewing Ticket History

**Where:** **Help → My Support Tickets**.

All your submitted tickets appear here with their current status (Open, In Progress, Resolved).

### 9.3 Contact Information

| Channel | Details |
|---|---|
| **In-app support** | Help → Contact Support |
| **Email** | support@flockiq.com |
| **Phone/WhatsApp** | Available on your billing page (plan-dependent) |
| **Website** | https://flockiq.com/contact/ |

Priority phone support is available on Yearly plan subscriptions.

---

## 10. Troubleshooting

### 10.1 Common Issues and Solutions

**"I cannot log data — the buttons are greyed out"**

- Your subscription may have lapsed or your trial may have expired. Check **Settings → Billing** and renew your plan.
- Your account role may not have data entry permissions. Contact your Organisation Owner to check your role.

**"I cannot see some of my batches"**

- Ensure you are logged into the correct organisation. Click your organisation name in the top bar to confirm.
- Check the batch status filter — closed batches may be hidden by default.

**"The AI Daily Brief is missing"**

- AI forecasting requires a minimum of 21 days of production data for the egg forecast. Keep logging daily and the brief will populate automatically.
- AI features require your plan to have them enabled. Check with support if you believe they should be active.

**"I submitted data but it is not showing up"**

- If you were offline when you submitted, the data is queued locally. The sync indicator (top right) will show a spinner. Ensure you have a network connection and wait for the sync to complete.
- If the sync indicator shows an error, try refreshing the page.

**"Notifications are not arriving by SMS"**

- Ensure your phone number is correct in **Profile Settings**.
- Verify that SMS notifications are enabled in **Settings → Notifications**.
- Check that your number is in E.164 format (e.g., +2348012345678).

### 10.2 Session Expiry and Re-Login

FlockIQ sessions expire after **2 hours of inactivity**. When your session expires:

- You will see a message: **"Your session has expired. Please log in again."**
- Any data you have entered but not yet saved may be lost.
- Click **Log In** to authenticate and return to where you were.

> ✅ **Tip:** Submit each log entry as you go rather than filling in multiple records before saving. This minimises data loss if your session expires.

### 10.3 Data Not Syncing

If you notice that offline records are not syncing:

1. Check that you have an active internet connection.
2. Open **Settings → Sync Status** to see any queued records and their sync state.
3. If records are stuck in a "conflict" state, it means a similar record already exists for the same batch and date. Review the conflict and choose which record to keep.
4. If the problem persists, contact support with your batch name and the dates of the affected logs.

---

*FlockIQ User Manual v1.0 — ADM Tech Hub — June 2026*  
*For feedback on this manual, email support@flockiq.com*
