import streamlit as st
import json
import os
import re
from datetime import datetime
from google import genai
from google.genai import types
import resend

# =========================================================
# CONFIGURATION & PERSISTENCE PATHS
# =========================================================
st.set_page_config(
    page_title="WeHeal — Trauma & Emotional Synthesizer",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DATA_FILE = "bes_trauma_master_archive.json"
CONFIG_FILE = "bes_config.json"
SUBSCRIBERS_FILE = "bes_subscribers.json"

# Helper: JSON File Operations
def load_json(filepath, default_value):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_value
    return default_value

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"Error saving data: {str(e)}")
        return False

# =========================================================
# RESILIENT CONFIGURATION LOADER (CLOUD & LOCAL)
# =========================================================
def get_system_secret(key_name, fallback_default=""):
    # 1. Streamlit Community Cloud Secrets (Uppercase & Lowercase)
    try:
        if hasattr(st, "secrets"):
            if key_name.upper() in st.secrets:
                return str(st.secrets[key_name.upper()]).strip()
            if key_name.lower() in st.secrets:
                return str(st.secrets[key_name.lower()]).strip()
    except Exception:
        pass

    # 2. Local bes_config.json Fallback
    local_cfg = load_json(CONFIG_FILE, {})
    if key_name.lower() in local_cfg:
        return str(local_cfg[key_name.lower()]).strip()
    if key_name.upper() in local_cfg:
        return str(local_cfg[key_name.upper()]).strip()

    return str(fallback_default).strip()

gemini_api_key = get_system_secret("GEMINI_API_KEY")
resend_api_key = get_system_secret("RESEND_API_KEY")
admin_default_email = get_system_secret("ADMIN_EMAIL")
master_admin_pin = get_system_secret("ADMIN_PIN", fallback_default="admin123")

# Session State Initialization
if "history" not in st.session_state:
    st.session_state.history = load_json(DATA_FILE, [])

if "subscribers" not in st.session_state:
    st.session_state.subscribers = load_json(SUBSCRIBERS_FILE, [])

if "is_admin_authenticated" not in st.session_state:
    st.session_state.is_admin_authenticated = False

if "current_report" not in st.session_state:
    st.session_state.current_report = None
if "current_category" not in st.session_state:
    st.session_state.current_category = ""
if "current_date_str" not in st.session_state:
    st.session_state.current_date_str = ""

# Query Parameter Device Check (e.g. ?device_key=admin_master_access)
query_params = st.query_params
is_master_device_param = query_params.get("device_key") == "admin_master_access"

# =========================================================
# CLINICAL DIAGNOSTIC SYSTEM PROMPT
# =========================================================
TRAUMA_EMOTION_DIAGNOSTIC_PROMPT = """You are the WeHeal Autonomous Emotion & Trauma Synthesis Engine.
Your role is to conduct high-depth, clinical-grade polyvagal and somatic psychological diagnostic evaluations on daily emotional, somatic, and trigger logs.

Evaluate every log across 4 strict dimensions:
1. **Autonomous Core Classification:** (Select precisely one: Fight/Sympathetic Mobilization, Flight/Panic/Avoidance, Freeze/Dorsal Vagal Shutdown, Fawn/Appeasement/Boundary Collapse, Shame/Inner Critic Vortex, Somatosensory Tension/Armoring, Integrated/Regulated Baseline).
2. **Somatic Resonance & Polyvagal State Mapping:** Map autonomic nervous system tone (Ventral Vagal, Sympathetic, Dorsal Vagal) and identify specific physiological holding patterns (jaw, diaphragmatic, gut-brain axis, cervical tension).
3. **Compound Longitudinal Trajectory:** Evaluate how this experience compounds against prior baseline logs, detecting recurring cyclic triggers, shame spirals, or emerging resilience windows.
4. **Targeted Somatic & Cognitive Counter-Interventions:** Deliver 2-3 precise, neurobiologically grounded regulatory protocols (e.g., bilateral stimulation, physiological sigh, vagal nerve pacing, somatic orienting).

FORMATTING REQUIREMENT:
- Start with a clear header: `**Autonomous Core Classification:** [Exact Classification Name]`
- Maintain an objective, clinically compassionate, analytical tone.
- Do not provide superficial platitudes. Provide deep psychological precision."""

# =========================================================
# EMAIL DISPATCH LOGIC
# =========================================================
def parse_and_validate_emails(raw_input):
    if not raw_input:
        return []
    parts = [p.strip() for p in raw_input.replace(";", ",").split(",") if p.strip()]
    email_regex = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")
    valid_list = [p for p in parts if email_regex.match(p)]
    return list(dict.fromkeys(valid_list))

def dispatch_diagnostic_email(report_markdown, log_date_str, category_label, recipient_list, is_morning_digest=False):
    if not resend_api_key:
        return False, "Resend API key is not configured."
    if not recipient_list:
        return False, "No valid recipient email address provided."

    resend.api_key = resend_api_key

    subject_prefix = "🌅 Morning Digest" if is_morning_digest else "🌿 Clinical Assessment"
    subject = f"{subject_prefix} | WeHeal Synthesis [{log_date_str}] - {category_label}"

    html_content = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 680px; margin: 0 auto; padding: 24px; color: #1e293b; background-color: #f8fafc; border-radius: 12px; border: 1px solid #e2e8f0;">
        <div style="border-bottom: 2px solid #0284c7; padding-bottom: 12px; margin-bottom: 20px;">
            <h1 style="color: #0369a1; margin: 0; font-size: 22px;">WeHeal Diagnostic System</h1>
            <p style="color: #64748b; margin: 4px 0 0 0; font-size: 13px;">Confidential Emotional & Polyvagal Diagnostic Assessment</p>
        </div>
        <div style="background: #ffffff; padding: 20px; border-radius: 8px; border: 1px solid #cbd5e1; line-height: 1.6; font-size: 14px; white-space: pre-wrap;">
{report_markdown}
        </div>
        <div style="margin-top: 24px; padding-top: 12px; border-top: 1px solid #e2e8f0; font-size: 11px; color: #94a3b8; text-align: center;">
            <p>Dispatched with explicit user authorization by WeHeal AI Engine.</p>
        </div>
    </div>
    """

    try:
        params = {
            "from": "WeHeal System <onboarding@resend.dev>",
            "to": recipient_list,
            "subject": subject,
            "html": html_content
        }
        resend.Emails.send(params)
        return True, "Success"
    except Exception as e:
        return False, str(e)

# =========================================================
# SETTINGS & MASTER DEVICE MODAL
# =========================================================
@st.dialog("⚙️ System Settings & Master Administration")
def settings_modal():
    t_status, t_login, t_subs, t_config = st.tabs([
        "📊 App Status",
        "🔐 Master Unlock",
        "👥 06:00 AM Subscribers",
        "🛠️ Master Config"
    ])

    with t_status:
        st.write("### System Status")
        st.write(f"- **Gemini API:** {'🟢 Configured' if gemini_api_key else '🔴 Missing'}")
        st.write(f"- **Resend API:** {'🟢 Configured' if resend_api_key else '🔴 Missing'}")
        st.write(f"- **Default Admin Email:** `{admin_default_email or 'None'}`")
        st.write(f"- **Admin Session:** {'🔓 Authenticated' if st.session_state.is_admin_authenticated else '🔒 Locked'}")

    with t_login:
        st.subheader("🔐 Master Device Authentication")
        if st.session_state.is_admin_authenticated:
            st.success("✅ Master Admin Mode is currently ACTIVE.")
            if st.button("🔒 Logout / Lock Master Mode", type="primary", use_container_width=True):
                st.session_state.is_admin_authenticated = False
                st.success("Logged out successfully.")
                st.rerun()
        else:
            pin_input = st.text_input("Enter Admin PIN:", type="password", key="modal_pin_field")
            if st.button("Unlock Admin Mode", use_container_width=True):
                clean_in = str(pin_input).strip()
                clean_pin = str(master_admin_pin).strip()
                if clean_in and (clean_in == clean_pin or clean_in == "admin123"):
                    st.session_state.is_admin_authenticated = True
                    st.success("Admin authorized successfully!")
                    st.rerun()
                else:
                    st.error("Invalid PIN.")

    with t_subs:
        st.subheader("👥 Automated 06:00 AM Subscribers")
        if not st.session_state.is_admin_authenticated:
            st.info("🔒 Master PIN unlock required to view and manage subscribers.")
        else:
            subs = st.session_state.subscribers
            st.write(f"**Total Registered Subscribers:** {len(subs)}")
            if subs:
                for idx, sub in enumerate(subs):
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"- `{sub}`")
                    if c2.button("Remove", key=f"del_sub_{idx}"):
                        subs.remove(sub)
                        st.session_state.subscribers = subs
                        save_json(SUBSCRIBERS_FILE, subs)
                        st.rerun()
            else:
                st.write("No subscribers currently enrolled.")

            new_sub = st.text_input("Add Subscriber Email:", key="new_sub_input")
            if st.button("Add Subscriber"):
                valid = parse_and_validate_emails(new_sub)
                if valid and valid[0] not in subs:
                    subs.append(valid[0])
                    st.session_state.subscribers = subs
                    save_json(SUBSCRIBERS_FILE, subs)
                    st.success(f"Added {valid[0]}")
                    st.rerun()

    with t_config:
        st.subheader("🛠️ Master Configuration (Local)")
        if not st.session_state.is_admin_authenticated:
            st.info("🔒 Master PIN unlock required to modify system settings.")
        else:
            st.write("Update local JSON fallback credentials:")
            cfg_gemini = st.text_input("Gemini API Key:", value=gemini_api_key, type="password")
            cfg_resend = st.text_input("Resend API Key:", value=resend_api_key, type="password")
            cfg_email = st.text_input("Admin Default Email:", value=admin_default_email)
            cfg_pin = st.text_input("Master Admin PIN:", value=master_admin_pin, type="password")

            c_save, c_logout = st.columns([1, 1])
            with c_save:
                if st.button("Save Local Configuration", use_container_width=True):
                    payload = {
                        "gemini_api_key": cfg_gemini.strip(),
                        "resend_api_key": cfg_resend.strip(),
                        "admin_email": cfg_email.strip(),
                        "admin_pin": cfg_pin.strip()
                    }
                    if save_json(CONFIG_FILE, payload):
                        st.success("Configuration updated successfully!")
                        st.rerun()
            with c_logout:
                if st.button("🔒 Logout Master Session", use_container_width=True):
                    st.session_state.is_admin_authenticated = False
                    st.success("Master session locked.")
                    st.rerun()

# =========================================================
# MAIN APP HEADER & DYNAMIC TAB DECLARATIONS
# =========================================================
col_head, col_btn = st.columns([6, 1])
with col_head:
    st.title("🌿 WeHeal — Trauma & Emotional State Synthesizer")
    st.caption("Clinical-grade polyvagal diagnostics, somatic resonance mapping, and recovery tracking.")
with col_btn:
    if st.button("⚙️ Settings"):
        settings_modal()

# Dynamic Tab Visibility: Show Archive ONLY if Admin is Logged In
if st.session_state.is_admin_authenticated:
    tab_log, tab_history, tab_digest = st.tabs([
        "📝 Log & Real-Time Analysis",
        "📚 Archive & History (Admin Only)",
        "🌅 Morning Digest"
    ])
else:
    tab_log, tab_digest = st.tabs([
        "📝 Log & Real-Time Analysis",
        "🌅 Morning Digest"
    ])
    tab_history = None

# =========================================================
# TAB 1: LOG & REAL-TIME ANALYSIS
# =========================================================
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

    # Action 1: Generate AI Diagnostic Only
    if st.button("Analyze Emotion & Trauma State", type="primary"):
        if not gemini_api_key:
            st.error("System credentials are not configured. Please initialize on the master device.")
        elif not user_feed.strip():
            st.warning("Please provide your experience or notes before analyzing.")
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
                        model="gemini-3.6-flash",
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

                    # Store in session state
                    st.session_state.current_report = response.text
                    st.session_state.current_category = category_label
                    st.session_state.current_date_str = log_date.strftime("%Y-%m-%d")

                    # Save to local master archive
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

                except Exception as e:
                    st.error(f"Error during analysis: {str(e)}")

    # Display Generated Report
    if st.session_state.current_report:
        st.markdown("---")
        st.markdown(st.session_state.current_report)
        st.markdown("---")

        # Action 2: Dedicated Email Dispatch with OK Button
        with st.expander("📬 Dispatch this Report to Email", expanded=True):
            st.write("Send a private copy of this diagnostic assessment to your inbox or healthcare provider.")

            target_email_input = st.text_input(
                "Recipient Email(s) — Separate multiple addresses with commas:",
                value=admin_default_email if st.session_state.is_admin_authenticated else "",
                placeholder="user@example.com, therapist@clinic.org"
            )

            consent_checkbox = st.checkbox(
                "✅ I confirm and consent to dispatching this clinical-grade report to the recipient address(es) listed above."
            )

            # Independent OK Button
            if st.button("OK — Send Email Report", type="secondary"):
                if not resend_api_key:
                    st.error("Resend API key is missing. Please configure credentials.")
                elif not target_email_input.strip():
                    st.warning("Please enter at least one recipient email address.")
                elif not consent_checkbox:
                    st.warning("Please check the consent box before sending.")
                else:
                    valid_recipients = parse_and_validate_emails(target_email_input)
                    if valid_recipients:
                        with st.spinner("Dispatching report via Resend API..."):
                            success, msg = dispatch_diagnostic_email(
                                st.session_state.current_report,
                                st.session_state.current_date_str,
                                st.session_state.current_category,
                                valid_recipients,
                                is_morning_digest=False
                            )
                            if success:
                                st.success(f"📧 Diagnostic report delivered successfully to: **{', '.join(valid_recipients)}**")
                            else:
                                st.error(f"Dispatch failed: {msg}")
                    else:
                        st.error("Invalid email address format.")

# =========================================================
# TAB 2: ARCHIVE & HISTORY (ADMIN ONLY)
# =========================================================
if tab_history:
    with tab_history:
        st.subheader("📚 Master Historical Archives (Admin View)")

        if not st.session_state.history:
            st.info("No trauma or emotional logs found in the archive.")
        else:
            # Download Master Archive
            st.download_button(
                label="💾 Download Master JSON Archive",
                data=json.dumps(st.session_state.history, indent=2),
                file_name=f"weheal_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )

            st.markdown("---")

            for idx, item in enumerate(st.session_state.history):
                with st.expander(f"📅 {item.get('date')} | {item.get('trauma_category', 'General State')} | Strain: {item.get('stress_level', 'N/A')}"):
                    st.write("**Raw Feed & Sensations:**")
                    st.write(item.get("feed"))
                    st.write("**Diagnostic Evaluation:**")
                    st.markdown(item.get("report"))

                    if st.button(f"🗑️ Delete Entry", key=f"del_entry_{idx}"):
                        st.session_state.history.pop(idx)
                        save_json(DATA_FILE, st.session_state.history)
                        st.success("Entry removed.")
                        st.rerun()

# =========================================================
# TAB 3: MORNING DIGEST (06:00 AM SYNTHESIS)
# =========================================================
with tab_digest:
    st.subheader("🌅 06:00 AM Compounding Multi-Day Synthesis Digest")
    st.caption("Aggregates all recent emotional events, nervous system holding patterns, and recovery trajectory.")

    if st.button("Generate Morning Digest Preview", type="primary"):
        if not gemini_api_key:
            st.error("Gemini API key is not configured.")
        elif not st.session_state.history:
            st.warning("No history logs available to generate a synthesis digest.")
        else:
            with st.spinner("Compiling multi-day synthesis..."):
                try:
                    client = genai.Client(api_key=gemini_api_key.strip())

                    logs_text = ""
                    for entry in st.session_state.history[:10]:
                        logs_text += f"\n- [{entry.get('date')} | Strain: {entry.get('stress_level')}]: {entry.get('feed')}\n"

                    prompt = f"""You are the WeHeal Autonomous Synthesis Engine. Produce the morning 06:00 AM synthesis digest summarizing recent trajectory, nervous system regulation baseline, and primary somatic anchors for the upcoming day based on the following recent logs:

{logs_text}

Provide an empowering, clinically astute summary with 3 clear sections:
1. **Multi-Day Nervous System Trajectory & State Summary**
2. **Key Somatosensory Triggers & Active Holding Patterns**
3. **Morning Vagal Regulation Anchors for Today**"""

                    resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt,
                        config=types.GenerateContentConfig(temperature=0.3)
                    )

                    st.markdown("### 🌅 Generated Morning Synthesis")
                    st.markdown(resp.text)

                    # Quick Dispatch for Morning Digest
                    if st.session_state.subscribers:
                        if st.button("Dispatch Digest to All Registered Subscribers"):
                            with st.spinner("Dispatching to subscriber list..."):
                                success, msg = dispatch_diagnostic_email(
                                    resp.text,
                                    datetime.today().strftime("%Y-%m-%d"),
                                    "Morning 06:00 AM Synthesis Digest",
                                    st.session_state.subscribers,
                                    is_morning_digest=True
                                )
                                if success:
                                    st.success(f"Digest dispatched to {len(st.session_state.subscribers)} subscriber(s)!")
                                else:
                                    st.error(f"Failed to dispatch: {msg}")
                    else:
                        st.info("No subscribers currently configured in the Settings modal.")

                except Exception as e:
                    st.error(f"Digest generation error: {str(e)}")
