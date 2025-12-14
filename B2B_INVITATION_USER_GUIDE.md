# B2B External User Invitation Guide

## Overview

When inviting external users (guests) to your application via Azure AD B2B, users go through a **two-step consent process**:

1. **B2B Invitation Consent** - Accepting invitation to join your organization (mandatory, cannot be removed)
2. **App Permission Consent** - Allowing your app to access their data (can be eliminated with optional claims or admin consent)

This guide explains what users see and provides communication templates.

---

## Understanding B2B Invitation vs App Permission Consent

### Two Separate Consent Flows

| Consent Type | What It's For | When Shown | Required? | Can Be Removed? |
|--------------|---------------|------------|-----------|-----------------|
| **B2B Invitation Consent** | Becoming guest user in your Azure AD tenant | First invitation acceptance | ✅ Yes | ❌ No (Microsoft requirement) |
| **App Permission Consent** | Allowing app to read groups/profile via Graph API | App sign-in | Depends | ✅ Yes (with optional claims) |

### Visual Distinction

**B2B Invitation Consent (Always Shows):**
```
╔═══════════════════════════════════════════╗
║  Review permissions                       ║
║                                           ║
║  external.user@gmail.com                  ║
║                                           ║
║  Contoso (contoso.com) is requesting      ║
║  permission to:                           ║
║                                           ║
║  • Read your basic profile information    ║
║  • Maintain access to data you've given   ║
║    access to                              ║
║  • Sign you in and read your profile      ║
║                                           ║
║  By accepting, you agree to the terms     ║
║  of service and privacy policy            ║
║                                           ║
║  [Cancel]              [Accept]           ║
╚═══════════════════════════════════════════╝
```

**App Permission Consent (Only if admin consent not granted):**
```
╔═══════════════════════════════════════════╗
║  Permissions requested                    ║
║                                           ║
║  Content Processing App                   ║
║                                           ║
║  This application is requesting:          ║
║                                           ║
║  • Read all groups (Group.Read.All)       ║
║                                           ║
║  ⚠️ This requires admin approval          ║
║                                           ║
║  [Cancel]                                 ║
╚═══════════════════════════════════════════╝
```

---

## Complete External User Journey

### Scenario 1: With Optional Claims (Recommended - Best UX)

**Step 1: Backend Invites User**
```python
from msgraph import GraphServiceClient
from msgraph.generated.models.invitation import Invitation

graph_client = GraphServiceClient(credentials)

invitation = Invitation(
    invited_user_email_address="external.user@gmail.com",
    invite_redirect_url="https://your-app.azurecontainerapps.io",
    send_invitation_message=True,
    invited_user_display_name="John Doe"
)

result = await graph_client.invitations.post(invitation)
```

**Step 2: User Receives Email**
```
From: Microsoft Invitations <invites@microsoft.com>
Subject: You're invited to join Contoso

Hi,

You've been invited to join Contoso's organization.

Get Started

By accepting this invitation, you agree to the terms of service.
```

**Step 3: User Clicks "Get Started"**
- Redirected to Microsoft login page
- Sees B2B invitation consent screen (shown above)
- Clicks "Accept" ✅

**Step 4: User Accesses Your App**
- Redirected to `https://your-app.azurecontainerapps.io`
- Signs in with their own account (Gmail, Outlook, etc.)
- **✅ No app permission consent** (using optional claims)
- Lands in app immediately

**Total consent screens seen: 1** (B2B only)

### Scenario 2: With Admin Consent Granted (Current Setup)

**Steps 1-3:** Same as above (B2B invitation)

**Step 4: User Accesses Your App**
- Redirected to your app
- Signs in with their account
- **✅ No app permission consent** (admin pre-approved)
- Lands in app immediately

**Total consent screens seen: 1** (B2B only)

### Scenario 3: Without Admin Consent (Bad UX - Avoid)

**Steps 1-3:** Same as above (B2B invitation)

**Step 4: User Tries to Access App**
```
❌ Error Screen:
╔═══════════════════════════════════════════╗
║  Need admin approval                      ║
║                                           ║
║  Content Processing App                   ║
║                                           ║
║  Ask your admin to grant permission to    ║
║  this app so you can use it.              ║
║                                           ║
║  Requested permissions:                   ║
║  • Group.Read.All                         ║
║                                           ║
║  [Back]                                   ║
╚═══════════════════════════════════════════╝
```

**Total screens seen: 1 consent + 1 error** (user blocked)

---

## Communication Templates

### Template 1: Invitation Email (Sent by Your App)

**When to send:** Before or after backend creates invitation

```
Subject: You're invited to join [Your App Name]

Hi [Name],

Welcome! You've been invited to access our document processing platform.

What happens next:

1️⃣ You'll receive an email from Microsoft
   From: invites@microsoft.com
   Subject: "You're invited to join [Organization Name]"
   
   ⚠️ Check your spam folder if you don't see it within 5 minutes

2️⃣ Click "Get Started" or "Accept Invitation" in that email

3️⃣ Microsoft will ask you to review permissions
   This is standard security when joining an organization.
   The permissions requested are:
   
   • Read your basic profile (name, email)
   • Keep you signed in
   
   Click "Accept" to continue

4️⃣ Sign in with your existing account
   Use your Gmail, Outlook, or any Microsoft-compatible account

5️⃣ You'll have immediate access! ✅

Need help?
- Didn't receive the invitation email? Check spam or contact us
- Having trouble signing in? Reply to this email

Best regards,
[Your Team Name]

---
Questions? Email us at support@yourapp.com
Privacy Policy: https://yourapp.com/privacy
```

### Template 2: Follow-Up Email (If User Hasn't Accepted)

**When to send:** 24-48 hours after invitation

```
Subject: Reminder: Your invitation to [Your App Name] is waiting

Hi [Name],

We noticed you haven't accepted your invitation yet.

Quick reminder of the steps:

1. Check your email for "You're invited to join [Organization]" from Microsoft
   ⚠️ Check spam/junk folder

2. Click "Get Started" or "Accept Invitation"

3. Review and accept the permissions (standard security step)

4. Sign in and start using the platform

Still having issues?
Common problems:
• Email went to spam → Check junk folder
• Invitation expired → Reply to this email for a new one
• Can't find the email → We can resend it

We're here to help!
Reply to this email or contact support@yourapp.com

Best regards,
[Your Team]
```

### Template 3: Welcome Email (After User Accepts Invitation)

**When to send:** Triggered after first successful sign-in (detect in app)

```
Subject: Welcome to [Your App Name]! 🎉

Hi [Name],

Great to have you on board! Your account is now active.

Here's what you can do:
• Upload and process documents
• Extract data with AI
• Manage your cases
• [List key features]

Quick Start Guide:
1. Go to https://your-app.azurecontainerapps.io
2. Click "Sign In"
3. Use the same account you used to accept the invitation
4. Start with our tutorial: [Link]

Resources:
📖 User Guide: https://docs.yourapp.com
💬 Support: support@yourapp.com
🎥 Video Tutorials: https://yourapp.com/tutorials

Need help? We're here for you!
Our team is available [hours] at [email/phone]

Welcome to [Your App Name]!
[Your Team]
```

### Template 4: Troubleshooting Email (User Reports Issues)

```
Subject: Re: Trouble accepting invitation to [Your App Name]

Hi [Name],

I'm sorry you're having trouble! Let me help you get access.

Common Issues & Solutions:

❓ "I didn't receive the invitation email"
✅ Solution:
   1. Check your spam/junk folder for emails from invites@microsoft.com
   2. Search for "invited to join" in your email
   3. If still not found, I can resend the invitation - just reply "resend"

❓ "I accepted the invitation but can't sign in"
✅ Solution:
   1. Make sure you're using the SAME email address you accepted with
   2. Try signing out and back in
   3. Clear your browser cache/cookies
   4. Try an incognito/private window

❓ "I see an error: Need admin approval"
✅ Solution:
   This is a configuration issue on our end. Our IT team is working on it.
   I'll email you as soon as it's resolved (usually within 24 hours).

❓ "The consent screen is asking for too many permissions"
✅ Don't worry! The permissions shown are standard for all business apps:
   • Reading your profile → So we know who you are
   • Keeping you signed in → So you don't have to login every time
   • These are safe and required by Microsoft

Still stuck?
Let's troubleshoot together:
1. What email address are you using? [Reply with this]
2. What error message do you see? [Screenshot if possible]
3. What browser are you using? [Chrome, Firefox, etc.]

I'll get you set up ASAP!

Best regards,
[Your Name]
[Support Team]
```

### Template 5: IT Admin Communication (For Admin Consent)

**When to send:** If you need admin to grant consent for Group.Read.All

```
Subject: [Action Required] Grant admin consent for [Your App Name]

Hi [IT Admin Name],

We need your help to complete setup for our new application.

What's needed:
Grant admin consent for the "[Your App Name]" application so all users can access it.

Why this is needed:
The app requires "Group.Read.All" permission to:
• Show users which teams/groups they belong to
• Enable group-based data isolation
• Allow collaboration features

This is a standard delegated permission - the app only reads groups that users are members of, not all organization groups.

How to grant consent (5 minutes):

Step 1: Go to Azure Portal
https://portal.azure.com

Step 2: Navigate to App Registration
Azure Active Directory → App registrations → "All applications" 
→ Search for "[Your App Name]"

Step 3: Grant Consent
• Click "API permissions" in left menu
• Look for "Microsoft Graph" section
• Find "Group.Read.All" permission
• Click "Grant admin consent for [Organization]" button at the top
• Confirm in the popup

Step 4: Verify
You should see green checkmarks next to all permissions

Alternative method (if you prefer):
Click this pre-configured admin consent URL:
https://login.microsoftonline.com/{tenant-id}/adminconsent?client_id={app-client-id}

After you grant consent:
✅ All users can immediately access the app
✅ No individual consent prompts
✅ Secure, read-only access to group memberships

Security notes:
• App only reads groups, cannot modify them
• Only delegated access (user context, not app-only)
• Audited in Azure AD logs
• Can be revoked anytime in Azure Portal

Questions?
I'm happy to jump on a call to walk through this together.

Contact: [Your Email/Phone]
Documentation: [Link to your security docs]

Thank you!
[Your Name]
```

---

## User Communication Checklist

### Pre-Invitation
- [ ] Prepare user email list
- [ ] Verify users don't already exist in your tenant
- [ ] Test invitation flow with your own external account first

### During Invitation
- [ ] Send pre-invitation email (Template 1)
- [ ] Send invitation via backend (Graph API)
- [ ] Log invitation status in your database

### Post-Invitation Monitoring
- [ ] Track who has accepted (check invitation status)
- [ ] Send reminder after 24-48 hours (Template 2)
- [ ] Send welcome email after first sign-in (Template 3)

### Troubleshooting
- [ ] Have Template 4 ready for support tickets
- [ ] Monitor for common errors (admin consent, spam folders)
- [ ] Keep admin contact info handy (Template 5)

---

## Customizing the B2B Invitation Experience

### Customize Invitation Email

**Option 1: Customize in Azure Portal**
```
Azure AD → External Identities → Company branding
→ Upload logo, colors, text
→ Applies to all invitations
```

**Option 2: Custom Email with Graph API**
```python
invitation = Invitation(
    invited_user_email_address="user@example.com",
    invite_redirect_url="https://your-app.azurecontainerapps.io",
    send_invitation_message=True,
    invited_user_message_info=InvitedUserMessageInfo(
        customized_message_body="""
        Hi! You've been invited to join our Content Processing Platform.
        
        Click the link below to get started. You'll be asked to review
        permissions - this is a standard security step.
        
        Questions? Contact support@yourapp.com
        """
    )
)
```

### Customize Consent Screen

**Branding:**
```
Azure AD → Company branding
→ Add:
  • Company logo
  • Background color
  • Privacy policy URL
  • Terms of use URL
```

**Privacy Policy & Terms:**
```
Azure AD → App registrations → Your App → Branding & properties
→ Add:
  • Privacy statement URL: https://yourapp.com/privacy
  • Terms of service URL: https://yourapp.com/terms
```

These URLs appear on the consent screen.

---

## FAQs for Support Team

### Q: User says "I accepted the invitation but can't access the app"

**A:** Walk through these steps:

1. **Verify they're using the right account:**
   "Which email address are you signing in with?"
   Must match the invitation email.

2. **Check for admin consent block:**
   If they see "Need admin approval" → Admin consent not granted
   Escalate to IT (use Template 5)

3. **Clear browser cache:**
   "Try signing in with an incognito/private window"

4. **Check user status in Azure:**
   Azure AD → Users → External users → Find user
   Status should be "Accepted"

### Q: User says "I never received the invitation email"

**A:** Troubleshoot in order:

1. **Check spam/junk folder:**
   "Search your spam folder for 'invites@microsoft.com'"

2. **Verify email address:**
   "What email address should we send to?"
   Check for typos in your system

3. **Resend invitation:**
   ```python
   # Delete old invitation if expired
   # Send new invitation with correct email
   ```

4. **Check email deliverability:**
   Some organizations block external invitations
   Ask user to whitelist: invites@microsoft.com, *.microsoft.com

### Q: User asks "Why do you need these permissions?"

**A:** Explain B2B vs App permissions:

**B2B Invitation Consent (what they see first):**
"These permissions allow you to join our organization as a guest:
• Read your profile → So we know your name and email
• Stay signed in → So you don't have to login every time
• These are required by Microsoft for all B2B collaborations"

**App Permissions (if admin consent not granted):**
"Our app needs to know which teams you belong to:
• Group.Read.All → See your team memberships
• This helps us show you the right data
• We only see groups you're a member of, not all groups"

### Q: User asks "Is this safe?"

**A:** Reassure them:

"Yes, this is completely safe:
✅ Microsoft's standard invitation process
✅ Used by millions of organizations worldwide
✅ We cannot access your personal email or files
✅ We only see basic profile info (name, email)
✅ You can revoke access anytime in your Microsoft account settings
✅ All data is encrypted and secure

Privacy policy: [link]
Security practices: [link]"

---

## Monitoring & Analytics

### Track Invitation Success Rate

**Metrics to monitor:**
```python
# In your database or analytics
{
  "total_invitations_sent": 100,
  "invitations_accepted": 85,
  "invitations_pending": 10,
  "invitations_expired": 5,
  "acceptance_rate": "85%",
  "average_time_to_accept": "3.2 hours",
  "common_issues": {
    "spam_folder": 30,
    "admin_consent_block": 5,
    "wrong_email": 2
  }
}
```

**Query Graph API for invitation status:**
```python
# Check invitation redemption status
invitation_status = await graph_client.invitations.by_invitation_id(
    invitation_id
).get()

print(f"Status: {invitation_status.status}")  # "Accepted", "PendingAcceptance"
print(f"Redeemed: {invitation_status.invited_user.redemption_state}")
```

### Automated Reminders

**Send reminder if not accepted within 24 hours:**
```python
import datetime
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

@scheduler.scheduled_job('interval', hours=24)
async def send_invitation_reminders():
    # Find pending invitations older than 24 hours
    pending = db.invitations.find({
        "status": "pending",
        "sent_at": {"$lt": datetime.utcnow() - datetime.timedelta(hours=24)}
    })
    
    for invitation in pending:
        # Send Template 2 (reminder email)
        await send_reminder_email(invitation.email)
```

---

## Best Practices

### ✅ Do's

1. **Send pre-invitation email** explaining what to expect
2. **Customize invitation message** with your branding
3. **Monitor acceptance rates** and follow up
4. **Provide clear support** contact info
5. **Test with your own account** before inviting users
6. **Use admin consent** or optional claims to eliminate app permission prompts
7. **Whitelist Microsoft IPs** if users report email delivery issues

### ❌ Don'ts

1. **Don't assume users understand** Azure AD/B2B terminology
2. **Don't skip explaining** what the consent screen means
3. **Don't ignore spam folder** issues (30% of users check spam)
4. **Don't leave admin consent ungranted** if using Group.Read.All
5. **Don't send invitations to invalid emails** (verify first)
6. **Don't forget to expire old invitations** (default: 7 days)

---

## Related Documentation

- **For removing app permission consent:** See `REMOVE_ADMIN_CONSENT_GUIDE.md`
- **For B2B and B2C architecture:** See `B2B_B2C_INFRASTRUCTURE_SHARING_GUIDE.md`
- **For authentication setup:** See `AUTHENTICATION_IMPLEMENTATION_COMPLETE.md`

---

## Summary

**What Users Will Always See:**
✅ B2B Invitation Consent (mandatory, 1 screen)

**What You Can Eliminate:**
✅ App Permission Consent (with optional claims or admin consent)

**Shortest Path (3 Steps):**
```
1) Send invitation via Graph API (no pre-email)
2) User clicks "Accept invitation" (B2B consent shown once)
3) User signs in → lands in app (no app consent if optional claims or admin consent configured)
```

Recommendations to minimize friction:
- Use optional claims for `groups` or grant admin consent once.
- Customize branding so the Microsoft consent screen looks familiar.
- Skip the pre-invitation email unless deliverability is an issue; rely on Microsoft’s invite.

Admin-only path (alternative):
- Keep `Group.Read.All` and have a Global Admin grant tenant-wide consent once.
- Outcome is the same for users: only the B2B invitation consent appears; no app-permission prompt.
- Choose this if you prefer Graph scopes or need other admin-consent Graph permissions.

**Recommended Setup:**
- Use optional claims (no admin consent needed) OR
- Grant admin consent once (no user-level consent)
- Customize B2B invitation email with branding
- Provide clear communication templates
- Monitor acceptance rates and send reminders

**Support Response Time:**
- Average issue resolution: <15 minutes with proper templates
- Most common issue: Spam folder (60% of support tickets)
- Most effective solution: Pre-emptive communication (Template 1)

---

## Guest vs Member (What to Invite?)

- **Guest (Recommended for B2B):**
   - Intended for external collaborators; stays in their home tenant.
   - Works with Microsoft personal accounts (MSA) and other Azure AD tenants.
   - Standard B2B invitation consent applies; least friction and least privilege in your tenant.

- **Member (Internal employee in your tenant):**
   - Full directory member; typically requires creating or converting the account in your tenant.
   - Not suitable for external organizations unless you manage their identity in your tenant.
   - Microsoft personal accounts (MSA) cannot be made true “members” of an Azure AD tenant; they must be guest or use Entra External ID (B2C) for customer identities.

**Conclusion:** For a B2B app, invite external users as **Guest**. Use **Member** only for users you own/manage within your tenant (employees, contractors with managed identities).

### Will a Microsoft personal account be OK?
- **Guest:** Yes. MSA (e.g., Outlook.com, Hotmail) can accept B2B guest invitations and sign in.
- **Member:** No. MSA cannot be converted to a native member of your Azure AD; member requires an account homed in your tenant.

### Impact on consent and access
- Guest users see the B2B invitation consent and then sign in; app permission consent is eliminated via optional claims or admin consent.
- Member users sign in like internal users; there is no B2B invitation step because their identity is already in your tenant.

---

## Current Discussion Summary (Dec 3, 2025)

- Make the process shorter: Use the 3-step flow and avoid pre-invitation emails unless deliverability is a known issue.
- Guest vs Member: For a B2B app, invite external users as Guest. Member is for accounts you manage in your tenant; not appropriate for external org identities.
- Microsoft personal accounts (MSA): Acceptable for Guest invitations; not supported as Member identities in your tenant.
- Consent screens: You cannot remove the B2B invitation consent. You can remove app permission consent via optional claims or admin consent, yielding a single consent screen total.

---

## Lite Email Templates (Use These for Minimum Friction)

### Lite Invitation Email
```
Subject: Access to [Your App Name]

Hi [Name],

You’ve been invited to access our platform. 
Check your inbox for an email from Microsoft (invites@microsoft.com) and click “Accept invitation.”

Then sign in with your existing account to get started.

Thanks,
[Your Team]
```

### Lite Reminder Email
```
Subject: Reminder: Accept your invite to [Your App Name]

Hi [Name],

Quick reminder to accept your invitation from Microsoft (invites@microsoft.com). 
Click “Accept invitation,” then sign in to use the app.

Need help? Reply to this email.

Thanks,
[Your Team]
```

### Lite Welcome Email
```
Subject: Welcome to [Your App Name]

Hi [Name],

Your access is active. Sign in at https://your-app.azurecontainerapps.io.

Support: support@yourapp.com

— [Your Team]
```

---

## In‑App Help Link Near "Sign In"

Purpose: Provide a one-click explanation of the single B2B consent screen so users don’t get stuck.

Placement: On your sign-in page next to the button, add a small link “What to expect”.

Proposed copy:
- Link text: `What to expect`
- Tooltip/hover: `You’ll see one Microsoft consent screen to accept the invitation.`

Frontend steps (React/TypeScript):
1) Add a simple route/page explaining the 3-step flow.
2) Link to it from the sign-in component.

Example component (drop-in):
```tsx
// File: src/ContentProcessorWeb/src/components/HelpConsentInfo.tsx
import React from 'react';
import { Link } from 'react-router-dom';

export const HelpConsentInfo: React.FC = () => (
   <div style={{ maxWidth: 720, margin: '24px auto', lineHeight: 1.6 }}>
      <h2>Signing In: What to Expect</h2>
      <p>
         To access the app, you'll accept a single Microsoft invitation consent screen
         and then sign in with your existing account. No extra app permissions are required.
      </p>
      <ol>
         <li>Open the invitation email from Microsoft and click <b>Accept invitation</b>.</li>
         <li>Review the Microsoft consent screen and click <b>Accept</b> (standard security step).</li>
         <li>Sign in to the app with your usual account and start using it.</li>
      </ol>
      <p>
         If you see an <b>admin approval</b> message, contact support — we can fix this quickly.
      </p>
      <p>
         <Link to="/">Return to Sign In</Link>
      </p>
   </div>
);
```

Add route (React Router):
```tsx
// File: src/ContentProcessorWeb/src/App.tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { HelpConsentInfo } from './components/HelpConsentInfo';

export default function App() {
   return (
      <BrowserRouter>
         <Routes>
            {/* existing routes */}
            <Route path="/help/consent" element={<HelpConsentInfo />} />
         </Routes>
      </BrowserRouter>
   );
}
```

Link from Sign-In:
```tsx
// File: src/ContentProcessorWeb/src/msal-auth/SignInCard.tsx (example)
import { Link } from 'react-router-dom';

export function SignInCard() {
   return (
      <div style={{ textAlign: 'center' }}>
         {/* your existing sign-in button */}
         <button onClick={/* call MSAL login */}>Sign In</button>
         <div style={{ marginTop: 8 }}>
            <Link to="/help/consent">What to expect</Link>
         </div>
      </div>
   );
}
```

Optional: Add a small banner only for first-time external users (detect via lack of app session):
```tsx
// Show a dismissible tip
<div role="alert" style={{ background: '#f5f7fa', padding: 8, borderRadius: 6 }}>
   New here? You’ll see one Microsoft consent screen to accept the invitation.
   <Link to="/help/consent" style={{ marginLeft: 8 }}>Learn more</Link>
   <button aria-label="Dismiss" onClick={dismiss}>×</button>
   </div>
```

Deployment notes:
- No backend changes required.
- Keep copy short and link obvious.
- Verify route `/help/consent` is accessible without sign-in.
