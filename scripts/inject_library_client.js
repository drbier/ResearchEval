const fs = require('fs');

let s = fs.readFileSync('src/api/server.py', 'utf8');

const target = "console.warn('[Library] Auto-save skipped:', err);\r\n                }\r\n            }";
if (!s.includes(target)) {
    console.error('Target not found!');
    process.exit(1);
}

const newCode = `

            // User Library State Cache
            let cachedUserLibraryItems = [];

            // Update User Library Counter Badge in Header
            async function updateUserLibraryBadge() {
                try {
                    const badge = document.getElementById('userLibraryBadge');
                    if (!badge) return;
                    if (!currentUser || !currentUser.uid) {
                        badge.classList.add('hidden');
                        badge.innerText = '0';
                        return;
                    }
                    if (fbDb) {
                        const snap = await fbDb.collection('users').doc(currentUser.uid).collection('appraisals').get();
                        const count = snap.size;
                        if (count > 0) {
                            badge.innerText = count;
                            badge.classList.remove('hidden');
                        } else {
                            badge.classList.add('hidden');
                        }
                    } else {
                        const res = await fetch('/user-appraisals?user_uid=' + encodeURIComponent(currentUser.uid));
                        if (res.ok) {
                            const data = await res.json();
                            const count = (data && data.items) ? data.items.length : 0;
                            if (count > 0) {
                                badge.innerText = count;
                                badge.classList.remove('hidden');
                            } else {
                                badge.classList.add('hidden');
                            }
                        }
                    }
                } catch (err) {
                    console.warn('[LibraryBadge] Count error:', err);
                }
            }

            // Refresh & Render User Library Feed
            async function refreshUserLibraryUI() {
                const feed = document.getElementById('libraryListFeed');
                if (!feed) return;

                if (!currentUser) {
                    feed.innerHTML = [
                        '<div class="text-center py-12 bg-white dark:bg-slate-800/50 rounded-xl border border-dashed border-slate-300 dark:border-slate-700">',
                        '  <span class="text-3xl">🔒</span>',
                        '  <h4 class="text-sm font-semibold text-slate-800 dark:text-slate-200 mt-2">Sign In Required</h4>',
                        '  <p class="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-sm mx-auto">',
                        '    Sign in to access your personal library of saved paper analyses, truth audits, and coordinate anchor maps.',
                        '  </p>',
                        '  <button onclick="openAuthModal()" class="mt-4 px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold shadow-xs transition cursor-pointer">',
                        '    Sign In / Register',
                        '  </button>',
                        '</div>'
                    ].join('');
                    return;
                }

                feed.innerHTML = [
                    '<div class="flex items-center justify-center py-12 text-slate-400 dark:text-slate-500 text-xs italic gap-2">',
                    '  <span class="inline-block animate-spin">⏳</span> Fetching your library records...',
                    '</div>'
                ].join('');

                try {
                    let items = [];
                    // Prefer Firestore client query first for live private library pointers
                    if (fbDb) {
                        try {
                            const snap = await fbDb.collection('users').doc(currentUser.uid).collection('appraisals').orderBy('updated_at', 'desc').get();
                            snap.forEach(doc => {
                                const d = doc.data();
                                items.push({
                                    paper_id: doc.id,
                                    title: d.title || doc.id,
                                    filename: d.filename || '',
                                    framework_name: d.framework_name || 'Clinical Study',
                                    anchor_hash: d.anchor_hash || '',
                                    pdf_hash: d.pdf_hash || '',
                                    global_cache_key: d.global_cache_key || '',
                                    is_public_oa: d.is_public_oa !== false,
                                    therapeutic_lens: d.therapeutic_lens || 'integrative',
                                    updated_at: d.updated_at ? (d.updated_at.toDate ? d.updated_at.toDate().toISOString() : d.updated_at) : new Date().toISOString()
                                });
                            });
                        } catch (fsErr) {
                            console.warn('[Library] Firestore direct query failed, falling back to server endpoint:', fsErr);
                        }
                    }

                    // Fallback to server endpoint if firestore returned empty or failed
                    if (items.length === 0) {
                        const res = await fetch('/user-appraisals?user_uid=' + encodeURIComponent(currentUser.uid));
                        if (res.ok) {
                            const payload = await res.json();
                            items = payload.items || [];
                        }
                    }

                    cachedUserLibraryItems = items;
                    updateUserLibraryBadge();
                    renderLibraryListCards(items);
                } catch (err) {
                    console.error('[Library] Failed to load library:', err);
                    feed.innerHTML = '<div class="text-center py-8 text-rose-500 dark:text-rose-400 text-xs">Error loading library: ' + escapeHtml(err.message) + '</div>';
                }
            }

            // Render Library Cards
            function renderLibraryListCards(items) {
                const feed = document.getElementById('libraryListFeed');
                if (!feed) return;

                if (!items || items.length === 0) {
                    feed.innerHTML = [
                        '<div class="text-center py-12 bg-white dark:bg-slate-800/40 rounded-xl border border-dashed border-slate-200 dark:border-slate-800">',
                        '  <span class="text-3xl">📚</span>',
                        '  <h4 class="text-sm font-semibold text-slate-700 dark:text-slate-300 mt-2">No Saved Appraisals Yet</h4>',
                        '  <p class="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-sm mx-auto">',
                        '    Appraisals are automatically preserved in your private library as you run precision searches or upload manuscripts.',
                        '  </p>',
                        '  <button onclick="switchMasterMode(\\'finder\\')" class="mt-4 px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold shadow-xs transition cursor-pointer">',
                        '    🔍 Find Literature to Appraise',
                        '  </button>',
                        '</div>'
                    ].join('');
                    return;
                }

                feed.innerHTML = items.map(item => {
                    const dateStr = item.updated_at ? new Date(item.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '';
                    const timeStr = item.updated_at ? new Date(item.updated_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '';
                    const isOA = item.is_public_oa !== false;
                    const oaBadge = isOA 
                        ? '<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800">Open Access</span>'
                        : '<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border border-amber-300 dark:border-amber-800">Quarantine PDF</span>';

                    const lensBadge = item.therapeutic_lens 
                        ? '<span class="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 capitalize">' + escapeHtml(item.therapeutic_lens) + ' Lens</span>' 
                        : '';

                    return [
                        '<div class="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-emerald-500 dark:hover:border-emerald-500/60 transition shadow-2xs group flex flex-col md:flex-row md:items-center justify-between gap-3">',
                        '  <div class="flex-1 min-w-0">',
                        '    <div class="flex flex-wrap items-center gap-2 mb-1.5">',
                        '      <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-sky-100 dark:bg-sky-950/60 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800">',
                        '        ' + escapeHtml(item.framework_name || 'Clinical Analysis'),
                        '      </span>',
                        '      ' + oaBadge,
                        '      ' + lensBadge,
                        '      <span class="text-[11px] text-slate-400 dark:text-slate-500">' + dateStr + ' ' + timeStr + '</span>',
                        '    </div>',
                        '    <h4 class="text-sm font-semibold text-slate-900 dark:text-slate-100 group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition truncate cursor-pointer" onclick="loadAppraisalFromLibrary(\\'' + escapeHtml(item.paper_id) + '\\', \\'' + escapeHtml(item.global_cache_key || '') + '\\')" title="' + escapeHtml(item.title || item.paper_id) + '">',
                        '      ' + escapeHtml(item.title || item.paper_id),
                        '    </h4>',
                        '    <p class="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">',
                        '      ' + escapeHtml(item.filename || item.paper_id),
                        '    </p>',
                        '  </div>',
                        '  <div class="flex items-center gap-2 shrink-0">',
                        '    <button onclick="loadAppraisalFromLibrary(\\'' + escapeHtml(item.paper_id) + '\\', \\'' + escapeHtml(item.global_cache_key || '') + '\\')" class="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold transition shadow-2xs flex items-center gap-1.5 cursor-pointer">',
                        '      <span>⚡</span> Open Appraisal',
                        '    </button>',
                        '  </div>',
                        '</div>'
                    ].join('');
                }).join('');
            }

            // Filter Library List by Search Query
            function filterLibraryList() {
                const input = document.getElementById('libraryFilterInput');
                const q = (input ? input.value : '').toLowerCase().trim();
                if (!q) {
                    renderLibraryListCards(cachedUserLibraryItems);
                    return;
                }
                const filtered = (cachedUserLibraryItems || []).filter(item => {
                    const t = (item.title || '').toLowerCase();
                    const pid = (item.paper_id || '').toLowerCase();
                    const fn = (item.filename || '').toLowerCase();
                    const fw = (item.framework_name || '').toLowerCase();
                    return t.includes(q) || pid.includes(q) || fn.includes(q) || fw.includes(q);
                });
                renderLibraryListCards(filtered);
            }

            // Load Appraisal from Library without LLM Inference
            async function loadAppraisalFromLibrary(paperId, globalCacheKey) {
                if (!currentUser) {
                    openAuthModal();
                    return;
                }

                const statusBox = document.getElementById('statusBox');
                const statusText = document.getElementById('statusText');
                const spinner = document.getElementById('spinner');
                const statusIcon = document.getElementById('statusIcon');

                switchMasterMode('appraisal');
                if (statusBox) statusBox.classList.remove('hidden');
                if (statusText) statusText.innerText = 'Loading cached appraisal & coordinate anchors (0 token usage)...';
                if (spinner) spinner.classList.remove('hidden');
                if (statusIcon) statusIcon.innerText = '📚';

                try {
                    const params = new URLSearchParams({
                        user_uid: currentUser.uid,
                        global_cache_key: globalCacheKey || ''
                    });
                    const res = await fetch('/appraisal-by-id/' + encodeURIComponent(paperId) + '?' + params.toString());
                    if (!res.ok) {
                        const errData = await res.json().catch(() => ({}));
                        throw new Error(errData.detail || ('Server returned ' + res.status));
                    }

                    const data = await res.json();
                    currentFilename = data.filename || paperId;

                    // Rehydrate anchor index
                    anchorIndex = data.anchor_index || {};

                    // Render appraisal directly
                    renderAppraisalResults(data);

                    if (statusBox) statusBox.classList.add('hidden');
                } catch (err) {
                    console.error('[Library] Error opening appraisal:', err);
                    if (statusBox) {
                        statusText.innerText = 'Failed to load appraisal: ' + err.message;
                        if (spinner) spinner.classList.add('hidden');
                        if (statusIcon) statusIcon.innerText = '⚠️';
                    }
                    alert('Could not load appraisal: ' + err.message);
                }
            }`;

// Also wire updateUserLibraryBadge in handleAuthStateChanged
const authTarget = "isApproved = false;\r\n                    isAdmin = false;";
const authReplacement = "isApproved = false;\r\n                    isAdmin = false;\r\n                    updateUserLibraryBadge();";

s = s.replace(target, target + newCode);
if (s.includes(authTarget)) {
    s = s.replace(authTarget, authReplacement);
}

fs.writeFileSync('src/api/server.py', s, 'utf8');
console.log('Successfully injected library functions into server.py!');

