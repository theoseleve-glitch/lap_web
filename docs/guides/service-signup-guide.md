# LAP Racing — Service Signup Guide

> Follow each section in order. At the end, you'll have all the credentials
> needed to deploy the backend. Copy them into the checklist at the bottom
> and bring it back to Claude.

---

## SERVICE 1: Hetzner Cloud (VPS Server)

### What it is
Your backend server — runs Flask, PostgreSQL, and serves the API.

### Cost
~€10/month (CX22 server + 100 GB storage volume)

### Steps

1. Go to **https://www.hetzner.com/cloud/**
2. Click **Sign Up** — create an account (email + password)
3. Verify your email, add a payment method (credit card or PayPal)

#### Create the server

4. Go to **Cloud Console** → click **+ Create Server**
5. Configure:
   - **Location**: Falkenstein (FSN1) or Nuremberg (NBG1) — both in Germany, GDPR-friendly
   - **Image**: Ubuntu 24.04
   - **Type**: Shared vCPU → **CX22** (2 vCPU, 4 GB RAM, 40 GB disk)
   - **Networking**: Check both IPv4 and IPv6
   - **SSH Keys**: Click **Add SSH Key**
     - If you don't have one, open a terminal and run:
       ```
       ssh-keygen -t ed25519 -C "your-email@example.com"
       ```
     - Copy the contents of `~/.ssh/id_ed25519.pub` and paste it in
   - **Name**: `lap-api` (or whatever you like)
6. Click **Create & Buy Now**
7. Wait ~30 seconds — your server will appear with an **IPv4 address**

#### Attach a storage volume

8. In the Cloud Console, go to **Volumes** → **+ Create Volume**
9. Configure:
   - **Size**: 100 GB (can resize later with one click)
   - **Location**: Same as your server (Falkenstein or Nuremberg)
   - **Attach to**: select your `lap-api` server
   - **Mount point**: `/mnt/volume`
   - **Format**: ext4
10. Click **Create & Buy Now**

#### Set up the firewall

11. Go to **Firewalls** → **+ Create Firewall**
12. Add these inbound rules:
    - **SSH**: TCP, Port 22, Source: Any IPv4/IPv6
    - **HTTP**: TCP, Port 80, Source: Any IPv4/IPv6
    - **HTTPS**: TCP, Port 443, Source: Any IPv4/IPv6
13. Apply to your `lap-api` server

### What to write down

```
HETZNER_SERVER_IP = ___________________________  (e.g. 116.203.xxx.xxx)
```

---

## SERVICE 2: Cloudflare DNS (API Subdomain)

### What it is
Points `api.lap-coach.racing` to your Hetzner server.

### Cost
Free (you already use Cloudflare for the frontend).

### Steps

1. Log in to **Cloudflare Dashboard** → select your `lap-coach.racing` domain
2. Go to **DNS** → **Records** → **Add Record**
3. Configure:
   - **Type**: A
   - **Name**: `api`
   - **IPv4 address**: paste your Hetzner server IP from above
   - **Proxy status**: **DNS only** (grey cloud icon — NOT proxied!)
     > This is important! Click the orange cloud to turn it grey.
   - **TTL**: Auto
4. Click **Save**

#### Verify it works (after a few minutes)

Open a terminal and run:
```
ping api.lap-coach.racing
```
It should resolve to your Hetzner server IP.

### What to write down

```
API_DOMAIN = api.lap-coach.racing         (confirmed working: yes / no)
```

---

## SERVICE 3: Stripe (Payments)

### What it is
Processes credit card payments for your Performance and Pro Racer plans.

### Cost
Free to create. They take 2.9% + €0.25 per successful charge.

### Steps

#### Create account

1. Go to **https://dashboard.stripe.com/register**
2. Sign up with email + password
3. You'll start in **Test Mode** (orange banner) — this is fine for now

#### Create your 4 subscription prices

4. Go to **Products** (left sidebar) → **+ Add product**
5. Create **Product 1 — Performance**:
   - Name: `Performance`
   - Description: `Unlimited sessions, full scoring, corner coaching`
   - Click **Add price**:
     - Price: `8.99` EUR, Recurring, Monthly
     - Click **Add another price**:
     - Price: `69` EUR, Recurring, Yearly
   - Click **Save product**
6. Create **Product 2 — Pro Racer**:
   - Name: `Pro Racer`
   - Description: `Everything + dev plans, API access, 5 team seats`
   - Click **Add price**:
     - Price: `13.99` EUR, Recurring, Monthly
     - Click **Add another price**:
     - Price: `109` EUR, Recurring, Yearly
   - Click **Save product**

7. For each product, click on it to see the prices. Each price has an ID starting with `price_...` — copy all 4.

#### Get API keys

8. Go to **Developers** → **API keys** (or click the key icon in top-right)
9. Copy:
   - **Publishable key**: starts with `pk_test_...`
   - **Secret key**: click "Reveal test key" → starts with `sk_test_...`

#### Set up webhook

10. Go to **Developers** → **Webhooks** → **+ Add endpoint**
11. Configure:
    - **Endpoint URL**: `https://api.lap-coach.racing/api/v1/billing/webhook`
    - **Events to send** — click **+ Select events**, then check:
      - `checkout.session.completed`
      - `customer.subscription.created`
      - `customer.subscription.updated`
      - `customer.subscription.deleted`
      - `invoice.payment_failed`
    - Click **Add endpoint**
12. On the webhook page, click **Reveal** under "Signing secret" → copy it (starts with `whsec_...`)

### What to write down

```
STRIPE_PUBLISHABLE_KEY     = pk_test____________________________
STRIPE_SECRET_KEY          = sk_test____________________________
STRIPE_WEBHOOK_SECRET      = whsec_____________________________
STRIPE_PRICE_PERF_MONTHLY  = price_____________________________
STRIPE_PRICE_PERF_ANNUAL   = price_____________________________
STRIPE_PRICE_PRO_MONTHLY   = price_____________________________
STRIPE_PRICE_PRO_ANNUAL    = price_____________________________
```

---

## SERVICE 4: Google Cloud Console (OAuth — "Sign in with Google")

### What it is
Lets users click "Sign in with Google" instead of typing email/password.

### Cost
Free.

### Steps

#### Create project

1. Go to **https://console.cloud.google.com/**
2. Sign in with your Google account
3. Click the project dropdown (top-left, next to "Google Cloud") → **New Project**
   - Project name: `LAP Racing`
   - Click **Create**
4. Make sure the new project is selected in the dropdown

#### Configure consent screen

5. Go to **APIs & Services** → **OAuth consent screen** (left sidebar)
6. Select **External** → click **Create**
7. Fill in:
   - App name: `LAP`
   - User support email: your email
   - App logo: optional (can add later)
   - **App domain**:
     - Application home page: `https://www.lap-coach.racing`
     - Application privacy policy: `https://www.lap-coach.racing/privacy`
     - Application terms of service: `https://www.lap-coach.racing/terms`
   - **Authorized domains**: click **+ Add Domain** → type `lap-coach.racing`
   - Developer contact email: your email
8. Click **Save and Continue**
9. **Scopes** page: click **Add or Remove Scopes**
   - Search and check: `openid`, `email`, `profile`
   - (or just add `.../auth/userinfo.email` and `.../auth/userinfo.profile`)
   - Click **Update** → **Save and Continue**
10. **Test users** page: click **+ Add Users** → add your own email
    - (In test mode, only these emails can log in. After verification, anyone can.)
11. Click **Save and Continue** → **Back to Dashboard**

#### Create OAuth credentials

12. Go to **APIs & Services** → **Credentials** (left sidebar)
13. Click **+ Create Credentials** → **OAuth 2.0 Client ID**
14. Configure:
    - Application type: **Web application**
    - Name: `LAP Web Client`
    - **Authorized JavaScript origins**: click **+ Add URI**
      - `https://www.lap-coach.racing`
    - **Authorized redirect URIs**: click **+ Add URI**
      - `https://api.lap-coach.racing/auth/oauth/google/callback`
15. Click **Create**
16. A popup shows your **Client ID** and **Client Secret** — copy both

> **Note:** While your app is in "Testing" status, only the test users you
> added can log in. To let anyone use Google login, you'll need to submit
> for verification later (Step 22 in the deployment plan). This requires a
> privacy policy page (you already have one at /privacy).

### What to write down

```
GOOGLE_CLIENT_ID     = ______________________________.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET = GOCSPX-_________________________
```

---

## SERVICE 5: Resend (Transactional Email)

### What it is
Sends verification emails when users register, and password reset emails in the future.

### Cost
Free up to 3,000 emails/month.

### Steps

#### Create account

1. Go to **https://resend.com/**
2. Click **Get Started** → sign up with email or GitHub

#### Add your domain

3. Go to **Domains** (left sidebar) → **+ Add Domain**
4. Type: `lap-coach.racing`
5. Resend will show you **3 DNS records** to add. For each one:

   Go to **Cloudflare Dashboard** → DNS → Add Record:

   | Resend tells you | Cloudflare fields |
   |-----------------|-------------------|
   | SPF TXT record | Type: TXT, Name: (what they say), Content: (what they say) |
   | DKIM CNAME record 1 | Type: CNAME, Name: (what they say), Target: (what they say) |
   | DKIM CNAME record 2 | Type: CNAME, Name: (what they say), Target: (what they say) |
   | DMARC TXT record | Type: TXT, Name: `_dmarc`, Content: `v=DMARC1; p=none;` |

   > Set all records to **DNS only** (grey cloud).

6. Back in Resend, click **Verify Domain** — wait for green checkmark (usually 1-5 minutes)

#### Get API key

7. Go to **API Keys** (left sidebar) → **+ Create API Key**
   - Name: `LAP Production`
   - Permission: Sending access
   - Domain: `lap-coach.racing`
8. Copy the key (starts with `re_...`) — it's only shown once!

### What to write down

```
RESEND_API_KEY = re_________________________________
RESEND_DOMAIN_VERIFIED = yes / no
```

---

## FINAL CHECKLIST — Bring This Back to Claude

Copy this entire block, fill in the values, and paste it when you're ready:

```
=== HETZNER ===
Server IP:              _______________
Volume mounted:         yes / no
SSH access working:     yes / no

=== CLOUDFLARE DNS ===
api.lap-coach.racing:   resolves to correct IP?  yes / no
Proxy status:           DNS only (grey cloud)?   yes / no

=== STRIPE ===
Publishable key (pk_):  _______________
Secret key (sk_):       _______________
Webhook secret (whsec): _______________
Price ID — Performance Monthly:  price_____________
Price ID — Performance Annual:   price_____________
Price ID — Pro Racer Monthly:    price_____________
Price ID — Pro Racer Annual:     price_____________

=== GOOGLE OAUTH ===
Client ID:              _______________
Client Secret:          _______________

=== RESEND ===
API Key (re_):          _______________
Domain verified:        yes / no

=== ANYTHING ELSE ===
Questions or issues you ran into:
_______________________________________________
```

> **Security reminder:** These are secret keys. Don't share them in public
> channels, don't commit them to git. When you paste them to Claude, that's
> fine — but after we configure the server, store them only in the VPS `.env`
> file and in a password manager.
