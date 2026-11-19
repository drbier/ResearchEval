with open('src/api/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Enhance #outputMarkdown CSS for h3, strong, and lists (since Tailwind Preflight resets ul/li without typography plugin)
old_h3_css = """            #outputMarkdown h3 {
                font-size: 0.95rem !important; /* slightly larger than 0.875rem body text */
                font-weight: 700 !important;
                color: #0f172a !important; /* slate-900 bold */
                margin-top: 1.1rem !important;
                margin-bottom: 0.35rem !important;
                letter-spacing: -0.005em !important;
            }"""

new_h3_css = """            #outputMarkdown h3 {
                font-size: 1.02rem !important; /* noticeably larger than 0.875rem body text */
                font-weight: 700 !important;
                color: #0f172a !important; /* slate-900 bold */
                margin-top: 1.15rem !important;
                margin-bottom: 0.4rem !important;
                letter-spacing: -0.005em !important;
            }
            #outputMarkdown p {
                margin-bottom: 0.6rem !important;
            }
            #outputMarkdown ul {
                list-style-type: disc !important;
                padding-left: 1.35rem !important;
                margin-top: 0.35rem !important;
                margin-bottom: 0.65rem !important;
            }
            #outputMarkdown ul ul {
                list-style-type: circle !important;
                margin-top: 0.25rem !important;
                margin-bottom: 0.25rem !important;
            }
            #outputMarkdown ol {
                list-style-type: decimal !important;
                padding-left: 1.35rem !important;
                margin-top: 0.35rem !important;
                margin-bottom: 0.65rem !important;
            }
            #outputMarkdown li {
                margin-bottom: 0.35rem !important;
            }
            #outputMarkdown strong {
                font-weight: 700 !important;
                color: #0f172a !important;
            }"""

assert old_h3_css in content, "old_h3_css not found"
content = content.replace(old_h3_css, new_h3_css, 1)

# 2. Update subheading & inline-label normalization in renderAppraisalResults
old_subhead_logic = """                        // Elevate clinical subheadings (e.g. 'Key Metric Definitions:', 'Primary Endpoint:') to ### markdown headers
                        if (trimmedLine.endsWith(':') && !trimmedLine.startsWith('#')) {
                            const rawNoColon = trimmedLine.slice(0, -1).trim();
                            const lowerNoColon = rawNoColon.toLowerCase();
                            let isSubhead = SUBHEAD_KEYWORDS.has(lowerNoColon);

                            if (!isSubhead && /^[A-Z][A-Za-z\\s&/\\-_–]{1,45}$/.test(rawNoColon)) {
                                const words = rawNoColon.split(/\\s+/);
                                if (words.length <= 5) {
                                    const titleCount = words.filter(w => w[0] === w[0].toUpperCase() || ['and', 'or', 'in', '&', 'of', 'for', 'to', 'the', 'with', 'by'].includes(w.toLowerCase())).length;
                                    if (titleCount === words.length) {
                                        isSubhead = true;
                                    }
                                }
                            }

                            if (isSubhead) {
                                contentLines[i] = '### ' + rawNoColon + ':';
                            }
                        }"""

new_subhead_logic = """                        // Elevate standalone clinical subheadings (including bulleted ones like '* Secondary Hematologic Endpoints:') to ### markdown headers
                        const bulletPrefixMatch = trimmedLine.match(/^([*\\-]\\s+)?(.+)$/);
                        const lineBody = bulletPrefixMatch ? bulletPrefixMatch[2].trim() : trimmedLine;
                        const cleanLineBody = lineBody.replace(/^\\*\\*|\\*\\*$/g, '').trim();

                        if (cleanLineBody.endsWith(':') && !trimmedLine.startsWith('#')) {
                            const rawNoColon = cleanLineBody.slice(0, -1).trim();
                            const lowerNoColon = rawNoColon.toLowerCase();
                            let isSubhead = SUBHEAD_KEYWORDS.has(lowerNoColon);

                            if (!isSubhead && /^[A-Z][A-Za-z0-9\\s&/\\-_–()]{1,75}$/.test(rawNoColon)) {
                                const words = rawNoColon.split(/\\s+/);
                                if (words.length <= 9) {
                                    const minorWords = new Set(['and', 'or', 'in', '&', 'of', 'for', 'to', 'the', 'with', 'by', 'on', 'at', 'from', 'vs', 'vs.']);
                                    const titleCount = words.filter(w => /^[A-Z(]/.test(w) || minorWords.has(w.toLowerCase())).length;
                                    if (titleCount === words.length) {
                                        isSubhead = true;
                                    }
                                }
                            }

                            if (isSubhead) {
                                contentLines[i] = '### ' + rawNoColon + ':';
                                continue;
                            }
                        }

                        // Bold inline lead-in labels (e.g. '* Planned Sample Size and Enrollment Target: 32 patients...' or '  - Hemoglobin: ...')
                        if (!trimmedLine.startsWith('#')) {
                            const inlineMatch = contentLines[i].match(/^(\\s*(?:[*\\-]\\s+)?)([A-Z][^:\\n]{1,68}):(\\s+.+)$/);
                            if (inlineMatch) {
                                const indentBullet = inlineMatch[1] || '';
                                const labelPart = inlineMatch[2].trim();
                                const restPart = inlineMatch[3];
                                // Avoid bolding if already bolded or if it looks like a URL/citation/sentence
                                if (!labelPart.startsWith('**') && !/^https?$/i.test(labelPart) && !labelPart.includes('[')) {
                                    contentLines[i] = indentBullet + '**' + labelPart + ':**' + restPart;
                                }
                            }
                        }"""

assert old_subhead_logic in content, "old_subhead_logic not found"
content = content.replace(old_subhead_logic, new_subhead_logic, 1)

with open('src/api/server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Subheading elevation, inline label bolding, and list/h3 CSS updated in server.py!")
