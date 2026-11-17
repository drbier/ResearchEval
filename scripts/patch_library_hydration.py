import os
import re

server_path = 'src/api/server.py'
with open(server_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update SaveAppraisalRequest to include total_pages
old_req = '''class SaveAppraisalRequest(BaseModel):
    user_uid: str
    paper_id: str
    title: str
    filename: str
    appraisal_markdown: str'''

new_req = '''class SaveAppraisalRequest(BaseModel):
    user_uid: str
    paper_id: str
    title: str
    filename: str
    appraisal_markdown: str
    total_pages: Optional[int] = None'''

assert old_req in content, "old_req not found"
content = content.replace(old_req, new_req, 1)

# 2. Update save_appraisal_endpoint payloads
old_payload = '''    appraisal_payload = {
        "paper_id": req.paper_id,
        "title": req.title,
        "filename": req.filename,
        "final_markdown": req.appraisal_markdown,
        "triage": req.triage or {},
        "rule_evaluations": req.rule_evaluations or [],
        "active_rules_detail": req.active_rules_detail or [],
        "thought_output": req.thought_output or "",
        "anchor_hash": req.anchor_hash or "",
        "is_public_oa": bool(req.is_public_oa),
        "pdf_hash": req.pdf_hash or "",
        "updated_at": time.time()
    }'''

new_payload = '''    appraisal_payload = {
        "paper_id": req.paper_id,
        "title": req.title,
        "filename": req.filename,
        "final_markdown": req.appraisal_markdown,
        "appraisal_markdown": req.appraisal_markdown,
        "total_pages": req.total_pages,
        "triage": req.triage or {},
        "rule_evaluations": req.rule_evaluations or [],
        "active_rules_detail": req.active_rules_detail or [],
        "thought_output": req.thought_output or "",
        "anchor_hash": req.anchor_hash or "",
        "is_public_oa": bool(req.is_public_oa),
        "pdf_hash": req.pdf_hash or "",
        "updated_at": time.time()
    }'''

assert old_payload in content, "old_payload not found"
content = content.replace(old_payload, new_payload, 1)

old_user_rec = '''    user_record = {
        "paper_id": req.paper_id,
        "title": req.title,
        "filename": req.filename,
        "therapeutic_lens": req.therapeutic_lens,
        "commentary": req.commentary,
        "qc_audit": req.qc_audit,
        "global_cache_key": tier_b_key if req.is_public_oa else "",
        "anchor_hash": req.anchor_hash,
        "pdf_hash": req.pdf_hash,
        "is_public_oa": bool(req.is_public_oa),
        "appraisal_markdown": req.appraisal_markdown,
        "triage": req.triage or {},
        "updated_at": time.time()
    }'''

new_user_rec = '''    user_record = {
        "paper_id": req.paper_id,
        "title": req.title,
        "filename": req.filename,
        "therapeutic_lens": req.therapeutic_lens,
        "commentary": req.commentary,
        "qc_audit": req.qc_audit,
        "global_cache_key": tier_b_key if req.is_public_oa else "",
        "anchor_hash": req.anchor_hash,
        "pdf_hash": req.pdf_hash,
        "is_public_oa": bool(req.is_public_oa),
        "appraisal_markdown": req.appraisal_markdown,
        "final_markdown": req.appraisal_markdown,
        "total_pages": req.total_pages,
        "triage": req.triage or {},
        "updated_at": time.time()
    }'''

assert old_user_rec in content, "old_user_rec not found"
content = content.replace(old_user_rec, new_user_rec, 1)

# 3. Update get_appraisal_by_id_endpoint to normalize keys and derive total_pages
old_get_rec = '''            rec["anchor_index"] = anchors
            rec["status"] = "success"
            return rec'''

new_get_rec = '''            rec["anchor_index"] = anchors
            rec["final_markdown"] = rec.get("final_markdown") or rec.get("appraisal_markdown", "")
            rec["appraisal_markdown"] = rec["final_markdown"]
            if not rec.get("total_pages") and anchors:
                rec["total_pages"] = max((m.get("page", 1) for m in anchors.values() if isinstance(m, dict)), default=1)
            rec["status"] = "success"
            return rec'''

assert old_get_rec in content, "old_get_rec not found"
content = content.replace(old_get_rec, new_get_rec, 1)

old_global_rec = '''        cached_global["anchor_index"] = anchors
        cached_global["status"] = "success"
        cached_global["from_global_cache"] = True
        return cached_global'''

new_global_rec = '''        cached_global["anchor_index"] = anchors
        cached_global["final_markdown"] = cached_global.get("final_markdown") or cached_global.get("appraisal_markdown", "")
        cached_global["appraisal_markdown"] = cached_global["final_markdown"]
        if not cached_global.get("total_pages") and anchors:
            cached_global["total_pages"] = max((m.get("page", 1) for m in anchors.values() if isinstance(m, dict)), default=1)
        cached_global["status"] = "success"
        cached_global["from_global_cache"] = True
        return cached_global'''

assert old_global_rec in content, "old_global_rec not found"
content = content.replace(old_global_rec, new_global_rec, 1)

# 4. In atomic_write_file, ensure permissions allow group reading (0o664 / 0o644)
old_atomic = '''    temp_fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_fact_")
    try:
        with os.fdopen(temp_fd, "wb") as f:
            f.write(data)
        os.replace(temp_path, target_path)'''

new_atomic = '''    temp_fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_fact_")
    try:
        with os.fdopen(temp_fd, "wb") as f:
            f.write(data)
        try:
            os.chmod(temp_path, 0o664)
        except Exception:
            pass
        os.replace(temp_path, target_path)'''

assert old_atomic in content, "old_atomic not found"
content = content.replace(old_atomic, new_atomic, 1)

# 5. In renderAppraisalResults: handle markdown content & total_pages fallback
old_content_line = '''                let content = data.final_markdown || data.raw_output || '';'''
new_content_line = '''                let content = data.final_markdown || data.appraisal_markdown || data.raw_output || '';'''

assert old_content_line in content, "old_content_line not found"
content = content.replace(old_content_line, new_content_line, 1)

old_render_pages = '''                if (data.total_pages) {
                    renderFullDocumentPages(currentFilename, data.total_pages);
                }'''

new_render_pages = '''                const totalPages = data.total_pages || (data.anchor_index ? Math.max(...Object.values(data.anchor_index).map(a => a.page || 1), 1) : 0);
                if (totalPages > 0 && currentFilename) {
                    renderFullDocumentPages(currentFilename, totalPages);
                } else if (currentFilename) {
                    fetch(`/api/pdf-manifest?filename=${encodeURIComponent(currentFilename)}`)
                        .then(r => r.json())
                        .then(manifest => {
                            if (manifest && manifest.total_pages) {
                                renderFullDocumentPages(manifest.filename, manifest.total_pages, manifest.pages);
                            }
                        }).catch(e => console.warn('Manifest load notice:', e));
                }'''

assert old_render_pages in content, "old_render_pages not found"
content = content.replace(old_render_pages, new_render_pages, 1)

# 6. In autoSaveAppraisalToLibrary: save total_pages and fallback
old_auto_save_payload = '''                    const payload = {
                        user_uid: currentUser.uid,
                        paper_id: paperId,
                        title: title,
                        filename: data.filename || currentFilename || '',
                        appraisal_markdown: markdownContent || '','''

new_auto_save_payload = '''                    const totalPages = data.total_pages || (data.anchor_index ? Math.max(...Object.values(data.anchor_index).map(a => a.page || 1), 1) : 1);
                    const payload = {
                        user_uid: currentUser.uid,
                        paper_id: paperId,
                        title: title,
                        filename: data.filename || currentFilename || '',
                        appraisal_markdown: markdownContent || '',
                        total_pages: totalPages,'''

assert old_auto_save_payload in content, "old_auto_save_payload not found"
content = content.replace(old_auto_save_payload, new_auto_save_payload, 1)

with open(server_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: server.py fully patched for library appraisal hydration and document pages rendering!")
