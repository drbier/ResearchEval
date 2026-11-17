with open('src/api/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update appraiseBtn definition
old_appraise_btn = """                    const appraiseBtn = hasFullText ? `
                        <button 
                            onclick="appraisePaperFromExternal('${appraiseTargetUrl}')" 
                            class="px-3 py-1.5 rounded-lg ${isEPMC ? 'bg-teal-600 hover:bg-teal-700' : 'bg-sky-600 hover:bg-sky-700'} text-white text-xs font-semibold transition shadow-2xs flex items-center gap-1 cursor-pointer"
                            title="Open full interactive analysis in Workbench (${isEPMC ? 'Full manuscript retrieved via Europe PMC' : 'Full manuscript retrieved via PMC'})"
                        >
                            <span>🔬</span> <span>Analyze Full Text ${isEPMC ? '(Europe PMC)' : ''}</span>
                        </button>
                    ` : `
                        <button 
                            onclick="appraisePaperFromExternal('${safeUrl}')" 
                            class="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold transition shadow-2xs flex items-center gap-1 cursor-pointer"
                            title="Paywalled paper: Analyze published abstract or upload full-text PDF in Workbench"
                        >
                            <span>📄</span> <span>Analyze Abstract</span>
                        </button>
                    `;"""

new_appraise_btn = """                    const appraiseBtn = hasFullText ? `
                        <button 
                            onclick="appraisePaperFromExternal('${appraiseTargetUrl}')" 
                            class="px-3 py-1.5 rounded-lg ${isEPMC ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-sky-600 hover:bg-sky-700'} text-white text-xs font-semibold transition shadow-2xs flex items-center gap-1 cursor-pointer shrink-0"
                            title="Open full interactive analysis in Workbench (${isEPMC ? 'Full manuscript retrieved via Europe PMC' : 'Full manuscript retrieved via PMC'})"
                        >
                            <span>🔬</span> <span>Analyze Full Text ${isEPMC ? '(Europe PMC)' : ''}</span>
                        </button>
                    ` : `
                        <button 
                            onclick="appraisePaperFromExternal('${safeUrl}')" 
                            class="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold transition shadow-2xs flex items-center gap-1 cursor-pointer shrink-0"
                            title="Paywalled paper: Analyze published abstract or upload full-text PDF in Workbench"
                        >
                            <span>📄</span> <span>Analyze Abstract</span>
                        </button>
                    `;"""

assert old_appraise_btn in content, "old_appraise_btn not found"
content = content.replace(old_appraise_btn, new_appraise_btn, 1)

# 2. Update the card footer container to guarantee right justification
old_footer = """                            <div class="flex flex-wrap items-center justify-between gap-3 pt-1 border-t border-slate-100">
                                <div class="flex flex-wrap items-center gap-3">
                                    <a href="${safeUrl}" target="_blank" rel="noopener noreferrer" class="text-xs text-sky-600 hover:text-sky-800 underline flex items-center gap-1 font-mono">
                                        <span>🔗</span> <span>${safeUrl}</span>
                                    </a>
                                    ${pmcLinkHtml}
                                    ${scholarBadge}
                                </div>
                                <div class="flex items-center gap-2">
                                    <button 
                                        onclick="toggleContextualizerBatch(this, '${safeUrl}', '${safeTitle}')" 
                                        class="contextualizer-toggle-btn px-3 py-1.5 rounded-lg ${window.ResearchAppState.summarizerBatch.includes(safeUrl) ? 'bg-sky-600 hover:bg-sky-700 text-white border-sky-600 shadow-2xs' : 'bg-slate-100 hover:bg-slate-200 text-slate-700 border-slate-300'} text-xs font-semibold transition border flex items-center gap-1 cursor-pointer"
                                        title="${window.ResearchAppState.summarizerBatch.includes(safeUrl) ? 'Click to remove from contextualizer batch' : 'Add to multi-paper contextualizer batch'}"
                                        data-url="${safeUrl}"
                                    >
                                        ${window.ResearchAppState.summarizerBatch.includes(safeUrl) ? '<span>+ Added</span>' : '<span>➕</span> <span>Add to Contextualizer</span>'}
                                    </button>
                                    ${appraiseBtn}
                                </div>
                            </div>"""

new_footer = """                            <div class="flex flex-wrap items-center justify-between gap-3 pt-1 border-t border-slate-100">
                                <div class="flex flex-wrap items-center gap-3 flex-1 min-w-0">
                                    <a href="${safeUrl}" target="_blank" rel="noopener noreferrer" class="text-xs text-sky-600 hover:text-sky-800 underline flex items-center gap-1 font-mono break-all">
                                        <span>🔗</span> <span>${safeUrl}</span>
                                    </a>
                                    ${pmcLinkHtml}
                                    ${scholarBadge}
                                </div>
                                <div class="flex items-center gap-2 ml-auto shrink-0">
                                    <button 
                                        onclick="toggleContextualizerBatch(this, '${safeUrl}', '${safeTitle}')" 
                                        class="contextualizer-toggle-btn px-3 py-1.5 rounded-lg ${window.ResearchAppState.summarizerBatch.includes(safeUrl) ? 'bg-sky-600 hover:bg-sky-700 text-white border-sky-600 shadow-2xs' : 'bg-slate-100 hover:bg-slate-200 text-slate-700 border-slate-300'} text-xs font-semibold transition border flex items-center gap-1 cursor-pointer shrink-0"
                                        title="${window.ResearchAppState.summarizerBatch.includes(safeUrl) ? 'Click to remove from contextualizer batch' : 'Add to multi-paper contextualizer batch'}"
                                        data-url="${safeUrl}"
                                    >
                                        ${window.ResearchAppState.summarizerBatch.includes(safeUrl) ? '<span>+ Added</span>' : '<span>➕</span> <span>Add to Contextualizer</span>'}
                                    </button>
                                    ${appraiseBtn}
                                </div>
                            </div>"""

assert old_footer in content, "old_footer not found"
content = content.replace(old_footer, new_footer, 1)

with open('src/api/server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: server.py updated with right-justified action buttons and green Europe PMC button styling!")
