import os
import json
import re
from datetime import datetime, timedelta
import streamlit as st
from google import genai
from google.genai import types
import resend

DATA_FILE = "bes_trauma_master_archive.json"
CONFIG_FILE = "bes_config.json"
AUDIT_LOG_FILE = "bes_dispatch_audit.json"
SUBSCRIBERS_FILE = "bes_subscribers.json"

st.set_page_config(
    page_title="BES - Behavioral & Emotional Summarizer",
    page_icon="🧠",
    layout="wide",
)

# --- Persistent Configurations ---
def load_json(filepath, default_val):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_val
    return default_val

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def log_dispatch_event(event_type, recipients, status, details=""):
    audit_logs = load_json(AUDIT_LOG_FILE, [])
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": event_type,
        "recipients": recipients,
        "status": status,
        "details": details
    }
    audit_logs.insert(0, entry)
    save_json(AUDIT_LOG_FILE, audit_logs[:100])

# Load master system state
config_data = load_json(CONFIG_FILE, {})
gemini_api_key = config_data.get("gemini_api_key", "")
resend_api_key = config_data.get("resend_api_key", "")
admin_default_email = config_data.get("admin_email", "")
master_admin_pin = config_data.get("admin_pin", "admin123")

if "history" not in st.session_state:
    st.session_state.history = load_json(DATA_FILE, [])

if "is_admin_authenticated" not in st.session_state:
    st.session_state.is_admin_authenticated = False

# --- DEVICE DETECTION LOGIC ---
# Determines if the user is browsing from your local host machine or via your private key token
query_params = st.query_params
is_admin_device = False

# Check if accessing locally or passing private admin key
if query_params.get("device_key") == "admin_master_access" or os.environ.get("STREAMLIT_SERVER_ADDRESS") in ["localhost", "127.0.0.1", None]:
    is_admin_device = True

# --- Email Parsing & Dispatch ---
def parse_and_validate_emails(email_string):
    raw_list = re.split(r"[,;\s]+", email_string.strip())
    valid_emails = [e for e in raw_list if re.match(r"[^@]+@[^@]+\.[^@]+", e)]
    return list(set(valid_emails))

def dispatch_diagnostic_email(report_text, entry_date, category_label, target_emails, is_morning_digest=False):
    try:
        resend.api_key = resend_api_key.strip()
        title_prefix = "🌅 BES 06:00 AM Daily Briefing" if is_morning_digest else "🧠 BES Real-Time Trauma Report"
        
        html_content = (
            f"<div style='font-family: Arial, sans-serif; background-color: #f8fafc; padding: 25px; border-radius: 10px; border: 1px solid #e2e8f0;'>"
            f"<h2 style='color: #1e293b; margin-bottom: 4px;'>{title_prefix}</h2>"
            f"<p style='color: #64748b; font-size: 14px;'><strong>Date:</strong> {entry_date} | <strong>Classification:</strong> {category_label}</p>"
            f"<hr style='border: 0; border-top: 1px solid #cbd5e1; margin: 15px 0;' />"
            f"<pre style='font-family: inherit; white-space: pre-wrap; font-size: 14px; line-height: 1.6; color: #0f172a;'>"
            f"{report_text}"
            f"</pre>"
            f"<hr style='border: 0; border-top: 1px solid #cbd5e1; margin: 15px 0;' />"
            f"<p style='font-size: 11px; color: #94a3b8;'>Generated via BES trauma-informed intelligence. Dispatched upon authorized user request with verified consent.</p>"
            f"</div>"
        )
        
        params = {
            "from": "BES Diagnostic <onboarding@resend.dev>",
            "to": target_emails,
            "subject": f"{title_prefix}: {category_label} ({entry_date})",
            "html": html_content,
        }
        response = resend.Emails.send(params)
        log_dispatch_event("User-Requested Dispatch" if not is_morning_digest else "06:00 AM Automated Schedule", target_emails, "Success", f"Email ID: {response.get('id')}")
        return True, response.get("id")
    except Exception as e:
        log_dispatch_event("User-Requested Dispatch" if not is_morning_digest else "06:00 AM Automated Schedule", target_emails, "Failed", str(e))
        return False, str(e)

# --- Prompts ---
TRAUMA_EMOTION_DIAGNOSTIC_PROMPT = """
You are BES (Behavioral, Emotional & Somatic Summarizer), an advanced clinical-grade trauma-informed intelligence system.

Synthesize all raw emotions, somatic cues, triggers, and reactions against prior archives.

Format strictly as:
### 🩺 1. Emotional Spectrum & Trauma Triage
- **Autonomous Core Classification:** [Classification Name]
- **Nervous System State (Polyvagal):** [Ventral Vagal / Sympathetic / Dorsal Vagal / Fawn]
- **Emotional Battery:** [X/10] | **Stress / Emotional Pain:** [X/10]
- **Primary & Suppressed Emotions:** [Primary vs Root Wound]

### ⚡ 2. Trigger Anatomy & Somatic Feedback Loop
- **The Psychological / Trauma Hook:** [Core wound or cognitive trap triggered]
- **Somatic Physical Resonance:** [Bodily sensations]
- **Observed Coping Response:** [Exact behavior chosen or avoided]
- **Coping Archetype:** [Dissociative / Avoidant / Reactive / Compensatory / Adaptive]

### 📊 3. Compounded Trauma Debt & 24-48h Forecast
- **Cumulative Baseline Compounding:** [Roll-over stress impact]
- **Next 24-48 Hour Vulnerability Alert:** [Anticipated risks tomorrow]

### 🛡️ 4. BES Trauma-Informed Reset Protocol (Rx)
- **Immediate Somatic / Grounding Action:** [One concrete somatic or behavioral reset action]
"""

# --- Settings & Hub Modal (Device-Gated) ---
@st.dialog("⚙️ Settings & Service Hub", width="large")
def settings_modal():
    if not is_admin_device:
        # === PUBLIC / OTHER DEVICES VIEW (NO ADMIN PORTAL AT ALL) ===
        t_about, t_sub = st.tabs([
            "ℹ️ About BES", 
            "🌅 06:00 AM Daily Briefing Sign-Up"
        ])
        
        with t_about:
            st.subheader("About BES Intelligence")
            st.markdown("""
            **BES (Behavioral, Emotional & Somatic Summarizer)** is a trauma-informed clinical AI triage system designed to decode emotional and physiological states in real-time.
            
            **What BES Analyzes:**
            * **Polyvagal State:** Identifies Ventral Vagal (Calm), Sympathetic (Fight/Flight), and Dorsal Vagal (Freeze/Numb) states.
            * **Somatic Resonance:** Correlates physical tension patterns (chest, jaw, gut) with emotional core wounds.
            * **Actionable Somatic Resets (Rx):** Delivers grounded physical micro-interventions to bring the nervous system back to baseline.
            """)

        with t_sub:
            st.subheader("Subscribe to 06:00 AM Daily Morning Briefings")
            st.write("Receive automated, compounded nervous system summaries and morning somatic grounding directives every day at 06:00 AM.")
            
            pub_email = st.text_input("Your Email Address:", placeholder="name@example.com")
            pub_consent = st.checkbox(
                "✅ I provide explicit, informed consent for BES to store my email and automatically send daily 06:00 AM somatic diagnostic reports."
            )
            
            if st.button("Subscribe to 06:00 AM Digest", type="primary"):
                valid = parse_and_validate_emails(pub_email)
                if not valid:
                    st.error("Please enter a valid email address.")
                elif not pub_consent:
                    st.warning("You must check the consent agreement to subscribe.")
                else:
                    current_subs = load_json(SUBSCRIBERS_FILE, [])
                    if valid[0] in current_subs:
                        st.info("This email is already subscribed to the 06:00 AM digest.")
                    else:
                        current_subs.append(valid[0])
                        save_json(SUBSCRIBERS_FILE, current_subs)
                        log_dispatch_event("Public Subscription", valid, "Success", "User opted-in with explicit consent.")
                        st.success("🎉 You are now subscribed! You will receive daily summaries at 06:00 AM.")

    else:
        # === YOUR DEVICE ONLY (ADMIN ACCESS AVAILABLE) ===
        if not st.session_state.is_admin_authenticated:
            t_about, t_sub, t_login = st.tabs([
                "ℹ️ About BES", 
                "🌅 06:00 AM Daily Briefing Sign-Up", 
                "🔐 Master Device Unlock"
            ])
            with t_about:
                st.subheader("About BES Intelligence")
                st.markdown("Clinical-grade trauma analysis and autonomous daily dispatch system.")
            with t_sub:
                st.subheader("06:00 AM Digest Subscription")
                p_email = st.text_input("Email:", placeholder="name@example.com")
                p_c = st.checkbox("Consent to daily reports")
                if st.button("Subscribe"):
                    v = parse_and_validate_emails(p_email)
                    if v and p_c:
                        subs = load_json(SUBSCRIBERS_FILE, [])
                        subs.append(v[0])
                        save_json(SUBSCRIBERS_FILE, list(set(subs)))
                        st.success("Subscribed!")
            with t_login:
                st.subheader("🔐 Master Device PIN Login")
                pin_entry = st.text_input("Enter Admin PIN:", type="password", key="modal_pin")
                if st.button("Unlock Admin Mode", use_container_width=True):
                    if pin_entry.strip() == master_admin_pin:
                        st.session_state.is_admin_authenticated = True
                        st.rerun()
                    else:
                        st.error("Invalid PIN.")
        else:
            # === FULL ADMIN HUB (AUTHORIZED) ===
            t_req, t_subs_admin, t_admin_cfg = st.tabs([
                "📋 Dispatch Request Logs", 
                "👥 06:00 AM Subscribers List", 
                "⚙️ Master Configuration"
            ])
            
            with t_req:
                st.subheader("Global Dispatch Audit Trail")
                audit_logs = load_json(AUDIT_LOG_FILE, [])
                if not audit_logs:
                    st.info("No dispatch events logged yet.")
                else:
                    for item in audit_logs:
                        badge = "🟢 SUCCESS" if item.get("status") == "Success" else "🔴 FAILED"
                        with st.expander(f"{badge} | {item.get('timestamp')} — {item.get('type')}"):
                            st.write(f"**Recipients:** `{', '.join(item.get('recipients', []))}`")
                            st.write(f"**Details / Status:** {item.get('details')}")

            with t_subs_admin:
                st.subheader("06:00 AM Morning Subscribers Management")
                current_subscribers = load_json(SUBSCRIBERS_FILE, [admin_default_email] if admin_default_email else [])
                
                col_add_sub, col_add_btn = st.columns([3, 1])
                with col_add_sub:
                    manual_sub = st.text_input("Add Email:", placeholder="user@clinic.org", label_visibility="collapsed")
                with col_add_btn:
                    if st.button("➕ Add"):
                        valid = parse_and_validate_emails(manual_sub)
                        if valid:
                            updated_subs = list(set(current_subscribers + valid))
                            save_json(SUBSCRIBERS_FILE, updated_subs)
                            st.success(f"Added {valid[0]}")
                            st.rerun()
                        else:
                            st.error("Invalid email.")
                            
                st.markdown(f"**Total Registered Subscribers:** `{len(current_subscribers)}`")
                for s in current_subscribers:
                    col_s1, col_s2 = st.columns([4, 1])
                    col_s1.code(s)
                    if col_s2.button("Remove", key=f"del_{s}"):
                        updated_subs = [x for x in current_subscribers if x != s]
                        save_json(SUBSCRIBERS_FILE, updated_subs)
                        st.rerun()

            with t_admin_cfg:
                st.subheader("System Credentials & Security")
                up_g = st.text_input("Gemini API Key:", value=gemini_api_key, type="password")
                up_r = st.text_input("Resend API Key:", value=resend_api_key, type="password")
                up_e = st.text_input("Default Admin Email:", value=admin_default_email)
                up_p = st.text_input("Admin PIN:", value=master_admin_pin, type="password")
                
                col_save, col_lock = st.columns([1, 1])
                with col_save:
                    if st.button("Save System Updates", type="primary", use_container_width=True):
                        cfg = {
                            "gemini_api_key": up_g.strip(),
                            "resend_api_key": up_r.strip(),
                            "admin_email": up_e.strip(),
                            "admin_pin": up_p.strip()
                        }
                        save_json(CONFIG_FILE, cfg)
                        st.success("Settings updated!")
                        st.rerun()
                with col_lock:
                    if st.button("🔒 Lock Admin Console", use_container_width=True):
                        st.session_state.is_admin_authenticated = False
                        st.rerun()

# --- Top Navigation Bar ---
col_head, col_gear = st.columns([9, 1])
with col_head:
    st.title("🧠 BES Intelligence Platform")
    st.caption("Behavioral, Emotional & Somatic Real-Time Diagnostic Engine")
with col_gear:
    st.write("")
    if st.button("⚙️ Settings", use_container_width=True):
        settings_modal()

st.markdown("---")

# --- Main Workspace Tabs ---
tab_log, tab_archive = st.tabs([
    "📝 1. Live Feed & Diagnostic Engine",
    "🗂️ 2. Master Archive"
])

# --- Tab 1: Live Feed & Analysis ---
with tab_log:
    col_d, col_stress = st.columns([1, 2])
    with col_d:
        log_date = st.date_input("Date", value=datetime.today())
    with col_stress:
        stress_level = st.select_slider(
            "Current Emotional Strain / Pain Level (1–10):",
            options=[
                "1/10 - Grounded / Safe & Calm",
                "2/10 - Minimal Discomfort",
                "3/10 - Mild Agitation / Sensitivity",
                "4/10 - Noticeable Friction / Self-Doubt",
                "5/10 - Moderate Strain / Anxiety",
                "6/10 - Heightened Emotional Pressure",
                "7/10 - High Stress / Trigger Activation",
                "8/10 - Heavy Strain / Freeze / Shame Loop",
                "9/10 - Severe Dysregulation / Breakdown",
                "10/10 - Acute Trauma Flashback / Crisis"
            ],
            value="5/10 - Moderate Strain / Anxiety"
        )
    
    user_feed = st.text_area(
        "Describe your experience, bodily sensations, acute clips/triggers, or reactions:",
        height=140,
        placeholder="Type raw notes, physical tension patterns, video clips, or emotional events..."
    )
    
    # On-Demand Email Dispatch with Consent
    with st.expander("📬 On-Demand Email Dispatch (Optional)", expanded=False):
        send_email_checkbox = st.checkbox("Dispatch a copy of this diagnostic analysis via email", value=False)
        target_email_input = st.text_input(
            "Recipient Email(s) — (Separate multiple addresses with commas):",
            placeholder="e.g. user@example.com, therapist@clinic.org"
        )
        consent_checkbox = st.checkbox(
            "✅ I explicitly consent to receiving this clinical-grade somatic diagnostic report at the email address(es) provided above."
        )

    if st.button("Analyze Emotion & Trauma State", type="primary"):
        if not gemini_api_key or not resend_api_key:
            st.error("System credentials are not configured. Please initialize on the master device.")
        elif not user_feed.strip():
            st.warning("Please provide your experience or notes before analyzing.")
        elif send_email_checkbox and not target_email_input.strip():
            st.warning("You selected email dispatch. Please enter at least one recipient email address.")
        elif send_email_checkbox and not consent_checkbox:
            st.warning("Please check the consent box to authorize sending the email report.")
        else:
            with st.spinner("Synthesizing polyvagal dynamics, somatic resonance, and baseline compounding..."):
                try:
                    client = genai.Client(api_key=gemini_api_key.strip())
                    
                    past_context = "### PRIOR HISTORICAL BASELINE & TRAUMA ARCHIVE:\n"
                    if st.session_state.history:
                        for entry in reversed(st.session_state.history[:15]):
                            past_context += f"- [{entry.get('date')} | {entry.get('trauma_category', 'Log')} | Strain: {entry.get('stress_level')}]: {entry.get('feed')}\n"
                    else:
                        past_context += "No prior logs recorded.\n"
                    
                    payload = (
                        f"{past_context}\n"
                        f"### NEW RAW EMOTIONAL / TRAUMA LOG ({log_date.strftime('%Y-%m-%d')}):\n"
                        f"Self-Reported Emotional Strain: {stress_level}\n"
                        f"Raw Experience & Sensations:\n{user_feed}"
                    )
                    
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=payload,
                        config=types.GenerateContentConfig(
                            system_instruction=TRAUMA_EMOTION_DIAGNOSTIC_PROMPT,
                            temperature=0.3
                        )
                    )
                    
                    category_label = "Deep Emotional State"
                    if "**Autonomous Core Classification:**" in response.text:
                        try:
                            category_label = response.text.split("**Autonomous Core Classification:**")[1].split("\n")[0].strip()
                        except Exception:
                            category_label = "Deep Emotional State"
                    
                    # Save to local archive
                    new_entry = {
                        "date": log_date.strftime("%Y-%m-%d"),
                        "timestamp": datetime.now().isoformat(),
                        "trauma_category": category_label,
                        "stress_level": stress_level,
                        "feed": user_feed,
                        "report": response.text
                    }
                    st.session_state.history.insert(0, new_entry)
                    save_json(DATA_FILE, st.session_state.history)
                    
                    st.success(f"Analysis complete! State classified as: **'{category_label}'**")
                    
                    # On-Demand Dispatch if requested
                    if send_email_checkbox and consent_checkbox:
                        valid_recipients = parse_and_validate_emails(target_email_input)
                        if valid_recipients:
                            with st.spinner("Dispatching reports via Resend API..."):
                                success, msg = dispatch_diagnostic_email(
                                    response.text,
                                    log_date.strftime("%Y-%m-%d"),
                                    category_label,
                                    valid_recipients,
                                    is_morning_digest=False
                                )
                                if success:
                                    st.info(f"📧 Report delivered to: **{', '.join(valid_recipients)}**")
                                else:
                                    st.error(f"Dispatch failed: {msg}")
                        else:
                            st.error("No valid email addresses provided.")
                            
                    st.markdown("---")
                    st.markdown(response.text)
                    
                except Exception as e:
                    st.error(f"Error during analysis: {str(e)}")

# --- Tab 2: Master Archive (Admin Device Guarded) ---
with tab_archive:
    st.header("🗂️ Master Trauma & Emotional Archive")
    if not is_admin_device or not st.session_state.is_admin_authenticated:
        st.info("🔒 Historical Master Archive access is restricted to the administrator on the authorized master device.")
    else:
        if not st.session_state.history:
            st.info("No recorded logs in the master database yet.")
        else:
            for i, item in enumerate(st.session_state.history):
                e_date = item.get("date", f"Entry #{len(st.session_state.history) - i}")
                e_cat = item.get("trauma_category", "Emotional State")
                e_stress = item.get("stress_level", "Moderate")
                e_feed = item.get("feed", "No content")
                e_rep = item.get("report", "No report")
                
                with st.expander(f"📅 {e_date} | 🏷️ {e_cat} | Strain: {e_stress}"):
                    st.markdown("**Logged Raw Input:**")
                    st.info(e_feed)
                    st.markdown("**Diagnostic & Somatic Prescription:**")
                    st.markdown(e_rep)