with open('src/api/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove the badge element from the library button HTML
old_btn = '''                <!-- Library Storage Access (Icon Button with Tooltip & Live Badge) -->
                <button id="masterTabLibrary" onclick="toggleLibraryMode()" class="relative p-2 rounded-lg bg-slate-50 hover:bg-slate-100 dark:bg-slate-800 dark:hover:bg-slate-750 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-slate-700 shadow-2xs transition cursor-pointer shrink-0 flex items-center justify-center" title="Library — Saved Appraisals" aria-label="Library">
                    <span class="text-base leading-none">📚</span>
                    <span id="userLibraryBadge" class="hidden absolute -top-1 -right-1 flex h-4 min-w-4 px-1 items-center justify-center rounded-full bg-emerald-600 text-white text-[10px] font-bold leading-none shadow-xs">0</span>
                </button>'''

new_btn = '''                <!-- Library Storage Access (Icon Button with Tooltip) -->
                <button id="masterTabLibrary" onclick="toggleLibraryMode()" class="relative p-2 rounded-lg bg-slate-50 hover:bg-slate-100 dark:bg-slate-800 dark:hover:bg-slate-750 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-slate-700 shadow-2xs transition cursor-pointer shrink-0 flex items-center justify-center" title="Library — Saved Appraisals" aria-label="Library">
                    <span class="text-base leading-none">📚</span>
                </button>'''

assert old_btn in content, "old_btn not found"
content = content.replace(old_btn, new_btn, 1)

# 2. Make updateUserLibraryBadge a no-op function to avoid any dangling callers or unnecessary DB fetches
old_func = '''            // Update User Library Counter Badge in Header
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
            }'''

new_func = '''            // Library badge removed to eliminate distraction
            function updateUserLibraryBadge() {
                // No-op
            }'''

assert old_func in content, "old_func not found"
content = content.replace(old_func, new_func, 1)

with open('src/api/server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Removed library indicator badge!")

