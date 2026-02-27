# Email Deliverability Setup — SPF/DKIM/DMARC

## Sending Domain
All transactional emails are sent from `noreply@lap-coach.racing` via Resend.

## DNS Records Required

### 1. SPF (Sender Policy Framework)
Authorizes Resend's mail servers to send on behalf of `lap-coach.racing`.

```
Type: TXT
Host: @
Value: v=spf1 include:amazonses.com ~all
```

> Resend uses Amazon SES under the hood. Check Resend dashboard for the
> exact `include:` value — it may be `include:_spf.resend.com`.

### 2. DKIM (DomainKeys Identified Mail)
Cryptographically signs outgoing emails. Resend generates the DKIM keys.

1. In Resend dashboard → Domains → Add `lap-coach.racing`
2. Resend will provide 3 CNAME records. Add them:

```
Type: CNAME
Host: resend._domainkey
Value: (provided by Resend)

Type: CNAME
Host: resend2._domainkey
Value: (provided by Resend)

Type: CNAME
Host: resend3._domainkey
Value: (provided by Resend)
```

3. Wait for DNS propagation (usually <1 hour)
4. Click "Verify" in Resend dashboard

### 3. DMARC (Domain-based Message Authentication)
Start with monitoring mode (`p=none`), then tighten after 2-4 weeks.

**Phase 1 — Monitoring (start here):**
```
Type: TXT
Host: _dmarc
Value: v=DMARC1; p=none; rua=mailto:dmarc@lap-coach.racing; pct=100
```

**Phase 2 — Quarantine (after confirming no false positives):**
```
Value: v=DMARC1; p=quarantine; rua=mailto:dmarc@lap-coach.racing; pct=100
```

**Phase 3 — Reject (production, after 30 days clean):**
```
Value: v=DMARC1; p=reject; rua=mailto:dmarc@lap-coach.racing; pct=100
```

## Verification

After adding all records, verify with:
- https://mxtoolbox.com/spf.aspx — SPF check
- https://mxtoolbox.com/dkim.aspx — DKIM check
- https://mxtoolbox.com/dmarc.aspx — DMARC check
- Resend dashboard — domain verification status

## Return-Path / Bounce Handling
Resend handles bounce processing automatically. No additional DNS records needed.
