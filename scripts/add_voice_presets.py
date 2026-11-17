with open('src/api/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update Commentary Header Toolbar to include Voice Preset Selector
old_toolbar = """                                    <div class="flex items-center gap-2">
                                        <span class="text-sm font-bold text-slate-800 dark:text-slate-100 flex items-center gap-1.5">
                                            <span>✍️</span> <span>Clinician Editorial Commentary</span>
                                        </span>
                                        <span id="commentaryVoiceBadge" class="text-[11px] font-mono px-2 py-0.5 rounded bg-sky-50 dark:bg-sky-950 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800">Voice Calibrated</span>
                                    </div>
                                    <div class="flex items-center gap-2">
                                        <button onclick="openSettingsModal('voice')" class="text-xs text-sky-600 hover:text-sky-800 dark:text-sky-400 dark:hover:text-sky-300 font-medium transition cursor-pointer flex items-center gap-1">
                                            <span>⚙️</span> <span>Calibrate Voice</span>
                                        </button>
                                        <button id="generateCommentaryBtn" onclick="generateClinicalCommentary()" class="btn-primary-accent text-white font-semibold text-xs px-3.5 py-1.5 rounded-md transition shadow-2xs flex items-center gap-1.5 cursor-pointer">
                                            <span>✨</span> <span id="generateCommentaryBtnText">Generate Commentary</span>
                                        </button>
                                    </div>"""

new_toolbar = """                                    <div class="flex items-center gap-2 flex-wrap">
                                        <span class="text-sm font-bold text-slate-800 dark:text-slate-100 flex items-center gap-1.5">
                                            <span>✍️</span> <span>Clinician Editorial Commentary</span>
                                        </span>
                                        <span id="commentaryVoiceBadge" class="text-[11px] font-mono px-2 py-0.5 rounded bg-sky-50 dark:bg-sky-950 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800">Voice Calibrated</span>
                                    </div>
                                    <div class="flex items-center gap-2 flex-wrap">
                                        <div class="flex items-center gap-1.5">
                                            <label for="commentaryVoicePresetSelect" class="sr-only">Active Commentary Voice</label>
                                            <select id="commentaryVoicePresetSelect" onchange="setActiveVoicePreset(this.value)" class="text-xs bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-md px-2 py-1.5 text-slate-700 dark:text-slate-200 font-medium focus:outline-none focus:ring-1 focus:ring-sky-500 cursor-pointer shadow-2xs" title="Switch commentary voice without overwriting your calibrated profile">
                                                <option value="calibrated">🎙️ My Calibrated Voice</option>
                                                <option value="methodological">📊 Default: Methodological / Biostatistical</option>
                                                <option value="conventional">🩺 Default: Conventional Allopathic</option>
                                                <option value="integrative">🌿 Default: Generic Integrative</option>
                                            </select>
                                        </div>
                                        <button onclick="openSettingsModal('voice')" class="text-xs text-sky-600 hover:text-sky-800 dark:text-sky-400 dark:hover:text-sky-300 font-medium transition cursor-pointer flex items-center gap-1 px-1.5 py-1 rounded hover:bg-sky-50 dark:hover:bg-sky-950/50">
                                            <span>⚙️</span> <span>Calibrate Voice</span>
                                        </button>
                                        <button id="generateCommentaryBtn" onclick="generateClinicalCommentary()" class="btn-primary-accent text-white font-semibold text-xs px-3.5 py-1.5 rounded-md transition shadow-2xs flex items-center gap-1.5 cursor-pointer">
                                            <span>✨</span> <span id="generateCommentaryBtnText">Generate Commentary</span>
                                        </button>
                                    </div>"""

assert old_toolbar in content, "old_toolbar not found"
content = content.replace(old_toolbar, new_toolbar, 1)

# 2. Add Active Voice Preset selector & dynamic lens description in Settings Voice Section
old_voice_section_header = """                            <!-- Therapeutic Lens / Clinical Orientation -->
                            <div class="space-y-1.5">
                                <div class="flex justify-between items-center text-xs">
                                    <label for="voiceTherapeuticLens" class="font-semibold text-slate-700 dark:text-slate-300">Therapeutic Lens / Clinical Orientation</label>
                                    <span class="text-[10px] text-slate-400">Guides commentary perspective</span>
                                </div>
                                <select id="voiceTherapeuticLens" class="w-full text-xs bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-lg px-2.5 py-2 text-slate-800 dark:text-slate-200 focus:bg-white dark:focus:bg-slate-900 focus:outline-none focus:ring-1 focus:ring-sky-500 cursor-pointer">
                                    <option value="integrative">Integrative / Naturopathic / Functional (Default)</option>
                                    <option value="conventional">Conventional Allopathic / Evidence-Based</option>
                                    <option value="methodological">Pure Methodological &amp; Biostatistical Focus</option>
                                </select>
                                <p class="text-[11px] text-slate-500 dark:text-slate-400">
                                    Integrative/Naturopathic lens prioritizes biological resilience and whole-body physiology, actively preventing unsolicited conventional drug mandates (e.g. routine statin recommendations).
                                </p>
                            </div>"""

new_voice_section_header = """                            <!-- Active Voice Preset Switcher (Non-destructive) -->
                            <div class="p-3 rounded-lg border border-sky-200 dark:border-sky-900/70 bg-sky-50/50 dark:bg-sky-950/20 space-y-1.5">
                                <div class="flex justify-between items-center text-xs">
                                    <label for="settingsVoicePresetSelect" class="font-semibold text-slate-800 dark:text-slate-200">Active Commentary Voice</label>
                                    <span class="text-[10px] text-slate-500 dark:text-slate-400">Switch anytime without losing your custom profile</span>
                                </div>
                                <select id="settingsVoicePresetSelect" onchange="setActiveVoicePreset(this.value)" class="w-full text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-2.5 py-2 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-sky-500 cursor-pointer font-medium">
                                    <option value="calibrated">🎙️ My Calibrated Voice (Custom Philosophy &amp; Exemplars)</option>
                                    <option value="methodological">📊 Default: Methodological &amp; Biostatistical Focus</option>
                                    <option value="conventional">🩺 Default: Conventional Allopathic (GDMT)</option>
                                    <option value="integrative">🌿 Default: Generic Integrative / Naturopathic</option>
                                </select>
                                <p id="settingsVoicePresetNotice" class="hidden text-[11px] text-amber-800 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/60 rounded px-2.5 py-1.5">
                                    Using a built-in default voice for commentary generation. Your custom calibrated philosophy and exemplars below remain safely saved.
                                </p>
                            </div>

                            <!-- Therapeutic Lens / Clinical Orientation -->
                            <div class="space-y-1.5">
                                <div class="flex justify-between items-center text-xs">
                                    <label for="voiceTherapeuticLens" class="font-semibold text-slate-700 dark:text-slate-300">Therapeutic Lens / Clinical Orientation</label>
                                    <span class="text-[10px] text-slate-400">Guides commentary perspective</span>
                                </div>
                                <select id="voiceTherapeuticLens" onchange="updateVoiceLensDescription()" class="w-full text-xs bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-lg px-2.5 py-2 text-slate-800 dark:text-slate-200 focus:bg-white dark:focus:bg-slate-900 focus:outline-none focus:ring-1 focus:ring-sky-500 cursor-pointer">
                                    <option value="integrative">Integrative / Naturopathic / Functional (Default)</option>
                                    <option value="conventional">Conventional Allopathic / Evidence-Based</option>
                                    <option value="methodological">Pure Methodological &amp; Biostatistical Focus</option>
                                </select>
                                <p id="voiceTherapeuticLensDesc" class="text-[11px] text-slate-500 dark:text-slate-400">
                                    Integrative/Naturopathic lens prioritizes biological resilience and whole-body physiology, actively preventing unsolicited conventional drug mandates (e.g. routine statin recommendations).
                                </p>
                            </div>"""

assert old_voice_section_header in content, "old_voice_section_header not found"
content = content.replace(old_voice_section_header, new_voice_section_header, 1)

# 3. Add VOICE_PRESETS, activeVoicePresetKey, setActiveVoicePreset, getEffectiveVoiceProfile, updateVoiceLensDescription
old_state_init = """            let voiceProfileState = JSON.parse(JSON.stringify(GENERIC_DEFAULT_VOICE));

            function loadVoiceProfileFromLocal() {"""

new_state_init = """            const VOICE_PRESETS = {
                methodological: {
                    label: "Methodological / Biostatistical",
                    therapeutic_lens: "methodological",
                    philosophy: "Maintain an objective, neutral biostatistical stance. Focus strictly on study design validity, statistical power, confounding variables, selection bias, surrogate versus hard endpoint dissociation, and multiplicity control.",
                    preferred_terms: "absolute risk reduction, confidence interval, confounding, statistical power, endpoint validity, effect size",
                    prohibited_terms: "more research is needed, delve, it is crucial to note",
                    exemplars: []
                },
                conventional: {
                    label: "Conventional Allopathic",
                    therapeutic_lens: "conventional",
                    philosophy: "Evaluate findings according to established guideline-directed medical therapy (GDMT) and evidence-based standard-of-care algorithms, balancing clinical efficacy, number needed to treat, and adverse event profiles.",
                    preferred_terms: "guideline-directed therapy, number needed to treat, absolute risk reduction, clinical significance, standard of care",
                    prohibited_terms: "more research is needed, delve, it is crucial to note",
                    exemplars: []
                },
                integrative: {
                    label: "Generic Integrative",
                    therapeutic_lens: "integrative",
                    philosophy: GENERIC_DEFAULT_VOICE.philosophy,
                    preferred_terms: GENERIC_DEFAULT_VOICE.preferred_terms,
                    prohibited_terms: GENERIC_DEFAULT_VOICE.prohibited_terms,
                    exemplars: []
                }
            };

            let activeVoicePresetKey = localStorage.getItem('fact_active_voice_preset') || 'calibrated';
            if (activeVoicePresetKey !== 'calibrated' && !VOICE_PRESETS[activeVoicePresetKey]) {
                activeVoicePresetKey = 'calibrated';
            }

            let voiceProfileState = JSON.parse(JSON.stringify(GENERIC_DEFAULT_VOICE));

            function getEffectiveVoiceProfile() {
                if (activeVoicePresetKey !== 'calibrated' && VOICE_PRESETS[activeVoicePresetKey]) {
                    return VOICE_PRESETS[activeVoicePresetKey];
                }
                return voiceProfileState;
            }

            function setActiveVoicePreset(presetKey) {
                activeVoicePresetKey = (presetKey === 'calibrated' || VOICE_PRESETS[presetKey]) ? presetKey : 'calibrated';
                try {
                    localStorage.setItem('fact_active_voice_preset', activeVoicePresetKey);
                } catch (e) {}
                updateVoiceUIElements();
                renderVoiceModalUI();
            }

            function updateVoiceLensDescription() {
                const lens = document.getElementById('voiceTherapeuticLens');
                const desc = document.getElementById('voiceTherapeuticLensDesc');
                if (!lens || !desc) return;
                if (lens.value === 'conventional') {
                    desc.innerText = "Conventional Allopathic lens evaluates findings within guideline-directed medical therapy (GDMT), consensus standards of care, and pharmacotherapy risk-benefit.";
                } else if (lens.value === 'methodological') {
                    desc.innerText = "Pure Methodological & Biostatistical lens maintains a therapeutically neutral stance focused strictly on study design, bias, statistical power, and endpoint validity.";
                } else {
                    desc.innerText = "Integrative/Naturopathic lens prioritizes biological resilience and whole-body physiology, actively preventing unsolicited conventional drug mandates (e.g. routine statin recommendations).";
                }
            }

            function loadVoiceProfileFromLocal() {"""

assert old_state_init in content, "old_state_init not found"
content = content.replace(old_state_init, new_state_init, 1)

# 4. Update updateVoiceUIElements to reflect active preset and sync selects
old_badge_update = """                const badge = document.getElementById('commentaryVoiceBadge');
                if (badge) {
                    const activeCount = (voiceProfileState.exemplars || []).filter(e => e.is_active).length;
                    badge.innerText = activeCount > 0 ? `Voice Calibrated (${activeCount} Exemplars)` : `Voice Calibrated (Philosophy Only)`;
                }"""

new_badge_update = """                const badge = document.getElementById('commentaryVoiceBadge');
                if (badge) {
                    if (activeVoicePresetKey !== 'calibrated' && VOICE_PRESETS[activeVoicePresetKey]) {
                        badge.innerText = `Voice: ${VOICE_PRESETS[activeVoicePresetKey].label}`;
                    } else {
                        const activeCount = (voiceProfileState.exemplars || []).filter(e => e.is_active).length;
                        badge.innerText = activeCount > 0 ? `Voice Calibrated (${activeCount} Exemplars)` : `Voice Calibrated (Philosophy Only)`;
                    }
                }
                const commentarySelect = document.getElementById('commentaryVoicePresetSelect');
                if (commentarySelect && commentarySelect.value !== activeVoicePresetKey) {
                    commentarySelect.value = activeVoicePresetKey;
                }
                const settingsSelect = document.getElementById('settingsVoicePresetSelect');
                if (settingsSelect && settingsSelect.value !== activeVoicePresetKey) {
                    settingsSelect.value = activeVoicePresetKey;
                }
                const presetNotice = document.getElementById('settingsVoicePresetNotice');
                if (presetNotice) {
                    if (activeVoicePresetKey === 'calibrated') {
                        presetNotice.classList.add('hidden');
                    } else {
                        presetNotice.classList.remove('hidden');
                    }
                }"""

assert old_badge_update in content, "old_badge_update not found"
content = content.replace(old_badge_update, new_badge_update, 1)

# 5. Update renderVoiceModalUI to also sync preset select & lens description
old_render_modal = """                if (lens) lens.value = voiceProfileState.therapeutic_lens || 'integrative';
                if (phil) phil.value = voiceProfileState.philosophy || '';
                if (pref) pref.value = voiceProfileState.preferred_terms || '';
                if (proh) proh.value = voiceProfileState.prohibited_terms || '';
                updateVoiceFieldCounts();"""

new_render_modal = """                const settingsSelect = document.getElementById('settingsVoicePresetSelect');
                if (settingsSelect) settingsSelect.value = activeVoicePresetKey;
                const presetNotice = document.getElementById('settingsVoicePresetNotice');
                if (presetNotice) {
                    if (activeVoicePresetKey === 'calibrated') presetNotice.classList.add('hidden');
                    else presetNotice.classList.remove('hidden');
                }
                if (lens) lens.value = voiceProfileState.therapeutic_lens || 'integrative';
                if (phil) phil.value = voiceProfileState.philosophy || '';
                if (pref) pref.value = voiceProfileState.preferred_terms || '';
                if (proh) proh.value = voiceProfileState.prohibited_terms || '';
                updateVoiceLensDescription();
                updateVoiceFieldCounts();"""

assert old_render_modal in content, "old_render_modal not found"
content = content.replace(old_render_modal, new_render_modal, 1)

# 6. Update generateClinicalCommentary to send getEffectiveVoiceProfile()
old_gen_append = """                    formData.append('voice_profile', JSON.stringify(voiceProfileState));"""
new_gen_append = """                    formData.append('voice_profile', JSON.stringify(getEffectiveVoiceProfile()));"""

assert old_gen_append in content, "old_gen_append not found"
content = content.replace(old_gen_append, new_gen_append, 1)

# 7. Update autoSaveAppraisalToLibrary to use getEffectiveVoiceProfile().therapeutic_lens
old_autosave_lens = """                        therapeutic_lens: (voiceProfileState && voiceProfileState.therapeutic_lens) ? voiceProfileState.therapeutic_lens : 'integrative',"""
new_autosave_lens = """                        therapeutic_lens: (typeof getEffectiveVoiceProfile === 'function' ? getEffectiveVoiceProfile().therapeutic_lens : (voiceProfileState && voiceProfileState.therapeutic_lens)) || 'integrative',"""

assert old_autosave_lens in content, "old_autosave_lens not found"
content = content.replace(old_autosave_lens, new_autosave_lens, 1)

with open('src/api/server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Voice preset selector implemented cleanly in server.py!")
