with open('src/api/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = """                // Toggle visibility between sibling DOM containers
                if (finderCont) finderCont.classList.add('hidden');
                if (summarizerCont) summarizerCont.classList.add('hidden');
                if (libraryCont) libraryCont.classList.add('hidden');
                if (resultBox) resultBox.classList.add('hidden');"""

replacement = """                // Toggle visibility between sibling DOM containers
                if (finderCont) finderCont.classList.add('hidden');
                if (summarizerCont) summarizerCont.classList.add('hidden');
                if (libraryCont) libraryCont.classList.add('hidden');
                if (resultBox) resultBox.classList.add('hidden');

                const studyBadgeWrapper = document.getElementById('studyBadgeWrapper');"""

assert target in content, 'Target not found'
content = content.replace(target, replacement, 1)

old_modes = """                if (mode === 'finder') {
                    if (finderCont) finderCont.classList.remove('hidden');
                    if (tabFinderBtn) tabFinderBtn.className = "px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
                } else if (mode === 'summarizer') {
                    if (summarizerCont) summarizerCont.classList.remove('hidden');
                    if (tabSummarizerBtn) tabSummarizerBtn.className = "px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
                    syncSummarizerInputFromBatch();
                } else if (mode === 'library') {
                    if (libraryCont) libraryCont.classList.remove('hidden');
                    if (tabLibraryBtn) tabLibraryBtn.className = "relative p-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border-2 border-emerald-500 shadow-2xs font-bold transition cursor-pointer shrink-0 flex items-center justify-center ring-2 ring-emerald-500/20";
                    refreshUserLibraryUI();
                } else {
                    // Mode 'appraisal'
                    if (tabAppraisalBtn) tabAppraisalBtn.className = "px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
                    // Only unhide resultBox if appraisal content has already been generated
                    if (currentFilename) {
                        if (resultBox) resultBox.classList.remove('hidden');
                        if (typeof centerHighlightInViewer === 'function') {
                            requestAnimationFrame(() => centerHighlightInViewer(false));
                        }
                    }
                }"""

new_modes = """                if (mode === 'finder') {
                    if (finderCont) finderCont.classList.remove('hidden');
                    if (tabFinderBtn) tabFinderBtn.className = "px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
                    if (studyBadgeWrapper) studyBadgeWrapper.classList.add('hidden');
                } else if (mode === 'summarizer') {
                    if (summarizerCont) summarizerCont.classList.remove('hidden');
                    if (tabSummarizerBtn) tabSummarizerBtn.className = "px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
                    if (studyBadgeWrapper) studyBadgeWrapper.classList.add('hidden');
                    syncSummarizerInputFromBatch();
                } else if (mode === 'library') {
                    if (libraryCont) libraryCont.classList.remove('hidden');
                    if (tabLibraryBtn) tabLibraryBtn.className = "relative p-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border-2 border-emerald-500 shadow-2xs font-bold transition cursor-pointer shrink-0 flex items-center justify-center ring-2 ring-emerald-500/20";
                    if (studyBadgeWrapper) studyBadgeWrapper.classList.add('hidden');
                    refreshUserLibraryUI();
                } else {
                    // Mode 'appraisal'
                    if (tabAppraisalBtn) tabAppraisalBtn.className = "px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
                    // Only unhide resultBox and studyBadgeWrapper if appraisal content has already been generated
                    if (currentFilename) {
                        if (resultBox) resultBox.classList.remove('hidden');
                        if (studyBadgeWrapper && window.ResearchAppState && window.ResearchAppState.lastAppraisalData && window.ResearchAppState.lastAppraisalData.triage) {
                            studyBadgeWrapper.classList.remove('hidden');
                        }
                        if (typeof centerHighlightInViewer === 'function') {
                            requestAnimationFrame(() => centerHighlightInViewer(false));
                        }
                    } else {
                        if (studyBadgeWrapper) studyBadgeWrapper.classList.add('hidden');
                    }
                }"""

assert old_modes in content, 'old_modes not found'
content = content.replace(old_modes, new_modes, 1)

with open('src/api/server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('SUCCESS: switchMasterMode updated to hide studyBadgeWrapper outside appraisal mode!')
