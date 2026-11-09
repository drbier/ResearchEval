with open('src/api/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update Ask toolbar to include clean export buttons
old_quick_inquiries = '''                                <!-- Quick Clinical Inquiries -->
                                <div class="flex-shrink-0 bg-slate-50 dark:bg-slate-950/70 p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 space-y-1.5">
                                    <span class="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 block">Quick Inquiries:</span>
                                    <div class="flex flex-wrap gap-1.5">
                                        <button onclick="askQuickChip('How many total participants were randomized or enrolled in the study?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">👥 Total Sample Size</button>
                                        <button onclick="askQuickChip('What was the primary endpoint, and was it statistically significant?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">🎯 Primary Endpoint</button>
                                        <button onclick="askQuickChip('Does the study report Overall Survival (OS) or MACE outcomes? What were the hazard ratios?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">📈 Survival / MACE</button>
                                        <button onclick="askQuickChip('What adverse events or safety signals were significantly different between groups?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">⚠️ Safety & Harms</button>
                                    </div>
                                </div>'''

new_quick_inquiries = '''                                <!-- Ask Toolbar: Quick Inquiries & Clean Export Controls -->
                                <div class="flex-shrink-0 bg-slate-50 dark:bg-slate-950/70 p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-2">
                                    <div class="space-y-1.5 flex-1 min-w-0">
                                        <span class="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 block">Quick Inquiries:</span>
                                        <div class="flex flex-wrap gap-1.5">
                                            <button onclick="askQuickChip('How many total participants were randomized or enrolled in the study?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">👥 Total Sample Size</button>
                                            <button onclick="askQuickChip('What was the primary endpoint, and was it statistically significant?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">🎯 Primary Endpoint</button>
                                            <button onclick="askQuickChip('Does the study report Overall Survival (OS) or MACE outcomes? What were the hazard ratios?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">📈 Survival / MACE</button>
                                            <button onclick="askQuickChip('What adverse events or safety signals were significantly different between groups?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">⚠️ Safety & Harms</button>
                                        </div>
                                    </div>
                                    <!-- Clean Export Toolbar for Peer Dialogue / Colleague Responses -->
                                    <div class="flex items-center gap-1.5 shrink-0 self-end md:self-center border-t md:border-t-0 md:border-l border-slate-200 dark:border-slate-800 pt-1.5 md:pt-0 md:pl-2">
                                        <button id="copyCleanAskChatBtn" onclick="copyCleanAskConversation()" class="px-2.5 py-1 rounded-md bg-white dark:bg-slate-850 hover:bg-emerald-50 dark:hover:bg-emerald-950/40 text-slate-700 dark:text-slate-300 hover:text-emerald-700 dark:hover:text-emerald-300 border border-slate-200 dark:border-slate-700 hover:border-emerald-300 text-[11px] font-semibold transition shadow-2xs cursor-pointer flex items-center gap-1" title="Copy entire conversation without [sec, pX] coordinate anchors for pasting into peer emails, forums, or chats">
                                            <span>📋</span> <span id="copyCleanAskChatBtnText">Copy Clean Chat</span>
                                        </button>
                                        <button onclick="resetAskChat()" class="px-2 py-1 rounded-md bg-white dark:bg-slate-850 hover:bg-rose-50 dark:hover:bg-rose-950/40 text-slate-500 hover:text-rose-600 dark:text-slate-400 dark:hover:text-rose-400 border border-slate-200 dark:border-slate-700 hover:border-rose-300 text-[11px] font-medium transition shadow-2xs cursor-pointer flex items-center gap-1" title="Clear conversational history">
                                            <span>🔄</span> <span>Clear</span>
                                        </button>
                                    </div>
                                </div>'''

assert old_quick_inquiries in content, "old_quick_inquiries not found"
content = content.replace(old_quick_inquiries, new_quick_inquiries, 1)

# 2. Update assistant message rendering to add individual "Copy Clean" button per turn
old_assistant_msg = '''                    const assistantMsgEl = document.createElement('div');
                    assistantMsgEl.className = 'flex justify-start';
                    assistantMsgEl.innerHTML = `
                        <div class="max-w-[90%] bg-white border border-slate-200 text-slate-800 rounded-lg px-3.5 py-2.5 shadow-2xs space-y-1.5">
                            <div class="text-[11px] font-semibold text-slate-500 flex items-center justify-between">
                                <span>Study Wonk Answer ${cachedBadge}</span>
                            </div>
                            <div class="prose prose-sm max-w-none text-xs leading-relaxed">${answerHtml}</div>
                        </div>
                    `;'''

new_assistant_msg = '''                    const turnIndex = askConversationHistory.length;
                    const rawAnswerText = data.answer || data.message || '';
                    const assistantMsgEl = document.createElement('div');
                    assistantMsgEl.className = 'flex justify-start';
                    assistantMsgEl.innerHTML = `
                        <div class="max-w-[90%] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-100 rounded-lg px-3.5 py-2.5 shadow-2xs space-y-2 group">
                            <div class="text-[11px] font-semibold text-slate-500 dark:text-slate-400 flex items-center justify-between">
                                <span>Study Wonk Answer ${cachedBadge}</span>
                                <button onclick="copySingleCleanAnswer(this, ${turnIndex})" class="px-2 py-0.5 rounded text-[10px] font-medium text-slate-500 dark:text-slate-400 hover:text-emerald-600 dark:hover:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-950/40 border border-transparent hover:border-emerald-300 dark:hover:border-emerald-800 transition cursor-pointer flex items-center gap-1" title="Copy this response without bracket coordinate anchors for pasting into dialogue">
                                    <span>📋</span> <span>Copy Clean</span>
                                </button>
                            </div>
                            <div class="prose prose-sm max-w-none text-xs leading-relaxed">${answerHtml}</div>
                        </div>
                    `;'''

assert old_assistant_msg in content, "old_assistant_msg not found"
content = content.replace(old_assistant_msg, new_assistant_msg, 1)

# 3. Add clean-text utilities: stripCoordinateAnchors, copyCleanAskConversation, copySingleCleanAnswer
clean_export_helpers = '''            // Utility: Strip bracket coordinate anchors [sec, pX] for clean external dialogue
            function stripCoordinateAnchors(rawText) {
                if (!rawText) return '';
                // Coordinate regex matching Doc_Header, Abstract, Intro, Methods, Results, Disc, Para, p\\d+, etc.
                const bracketCoordRegex = /\\s*\\[[^\\]]*?\\b(?:Doc_Header|Header|Abstract|Abs|Intro(?:duction)?|Methods?|Meth|Patients?\\s+and\\s+Methods?|Materials?\\s+and\\s+Methods?|Results?|Res|Findings?|Discussion|Disc|Conclusions?|Concl|Appendix|Supp(?:lementary)?|Para(?:graph)?|Table(?:Note)?|Fig(?:ure)?(?:Legend)?|Box|p\\d+)\\b[^\\]]*?\\]/gi;
                let cleaned = rawText.replace(bracketCoordRegex, '');
                // Clean orphan rule tags if present
                cleaned = cleaned.replace(/\\s*\\{R_[A-Z0-9_]+\\}/g, '').replace(/\\s*\\[R_[A-Z0-9_]+\\]/g, '');
                // Fix spacing before punctuation caused by removed bracket (e.g., "word ." -> "word.")
                cleaned = cleaned.replace(/ +([,\\.\\?!;:])/g, '$1');
                // Clean multiple consecutive whitespace
                cleaned = cleaned.replace(/[ \\t]+/g, ' ');
                return cleaned.trim();
            }

            // Copy entire conversation cleaned of coordinate anchors
            async function copyCleanAskConversation() {
                const btnText = document.getElementById('copyCleanAskChatBtnText');
                if (!askConversationHistory || askConversationHistory.length === 0) {
                    if (btnText) {
                        const orig = btnText.innerText;
                        btnText.innerText = 'No messages yet';
                        setTimeout(() => { btnText.innerText = orig; }, 1800);
                    }
                    return;
                }

                // Format entire dialogue as clean Q&A
                const cleanDialogue = askConversationHistory.map(item => {
                    const cleanContent = stripCoordinateAnchors(item.content);
                    if (item.role === 'user') {
                        return `Q: ${cleanContent}`;
                    } else {
                        return `A: ${cleanContent}\\n`;
                    }
                }).join('\\n\\n');

                try {
                    await navigator.clipboard.writeText(cleanDialogue);
                    if (btnText) {
                        const orig = btnText.innerText;
                        btnText.innerText = '✓ Copied Clean Chat!';
                        setTimeout(() => { btnText.innerText = orig; }, 2200);
                    }
                } catch (err) {
                    console.error('Clipboard copy failed:', err);
                    alert('Could not copy to clipboard: ' + err.message);
                }
            }

            // Copy single assistant answer cleaned of coordinate anchors
            async function copySingleCleanAnswer(btnEl, turnIndex) {
                if (!askConversationHistory) return;
                // Target the assistant entry corresponding to this turn
                let targetContent = '';
                if (askConversationHistory[turnIndex] && askConversationHistory[turnIndex].role === 'assistant') {
                    targetContent = askConversationHistory[turnIndex].content;
                } else if (turnIndex > 0 && askConversationHistory[turnIndex - 1] && askConversationHistory[turnIndex - 1].role === 'assistant') {
                    targetContent = askConversationHistory[turnIndex - 1].content;
                } else if (askConversationHistory.length > 0) {
                    // Fallback to most recent assistant entry
                    const lastAss = [...askConversationHistory].reverse().find(m => m.role === 'assistant');
                    if (lastAss) targetContent = lastAss.content;
                }

                if (!targetContent) return;
                const cleanText = stripCoordinateAnchors(targetContent);

                try {
                    await navigator.clipboard.writeText(cleanText);
                    if (btnEl) {
                        const origHtml = btnEl.innerHTML;
                        btnEl.innerHTML = '<span>✓</span> <span class="text-emerald-600 dark:text-emerald-400 font-bold">Copied!</span>';
                        setTimeout(() => { btnEl.innerHTML = origHtml; }, 2000);
                    }
                } catch (err) {
                    console.error('Clipboard copy failed:', err);
                    alert('Could not copy to clipboard: ' + err.message);
                }
            }
'''

target_reset = "function resetAskChat() {"
assert target_reset in content, "resetAskChat not found"
content = content.replace(target_reset, clean_export_helpers + "\n            " + target_reset, 1)

with open('src/api/server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Ask clean export feature added to server.py!")

