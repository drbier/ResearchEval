with open('src/api/server.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 1. Replace line 1862 to 1878 (0-indexed 1861 to 1878)
new_tabs = [
    '                <!-- Master 3-Mode Navigation Switcher: F.A.C.T. (Find -> Analyze -> Contextualize) -->\n',
    '                <div class="flex items-center bg-slate-100 dark:bg-slate-800 p-1 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold gap-1 shrink-0">\n',
    '                    <button id="masterTabFinder" onclick="switchMasterMode(\'finder\')" class="px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium">\n',
    '                        <span>🔍</span> <span>Find</span>\n',
    '                    </button>\n',
    '                    <button id="masterTabAppraisal" onclick="switchMasterMode(\'appraisal\')" class="px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs">\n',
    '                        <span>🔬</span> <span>Analyze</span>\n',
    '                    </button>\n',
    '                    <button id="masterTabSummarizer" onclick="switchMasterMode(\'summarizer\')" class="px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium">\n',
    '                        <span>📝</span> <span>Contextualize</span>\n',
    '                        <span id="summarizerBatchBadge" class="hidden ml-1 px-1.5 py-0.2 bg-sky-600 text-white rounded-full text-[10px] font-bold">0</span>\n',
    '                    </button>\n',
    '                </div>\n'
]

# Verify where old tabs start
start_idx = None
end_idx = None
for i, l in enumerate(lines):
    if 'Master 4-Mode Navigation Switcher' in l:
        start_idx = i
    if start_idx is not None and 'Center: Compact Unified Input' in l:
        end_idx = i - 1
        break

print(f'Replacing tabs from line {start_idx+1} to {end_idx+1}')
lines[start_idx:end_idx] = new_tabs

# 2. Locate the end of the unified input container and insert the Library button
input_end_idx = None
for i, l in enumerate(lines):
    if 'startUrlResolution()' in l:
        # The closing </div> for the unified input is 2 lines down
        input_end_idx = i + 2
        break

print(f'Found unified input closing </div> at line {input_end_idx+1}: {lines[input_end_idx].strip()}')

library_btn_lines = [
    '\n',
    '                <!-- Library Storage Access (Icon Button with Tooltip & Live Badge) -->\n',
    '                <button id="masterTabLibrary" onclick="toggleLibraryMode()" class="relative p-2 rounded-lg bg-slate-50 hover:bg-slate-100 dark:bg-slate-800 dark:hover:bg-slate-750 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-slate-700 shadow-2xs transition cursor-pointer shrink-0 flex items-center justify-center" title="Library — Saved Appraisals" aria-label="Library">\n',
    '                    <span class="text-base leading-none">📚</span>\n',
    '                    <span id="userLibraryBadge" class="hidden absolute -top-1 -right-1 flex h-4 min-w-4 px-1 items-center justify-center rounded-full bg-emerald-600 text-white text-[10px] font-bold leading-none shadow-xs">0</span>\n',
    '                </button>\n'
]

lines[input_end_idx+1:input_end_idx+1] = library_btn_lines

# 3. Add toggleLibraryMode and update switchMasterMode button styling
for i, l in enumerate(lines):
    if 'function switchMasterMode(mode)' in l:
        toggle_code = [
            '            function toggleLibraryMode() {\n',
            '                if (window.ResearchAppState && window.ResearchAppState.currentMasterMode === "library") {\n',
            '                    switchMasterMode(window.ResearchAppState.previousMasterMode || "appraisal");\n',
            '                } else {\n',
            '                    switchMasterMode("library");\n',
            '                }\n',
            '            }\n',
            '\n'
        ]
        lines[i:i] = toggle_code
        break

# Update previousMasterMode tracking and button styling
full_content = ''.join(lines)
full_content = full_content.replace(
    'window.ResearchAppState.currentMasterMode = mode;',
    'if (window.ResearchAppState && window.ResearchAppState.currentMasterMode !== "library") {\n                    window.ResearchAppState.previousMasterMode = window.ResearchAppState.currentMasterMode;\n                }\n                window.ResearchAppState.currentMasterMode = mode;'
)

old_reset = 'if (tabLibraryBtn) tabLibraryBtn.className = "px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium";'
new_reset = 'if (tabLibraryBtn) tabLibraryBtn.className = "relative p-2 rounded-lg bg-slate-50 hover:bg-slate-100 dark:bg-slate-800 dark:hover:bg-slate-750 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-slate-700 shadow-2xs transition cursor-pointer shrink-0 flex items-center justify-center";'

old_active = 'if (tabLibraryBtn) tabLibraryBtn.className = "px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";'
new_active = 'if (tabLibraryBtn) tabLibraryBtn.className = "relative p-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border-2 border-emerald-500 shadow-2xs font-bold transition cursor-pointer shrink-0 flex items-center justify-center ring-2 ring-emerald-500/20";'

full_content = full_content.replace(old_reset, new_reset)
full_content = full_content.replace(old_active, new_active)

with open('src/api/server.py', 'w', encoding='utf-8') as f:
    f.write(full_content)

print('SUCCESS: server.py updated cleanly!')

