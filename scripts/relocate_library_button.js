const fs = require('fs');

let s = fs.readFileSync('src/api/server.py', 'utf8');

// 1. Replace the Master 4-Mode navigation with 3-Mode navigation (removing Library from the pill)
const oldTabs = `                <!-- Master 4-Mode Navigation Switcher: F.A.C.T. (Find -> Analyze -> Contextualize -> Library) -->
                <div class="flex items-center bg-slate-100 dark:bg-slate-800 p-1 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold gap-1 shrink-0">
                    <button id="masterTabFinder" onclick="switchMasterMode('finder')" class="px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium">
                        <span>🔍</span> <span>Find</span>
                    </button>
                    <button id="masterTabAppraisal" onclick="switchMasterMode('appraisal')" class="px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs">
                        <span>🔬</span> <span>Analyze</span>
                    </button>
                    <button id="masterTabSummarizer" onclick="switchMasterMode('summarizer')" class="px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium">
                        <span>📝</span> <span>Contextualize</span>
                        <span id="summarizerBatchBadge" class="hidden ml-1 px-1.5 py-0.2 bg-sky-600 text-white rounded-full text-[10px] font-bold">0</span>
                    </button>
                    <button id="masterTabLibrary" onclick="switchMasterMode('library')" class="px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium">
                        <span>📚</span> <span>Library</span>
                        <span id="userLibraryBadge" class="hidden ml-1 px-1.5 py-0.2 bg-emerald-600 text-white rounded-full text-[10px] font-bold">0</span>
                    </button>
                </div>`;

const newTabs = `                <!-- Master 3-Mode Navigation Switcher: F.A.C.T. (Find -> Analyze -> Contextualize) -->
                <div class="flex items-center bg-slate-100 dark:bg-slate-800 p-1 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold gap-1 shrink-0">
                    <button id="masterTabFinder" onclick="switchMasterMode('finder')" class="px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium">
                        <span>🔍</span> <span>Find</span>
                    </button>
                    <button id="masterTabAppraisal" onclick="switchMasterMode('appraisal')" class="px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs">
                        <span>🔬</span> <span>Analyze</span>
                    </button>
                    <button id="masterTabSummarizer" onclick="switchMasterMode('summarizer')" class="px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium">
                        <span>📝</span> <span>Contextualize</span>
                        <span id="summarizerBatchBadge" class="hidden ml-1 px-1.5 py-0.2 bg-sky-600 text-white rounded-full text-[10px] font-bold">0</span>
                    </button>
                </div>`;

// 2. Add the compact Library button directly to the right of the unified input container
const oldInputEnd = `                    <!-- URL / PMID Input Control -->
                    <div id="tabUrl" class="hidden flex items-center gap-2 flex-1">
                        <input type="text" id="paperUrl" placeholder="Paste PubMed URL, PMID (e.g. 37726553), PMC ID, or DOI" class="block w-full text-xs text-slate-800 dark:text-slate-100 bg-white dark:bg-slate-900 px-3 py-1.5 rounded border border-slate-200 dark:border-slate-700 focus:outline-none"/>
                        <button onclick="startUrlResolution()" id="resolveBtn" class="btn-primary-accent text-white font-semibold text-xs px-4 py-1.5 rounded transition shadow-xs shrink-0">Fetch & Analyze</button>
                    </div>
                </div>`;

const newInputEnd = `                    <!-- URL / PMID Input Control -->
                    <div id="tabUrl" class="hidden flex items-center gap-2 flex-1">
                        <input type="text" id="paperUrl" placeholder="Paste PubMed URL, PMID (e.g. 37726553), PMC ID, or DOI" class="block w-full text-xs text-slate-800 dark:text-slate-100 bg-white dark:bg-slate-900 px-3 py-1.5 rounded border border-slate-200 dark:border-slate-700 focus:outline-none"/>
                        <button onclick="startUrlResolution()" id="resolveBtn" class="btn-primary-accent text-white font-semibold text-xs px-4 py-1.5 rounded transition shadow-xs shrink-0">Fetch & Analyze</button>
                    </div>
                </div>

                <!-- Library Storage Access (Icon Button with Tooltip & Live Badge) -->
                <button id="masterTabLibrary" onclick="toggleLibraryMode()" class="relative p-2 rounded-lg bg-slate-50 hover:bg-slate-100 dark:bg-slate-800 dark:hover:bg-slate-750 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-slate-700 shadow-2xs transition cursor-pointer shrink-0 flex items-center justify-center" title="Library — Saved Appraisals" aria-label="Library">
                    <span class="text-base leading-none">📚</span>
                    <span id="userLibraryBadge" class="hidden absolute -top-1 -right-1 flex h-4 min-w-4 px-1 items-center justify-center rounded-full bg-emerald-600 text-white text-[10px] font-bold leading-none shadow-xs">0</span>
                </button>`;

// Normalize line endings for replacement
const normalize = str => str.replace(/\\r\\n/g, '\\n');

let normS = normalize(s);
let normOldTabs = normalize(oldTabs);
let normNewTabs = normalize(newTabs);
let normOldInput = normalize(oldInputEnd);
let normNewInput = normalize(newInputEnd);

if (!normS.includes(normOldTabs)) {
    console.error('Could not find oldTabs in server.py');
    process.exit(1);
}
if (!normS.includes(normOldInput)) {
    console.error('Could not find oldInputEnd in server.py');
    process.exit(1);
}

normS = normS.replace(normOldTabs, normNewTabs);
normS = normS.replace(normOldInput, normNewInput);

// Also add toggleLibraryMode function in script
const oldSwitchMasterMode = `            function switchMasterMode(mode) {
                window.ResearchAppState.currentMasterMode = mode;`;

const newSwitchMasterMode = `            function toggleLibraryMode() {
                if (window.ResearchAppState && window.ResearchAppState.currentMasterMode === 'library') {
                    // If already in library, toggle back to previous mode or appraisal
                    switchMasterMode(window.ResearchAppState.previousMasterMode || 'appraisal');
                } else {
                    switchMasterMode('library');
                }
            }

            function switchMasterMode(mode) {
                if (window.ResearchAppState && window.ResearchAppState.currentMasterMode !== 'library') {
                    window.ResearchAppState.previousMasterMode = window.ResearchAppState.currentMasterMode;
                }
                window.ResearchAppState.currentMasterMode = mode;`;

normS = normS.replace(normalize(oldSwitchMasterMode), normalize(newSwitchMasterMode));

// Update button styles in switchMasterMode
const oldTabLibReset = `if (tabLibraryBtn) tabLibraryBtn.className = "px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium";`;
const newTabLibReset = `if (tabLibraryBtn) tabLibraryBtn.className = "relative p-2 rounded-lg bg-slate-50 hover:bg-slate-100 dark:bg-slate-800 dark:hover:bg-slate-750 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-slate-700 shadow-2xs transition cursor-pointer shrink-0 flex items-center justify-center";`;

const oldTabLibActive = `if (tabLibraryBtn) tabLibraryBtn.className = "px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";`;
const newTabLibActive = `if (tabLibraryBtn) tabLibraryBtn.className = "relative p-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border-2 border-emerald-500 shadow-2xs font-bold transition cursor-pointer shrink-0 flex items-center justify-center ring-2 ring-emerald-500/20";`;

normS = normS.replace(normalize(oldTabLibReset), normalize(newTabLibReset));
normS = normS.replace(normalize(oldTabLibActive), normalize(newTabLibActive));

fs.writeFileSync('src/api/server.py', normS, 'utf8');
console.log('Successfully updated Library button layout in server.py!');

