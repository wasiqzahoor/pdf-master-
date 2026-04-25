/* ============================================================
   PDF MASTER — JAVASCRIPT
   Auto-detects Flask backend → uses real Python compression
   Falls back to browser-side PDF-Lib if no backend found
   ============================================================ */

"use strict";

// ── Detect backend ─────────────────────────────────────────────────────────
let BACKEND_AVAILABLE = false;

async function detectBackend() {
    try {
        const res = await fetch("/api/compress", { method: "HEAD" });
        BACKEND_AVAILABLE = (res.status !== 404);
    } catch (e) {
        BACKEND_AVAILABLE = false;
    }
    updateBackendBadge();
}

function updateBackendBadge() {
    const badge = document.getElementById("backend-badge");
    if (!badge) return;
    if (BACKEND_AVAILABLE) {
        badge.textContent = "🐍 Python Engine Active — Real Image Compression";
        badge.className   = "backend-badge python";
    } else {
        badge.textContent = "⚠️ Browser Mode — Start app.py for real compression";
        badge.className   = "backend-badge browser";
    }
}

let PDFDocLib;
if (typeof PDFLib !== "undefined") PDFDocLib = PDFLib.PDFDocument;

let mergeFiles              = [];
let compressFile            = null;
let currentCompressionLevel = "medium";

const mergeInput      = document.getElementById("merge-input");
const mergeFileList   = document.getElementById("merge-file-list");
const mergeBtn        = document.getElementById("merge-btn");
const mergeActionArea = document.getElementById("merge-action-area");
const mergeDropZone   = document.getElementById("merge-drop-zone");
const fileCountText   = document.getElementById("file-count-text");
const compressInput   = document.getElementById("compress-input");
const compressBtn     = document.getElementById("compress-btn");
const compControls    = document.getElementById("comp-controls");
const compFileInfo    = document.getElementById("compress-file-info");
const compFileName    = document.getElementById("compress-file-name");
const compFileSize    = document.getElementById("compress-file-size");
const compInfoText    = document.getElementById("comp-info-text");
const compressDropZone = document.getElementById("compress-drop-zone");
const compRemoveBtn   = document.getElementById("compress-remove-btn");
const progressModal   = document.getElementById("progress-modal");
const progressPercent = document.getElementById("progress-percent");
const progressTitle   = document.getElementById("progress-title");
const progressSub     = document.getElementById("progress-sub");
const spinnerFill     = document.getElementById("spinner-fill");
const toast    = document.getElementById("toast");
const toastMsg = document.getElementById("toast-msg");
const toastIcon = document.getElementById("toast-icon");

window.addEventListener("scroll", () => {
    document.getElementById("navbar").classList.toggle("scrolled", window.scrollY > 20);
});

const cursor = document.getElementById("cursor");
const cursorFollower = document.getElementById("cursor-follower");
let mouseX = 0, mouseY = 0, followerX = 0, followerY = 0;
if (cursor && cursorFollower) {
    document.addEventListener("mousemove", e => {
        mouseX = e.clientX; mouseY = e.clientY;
        cursor.style.left = mouseX + "px"; cursor.style.top = mouseY + "px";
    });
    (function animateCursor() {
        followerX += (mouseX - followerX) * 0.12;
        followerY += (mouseY - followerY) * 0.12;
        cursorFollower.style.left = followerX + "px";
        cursorFollower.style.top  = followerY + "px";
        requestAnimationFrame(animateCursor);
    })();
    document.querySelectorAll("a, button, .drop-zone, .level-btn").forEach(el => {
        el.addEventListener("mouseenter", () => { cursor.style.width = "14px"; cursor.style.height = "14px"; cursorFollower.style.width = "50px"; cursorFollower.style.height = "50px"; });
        el.addEventListener("mouseleave", () => { cursor.style.width = "8px"; cursor.style.height = "8px"; cursorFollower.style.width = "32px"; cursorFollower.style.height = "32px"; });
    });
}

const hamburger  = document.getElementById("hamburger");
const mobileMenu = document.getElementById("mobile-menu");
if (hamburger) hamburger.addEventListener("click", () => mobileMenu.classList.toggle("open"));
function closeMobileMenu() { if (mobileMenu) mobileMenu.classList.remove("open"); }

document.querySelectorAll(".tool-card, .feature-card, .section-header").forEach(el => {
    el.classList.add("reveal");
    new IntersectionObserver(entries => {
        entries.forEach(e => { if (e.isIntersecting) el.classList.add("visible"); });
    }, { threshold: 0.1 }).observe(el);
});

function formatSize(bytes) {
    if (!bytes) return "0 B";
    const k = 1024, s = ["B","KB","MB","GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k,i)).toFixed(2)) + " " + s[i];
}

function showToast(msg, type = "success") {
    toastMsg.textContent = msg;
    toast.className = "toast " + type;
    toastIcon.className = type === "success" ? "fas fa-check-circle" : "fas fa-times-circle";
    void toast.offsetWidth;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 5000);
}

function setProgress(pct, title, sub) {
    const offset = 251 - (pct / 100) * 251;
    if (spinnerFill) spinnerFill.style.strokeDashoffset = offset;
    if (progressPercent) progressPercent.textContent = Math.round(pct) + "%";
    if (title && progressTitle) progressTitle.textContent = title;
    if (sub   && progressSub)   progressSub.textContent   = sub;
}

function showProgress(title, sub) { setProgress(0, title, sub); if (progressModal) progressModal.classList.add("active"); }
function hideProgress() { setProgress(100); setTimeout(() => { if (progressModal) progressModal.classList.remove("active"); }, 500); }

function triggerDownload(url, filename) {
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ============================================================
// MERGE TOOL
// ============================================================
mergeInput.addEventListener("change", e => { addMergeFiles(Array.from(e.target.files)); e.target.value = ""; });

["dragover","dragleave","drop"].forEach(ev => mergeDropZone.addEventListener(ev, e => {
    e.preventDefault();
    if (ev === "dragover") mergeDropZone.classList.add("dragging");
    if (ev === "dragleave") mergeDropZone.classList.remove("dragging");
    if (ev === "drop") { mergeDropZone.classList.remove("dragging"); addMergeFiles(Array.from(e.dataTransfer.files).filter(f => f.type === "application/pdf")); }
}));

function addMergeFiles(files) {
    let added = 0;
    files.forEach(f => { if (f.type === "application/pdf") { mergeFiles.push(f); added++; } });
    if (!added) { showToast("Please select valid PDF files.", "error"); return; }
    renderFileList();
}

function renderFileList() {
    mergeFileList.innerHTML = "";
    mergeFiles.forEach((file, index) => {
        const item = document.createElement("div");
        item.className = "file-item"; item.draggable = true; item.dataset.index = index;
        item.innerHTML = `<div class="file-item-num">${index+1}</div><i class="fas fa-file-pdf file-item-icon"></i><div class="file-item-name" title="${file.name}">${file.name}</div><div class="file-item-size">${formatSize(file.size)}</div><i class="fas fa-grip-lines file-item-drag"></i><button class="file-item-remove" data-index="${index}"><i class="fas fa-times"></i></button>`;
        item.addEventListener("dragstart", e => { e.dataTransfer.setData("text/plain", index); setTimeout(() => item.classList.add("dragging-item"), 0); });
        item.addEventListener("dragend", () => item.classList.remove("dragging-item"));
        item.addEventListener("dragover", e => { e.preventDefault(); document.querySelectorAll(".file-item").forEach(i => i.classList.remove("drag-over")); item.classList.add("drag-over"); });
        item.addEventListener("dragleave", () => item.classList.remove("drag-over"));
        item.addEventListener("drop", e => { e.preventDefault(); item.classList.remove("drag-over"); const src = parseInt(e.dataTransfer.getData("text/plain")); if (isNaN(src) || src === index) return; const moved = mergeFiles.splice(src,1)[0]; mergeFiles.splice(index,0,moved); renderFileList(); });
        item.querySelector(".file-item-remove").addEventListener("click", () => { mergeFiles.splice(index,1); renderFileList(); });
        mergeFileList.appendChild(item);
    });
    if (mergeFiles.length > 0) {
        mergeActionArea.style.display = "flex";
        fileCountText.textContent = `${mergeFiles.length} file${mergeFiles.length!==1?"s":""} ready to merge`;
        mergeBtn.disabled = mergeFiles.length < 2;
    } else { mergeActionArea.style.display = "none"; }
}

document.getElementById("merge-clear-btn").addEventListener("click", () => { mergeFiles = []; renderFileList(); });
mergeBtn.addEventListener("click", async () => { BACKEND_AVAILABLE ? await mergePDFsBackend() : await mergePDFsBrowser(); });

async function mergePDFsBackend() {
    if (mergeFiles.length < 2) return;
    showProgress("Merging PDFs...", "Uploading files to Python engine");
    try {
        const formData = new FormData();
        mergeFiles.forEach(f => formData.append("files", f));
        setProgress(30, "Merging PDFs...", "Python is merging your files");
        const res = await fetch("/api/merge", { method: "POST", body: formData });
        const data = await res.json();
        setProgress(95, "Almost done!", "");
        if (!data.success) throw new Error(data.error || "Unknown error");
        await new Promise(r => setTimeout(r,300)); hideProgress();
        const a = document.createElement("a"); a.href = data.download_url; a.download = data.filename;
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        showToast(`Merged ${mergeFiles.length} files — ${data.merged_fmt}`, "success");
    } catch(err) { hideProgress(); showToast("Merge failed: " + err.message, "error"); }
}

async function mergePDFsBrowser() {
    if (!PDFDocLib) { showToast("PDF-Lib not loaded.", "error"); return; }
    showProgress("Merging PDFs...", "Browser mode");
    try {
        const merged = await PDFDocLib.create();
        for (let i = 0; i < mergeFiles.length; i++) {
            setProgress((i/mergeFiles.length)*85, "Merging...", `File ${i+1}/${mergeFiles.length}`);
            try { const buf = await mergeFiles[i].arrayBuffer(); const pdf = await PDFDocLib.load(buf,{ignoreEncryption:true}); const pages = await merged.copyPages(pdf,pdf.getPageIndices()); pages.forEach(p=>merged.addPage(p)); } catch(e){}
        }
        const bytes = await merged.save({useObjectStreams:true}); hideProgress();
        triggerDownload(URL.createObjectURL(new Blob([bytes],{type:"application/pdf"})),"merged_output.pdf");
        showToast(`Merged ${mergeFiles.length} files — ${formatSize(bytes.length)}`,"success");
    } catch(err) { hideProgress(); showToast("Merge failed: "+err.message,"error"); }
}

// ============================================================
// COMPRESS TOOL
// ============================================================
compressInput.addEventListener("change", e => { const f=e.target.files[0]; if(!f)return; if(f.type!=="application/pdf"){showToast("Please select a valid PDF.","error");return;} loadCompressFile(f); e.target.value=""; });

["dragover","dragleave","drop"].forEach(ev => compressDropZone.addEventListener(ev, e => {
    e.preventDefault();
    if (ev === "dragover") compressDropZone.classList.add("dragging");
    if (ev === "dragleave") compressDropZone.classList.remove("dragging");
    if (ev === "drop") { compressDropZone.classList.remove("dragging"); const f=e.dataTransfer.files[0]; if(f&&f.type==="application/pdf")loadCompressFile(f); else showToast("Please drop a valid PDF file.","error"); }
}));

function loadCompressFile(file) { compressFile=file; compFileName.textContent=file.name; compFileSize.textContent=`Original: ${formatSize(file.size)}`; compFileInfo.style.display="block"; compControls.style.display="block"; compressBtn.disabled=false; updateCompInfoText(); }
compRemoveBtn.addEventListener("click", () => { compressFile=null; compFileInfo.style.display="none"; compControls.style.display="none"; compressBtn.disabled=true; compressInput.value=""; });

const compressionDescriptions = {
    low:    "Low — Re-encodes images at 75% JPEG quality, downsamples to 200 DPI. Fastest, ~20-40% size reduction.",
    medium: "Medium — Re-encodes images at 50% JPEG quality, downsamples to 150 DPI. Balanced. ~40-65% reduction.",
    high:   "High — Re-encodes images at 30% JPEG quality, downsamples to 100 DPI. Maximum compression. ~60-85% reduction.",
};

function setLevel(level) { currentCompressionLevel=level; document.querySelectorAll(".level-btn").forEach(b=>b.classList.toggle("active",b.dataset.level===level)); updateCompInfoText(); }
function updateCompInfoText() { if(compInfoText) compInfoText.textContent=compressionDescriptions[currentCompressionLevel]||""; }

compressBtn.addEventListener("click", async () => { BACKEND_AVAILABLE ? await compressPDFBackend() : await compressPDFBrowser(); });

async function compressPDFBackend() {
    if (!compressFile) return;
    showProgress("Compressing PDF...", "Uploading to Python engine");
    try {
        const formData = new FormData();
        formData.append("file", compressFile);
        formData.append("level", currentCompressionLevel);
        let fake = 15;
        const ticker = setInterval(() => { fake = Math.min(fake+2, 85); setProgress(fake, "Compressing PDF...", "Python is recompressing images..."); }, 300);
        const res = await fetch("/api/compress", { method: "POST", body: formData });
        clearInterval(ticker);
        const data = await res.json();
        setProgress(95, "Almost done!", "");
        if (!data.success) throw new Error(data.error || "Compression failed");
        await new Promise(r => setTimeout(r,300)); hideProgress();
        const a = document.createElement("a"); a.href = data.download_url; a.download = data.filename;
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        const msg = data.reduction > 0
            ? `Compressed: ${data.original_fmt} → ${data.compressed_fmt} (${data.reduction}% smaller)`
            : `Already optimized — saved as ${data.compressed_fmt}`;
        showToast(msg, "success");
    } catch(err) { hideProgress(); showToast("Compression failed: "+err.message,"error"); }
}

async function compressPDFBrowser() {
    if (!compressFile||!PDFDocLib) return;
    showProgress("Compressing PDF...", "Browser mode — structure only\n(Run app.py for real compression)");
    try {
        const buf = await compressFile.arrayBuffer();
        setProgress(30,"Compressing...","Parsing PDF");
        const pdfDoc = await PDFDocLib.load(buf,{ignoreEncryption:true});
        pdfDoc.setTitle(""); pdfDoc.setAuthor(""); pdfDoc.setSubject(""); pdfDoc.setKeywords([]); pdfDoc.setProducer(""); pdfDoc.setCreator("");
        if(currentCompressionLevel==="medium"||currentCompressionLevel==="high"){try{pdfDoc.getForm().flatten();}catch(e){}}
        setProgress(80,"Saving...","");
        const bytes = await pdfDoc.save({useObjectStreams:true}); hideProgress();
        const red = ((compressFile.size-bytes.length)/compressFile.size*100).toFixed(1);
        triggerDownload(URL.createObjectURL(new Blob([bytes],{type:"application/pdf"})),`compressed_${compressFile.name}`);
        showToast((red>0?`${formatSize(compressFile.size)} → ${formatSize(bytes.length)} (${red}% smaller)`:`Already optimized`) + " — Start app.py for real image compression!","success");
    } catch(err) { hideProgress(); showToast("Failed: "+err.message,"error"); }
}

updateCompInfoText();
detectBackend();