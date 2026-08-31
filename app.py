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

    # State storage for the latest report
    if "current_report" not in st.session_state:
        st.session_state.current_report = None
    if "current_category" not in st.session_state:
        st.session_state.current_category = ""
    if "current_date_str" not in st.session_state:
        st.session_state.current_date_str = ""

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
                    
                    # Store report in state for viewing & separate dispatch
                    st.session_state.current_report = response.text
                    st.session_state.current_category = category_label
                    st.session_state.current_date_str = log_date.strftime("%Y-%m-%d")
                    
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
                    
                except Exception as e:
                    st.error(f"Error during analysis: {str(e)}")

    # Display Generated Report
    if st.session_state.current_report:
        st.markdown("---")
        st.markdown(st.session_state.current_report)
        st.markdown("---")

        # Action 2: Dedicated Email Dispatch Box with OK Button
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
