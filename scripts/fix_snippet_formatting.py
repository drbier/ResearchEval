with open('src/api/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add formatManuscriptSnippet helper function right before inspectAnchor
helper_func = """            // Format manuscript snippet text so only genuine paragraph breaks show while intra-paragraph lines flow naturally
            function formatManuscriptSnippet(rawText) {
                if (!rawText) return '';
                const normalized = String(rawText).replace(/\\r\\n/g, '\\n').replace(/\\r/g, '\\n');
                const paragraphs = normalized.split(/\\n\\s*\\n+/);
                const cleanedParas = [];
                for (let i = 0; i < paragraphs.length; i++) {
                    let p = paragraphs[i];
                    // Join words hyphenated across a line-break e.g. "random-\\nized" -> "randomized"
                    p = p.replace(/(\\w+)-\\n(\\w+)/g, '$1$2');
                    // Replace remaining single intra-paragraph line breaks with a single space
                    p = p.replace(/\\s*\\n\\s*/g, ' ');
                    // Collapse multiple horizontal whitespace sequences
                    p = p.replace(/[ \\t]+/g, ' ').trim();
                    if (p.length > 0) {
                        cleanedParas.push(p);
                    }
                }
                return cleanedParas.join('\\n\\n');
            }

            function inspectAnchor(encodedAnchor) {"""

assert "function inspectAnchor(encodedAnchor) {" in content, "inspectAnchor not found"
content = content.replace("function inspectAnchor(encodedAnchor) {", helper_func, 1)

# 2. Update snippetText and popupTranscriptText assignments in inspectAnchor
old_inspect_assign = """                    if (snippetText) {
                        snippetText.innerText = meta.text || '';
                    }"""

new_inspect_assign = """                    if (snippetText) {
                        snippetText.innerText = formatManuscriptSnippet(meta.text || '');
                    }"""

assert old_inspect_assign in content, "old_inspect_assign not found"
content = content.replace(old_inspect_assign, new_inspect_assign, 1)

old_pinned_assign = """                        if (transcriptBox && transcriptText && meta.text) {
                            transcriptText.innerText = meta.text;
                            if (pageInfo) pageInfo.innerText = meta.page ? `Page ${meta.page}` : '';
                            transcriptBox.classList.remove('hidden');
                        }"""

new_pinned_assign = """                        if (transcriptBox && transcriptText && meta.text) {
                            transcriptText.innerText = formatManuscriptSnippet(meta.text);
                            if (pageInfo) pageInfo.innerText = meta.page ? `Page ${meta.page}` : '';
                            transcriptBox.classList.remove('hidden');
                        }"""

assert old_pinned_assign in content, "old_pinned_assign not found"
content = content.replace(old_pinned_assign, new_pinned_assign, 1)

# 3. Update popup transcript in openPopup (hover/click popup on hitbox)
old_popup_assign = """                    if (transcriptBox && transcriptText && currentMeta.text) {
                        transcriptText.innerText = currentMeta.text;
                        if (pageInfo) pageInfo.innerText = currentMeta.page ? `Page ${currentMeta.page}` : '';
                        transcriptBox.classList.remove('hidden');
                    }"""

new_popup_assign = """                    if (transcriptBox && transcriptText && currentMeta.text) {
                        transcriptText.innerText = formatManuscriptSnippet(currentMeta.text);
                        if (pageInfo) pageInfo.innerText = currentMeta.page ? `Page ${currentMeta.page}` : '';
                        transcriptBox.classList.remove('hidden');
                    }"""

assert old_popup_assign in content, "old_popup_assign not found"
content = content.replace(old_popup_assign, new_popup_assign, 1)

with open('src/api/server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: formatManuscriptSnippet added and applied to Source Evidence Inspector & Popups!")
