with open('src/api/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Replace the input element with a textarea in the Ask tab
old_input_html = '''                                <!-- Question Input Box -->
                                <div class="flex-shrink-0 flex gap-2 pt-1">
                                    <input type="text" id="askQuestionInput" onkeydown="if(event.key==='Enter') executeAskQuery();" placeholder="Ask a question about this paper (e.g. 'What was the blinding method?')..." class="flex-1 text-xs text-slate-800 dark:text-slate-100 bg-white dark:bg-slate-900 px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-700 focus:outline-none focus:ring-1 focus:ring-sky-500 shadow-2xs"/>
                                    <button id="askSubmitBtn" onclick="executeAskQuery()" class="btn-primary-accent px-4 py-2 text-white font-semibold text-xs rounded-lg transition shadow-2xs flex items-center gap-1.5 cursor-pointer shrink-0">
                                        <span>Send</span> <span>➤</span>
                                    </button>
                                </div>'''

new_input_html = '''                                <!-- Question Input Box (Expandable Textarea with Auto-grow & Enter/Ctrl-Enter Support) -->
                                <div class="flex-shrink-0 flex items-end gap-2 pt-1">
                                    <textarea id="askQuestionInput" 
                                              rows="1" 
                                              oninput="autoResizeAskInput(this)" 
                                              onkeydown="handleAskInputKeydown(event)" 
                                              placeholder="Ask a question about this paper... (Press Enter to send, Ctrl+Enter or Shift+Enter for new line)" 
                                              class="flex-1 text-xs text-slate-800 dark:text-slate-100 bg-white dark:bg-slate-900 px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-700 focus:outline-none focus:ring-1 focus:ring-sky-500 shadow-2xs resize-none overflow-y-auto leading-relaxed" 
                                              style="min-height: 38px; max-height: 200px;"></textarea>
                                    <button id="askSubmitBtn" onclick="executeAskQuery()" class="btn-primary-accent px-4 py-2 text-white font-semibold text-xs rounded-lg transition shadow-2xs flex items-center gap-1.5 cursor-pointer shrink-0 h-[38px]">
                                        <span>Send</span> <span>➤</span>
                                    </button>
                                </div>'''

# 2. Add helper functions for textarea auto-resizing and keyboard handling
helper_funcs = '''            // Auto-resize Ask Question Textarea
            function autoResizeAskInput(el) {
                if (!el) return;
                el.style.height = 'auto';
                const maxHeight = 200;
                const newHeight = Math.min(el.scrollHeight, maxHeight);
                el.style.height = (newHeight > 38 ? newHeight : 38) + 'px';
                el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden';
            }

            // Keyboard handler: Enter sends, Ctrl+Enter or Shift+Enter inserts newline
            function handleAskInputKeydown(e) {
                if (e.key === 'Enter') {
                    if (e.ctrlKey || e.metaKey || e.shiftKey) {
                        // Allow default newline insertion, then resize
                        setTimeout(() => autoResizeAskInput(e.target), 0);
                    } else {
                        // Enter alone sends query
                        e.preventDefault();
                        executeAskQuery();
                    }
                }
            }
'''

assert old_input_html in content, "old_input_html not found"
content = content.replace(old_input_html, new_input_html, 1)

# In resetAskChat and executeAskQuery, reset textarea height back to 38px
content = content.replace(
    "if (inp) inp.value = '';",
    "if (inp) { inp.value = ''; inp.style.height = '38px'; }"
)
content = content.replace(
    "inp.value = '';\n                inp.disabled = true;",
    "inp.value = '';\n                inp.style.height = '38px';\n                inp.disabled = true;"
)

# Insert the helper functions right before resetAskChat()
target_reset_pos = "function resetAskChat() {"
assert target_reset_pos in content, "resetAskChat not found"
content = content.replace(target_reset_pos, helper_funcs + "\n            " + target_reset_pos, 1)

with open('src/api/server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: server.py updated with expandable Ask textarea!")

