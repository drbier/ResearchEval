with open('src/api/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update CSS in server.py for h3 (subheadings)
old_css = '''            #outputMarkdown h3 {
                font-size: 1.0rem !important;
                font-weight: 700 !important;
                color: #1e293b !important; /* slate-800 */
                margin-top: 1rem !important;
                margin-bottom: 0.35rem !important;
            }'''

new_css = '''            #outputMarkdown h3 {
                font-size: 0.95rem !important; /* slightly larger than 0.875rem body text */
                font-weight: 700 !important;
                color: #0f172a !important; /* slate-900 bold */
                margin-top: 1.1rem !important;
                margin-bottom: 0.35rem !important;
                letter-spacing: -0.005em !important;
            }'''

assert old_css in content, "old_css not found"
content = content.replace(old_css, new_css, 1)

# Dark mode styling for h3
old_dark_h3 = '''            html.dark #outputMarkdown h3 {
                color: #cbd5e1 !important;
            }'''

new_dark_h3 = '''            html.dark #outputMarkdown h3 {
                color: #f1f5f9 !important; /* slate-100 high-contrast bold */
            }'''

assert old_dark_h3 in content, "old_dark_h3 not found"
content = content.replace(old_dark_h3, new_dark_h3, 1)

# 2. Update renderAppraisalResults preprocessing loop to convert subheadings ending in colon to ### Subheading:
old_normalization = '''                    for (let i = 0; i < contentLines.length; i++) {
                        let trimmedLine = contentLines[i].trim();
                        if (/^(?:#*\\s*)?\\*\\*?Clinical Bottom Line\\*\\*?:?$/i.test(trimmedLine) || trimmedLine.toLowerCase() === 'clinical bottom line') {
                            contentLines[i] = '## Clinical Bottom Line';
                        }
                    }'''

new_normalization = '''                    const SUBHEAD_KEYWORDS = new Set([
                        'key metric definitions', 'primary endpoint', 'primary endpoints', 'secondary endpoint',
                        'secondary endpoints', 'secondary endpoints & biomarkers', 'safety and harms',
                        'safety & harms', 'harms reporting standards', 'subgroup analyses', 'subgroup analysis',
                        'exploratory endpoints', 'methodological rationale', 'study design & setting',
                        'study design and setting', 'inclusion and exclusion criteria', 'baseline characteristics',
                        'statistical methodology', 'efficacy outcomes', 'adverse events', 'risk of bias'
                    ]);

                    for (let i = 0; i < contentLines.length; i++) {
                        let trimmedLine = contentLines[i].trim();
                        if (/^(?:#*\\s*)?\\*\\*?Clinical Bottom Line\\*\\*?:?$/i.test(trimmedLine) || trimmedLine.toLowerCase() === 'clinical bottom line') {
                            contentLines[i] = '## Clinical Bottom Line';
                            continue;
                        }

                        // Elevate clinical subheadings (e.g. 'Key Metric Definitions:', 'Primary Endpoint:') to ### markdown headers
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
                        }
                    }'''

assert old_normalization in content, "old_normalization not found"
content = content.replace(old_normalization, new_normalization, 1)

with open('src/api/server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: server.py updated with formatted subheadings!")
