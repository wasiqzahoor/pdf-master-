"""
PDF Master — Flask Web Application (v3.0 — Smart Compression)

Smart compression:
  - Detects PDF type (text-only vs image-heavy vs mixed)
  - Uses correct strategy per type
  - Fast Ghostscript settings (no 5-min wait)
  - Honest message if file cannot be compressed further

Install:
    pip install flask pikepdf Pillow
    Ghostscript: https://www.ghostscript.com/releases/gsdnld.html (Windows)

Run:
    python app.py  →  http://localhost:5000
"""

import glob
import io
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

try:
    import pikepdf
    from PIL import Image
except ImportError:
    raise SystemExit("Run: pip install pikepdf Pillow")

# ── App Setup ──────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

OUTPUT_FOLDER = Path("outputs")
OUTPUT_FOLDER.mkdir(exist_ok=True)

# ── Ghostscript DPI per level ──────────────────────────────────────────────
GS_DPI = {
    "low": {"color": 150, "gray": 150, "mono": 300},
    "medium": {"color": 100, "gray": 100, "mono": 200},
    "high": {"color": 72, "gray": 72, "mono": 150},
}

JPEG_QUALITY = {"low": 75, "medium": 50, "high": 28}


# ══════════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════════


def format_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b //= 1024
    return f"{b:.1f} GB"


def find_ghostscript() -> str | None:
    for name in ("gs", "gswin64c", "gswin32c"):
        p = shutil.which(name)
        if p:
            return p
    for pattern in [
        r"C:\Program Files\gs\**\gswin64c.exe",
        r"C:\Program Files\gs\**\gswin32c.exe",
        r"C:\Program Files (x86)\gs\**\gswin64c.exe",
    ]:
        hits = glob.glob(pattern, recursive=True)
        if hits:
            return hits[0]
    return None


# ══════════════════════════════════════════════════════════════════════════
# PDF ANALYSIS
# ══════════════════════════════════════════════════════════════════════════


def analyze_pdf(pdf_bytes: bytes) -> dict:
    image_count = 0
    has_text = False
    total_image_bytes = 0

    try:
        with pikepdf.open(io.BytesIO(pdf_bytes), suppress_warnings=True) as pdf:
            for page in pdf.pages:
                try:
                    if page.get("/Contents"):
                        has_text = True
                except Exception:
                    pass
                try:
                    res = page.get("/Resources")
                    if not res:
                        continue
                    xobj = res.get("/XObject")
                    if not xobj:
                        continue
                    for name in xobj.keys():
                        try:
                            o = xobj[name]
                            if o.get("/Subtype") == "/Image":
                                image_count += 1
                                total_image_bytes += len(bytes(o.read_bytes()))
                        except Exception:
                            pass
                except Exception:
                    pass
    except Exception:
        pass

    if image_count == 0:
        pdf_type = "text_only"
    elif has_text:
        pdf_type = "mixed"
    else:
        pdf_type = "image_heavy"

    return {
        "image_count": image_count,
        "has_text": has_text,
        "total_image_kb": total_image_bytes // 1024,
        "pdf_type": pdf_type,
    }


# ══════════════════════════════════════════════════════════════════════════
# STRATEGY 1: Ghostscript
# ══════════════════════════════════════════════════════════════════════════


def compress_ghostscript(input_bytes: bytes, level: str) -> bytes:
    gs = find_ghostscript()
    if not gs:
        raise RuntimeError("Ghostscript not found")

    dpi = GS_DPI.get(level, GS_DPI["medium"])

    with tempfile.TemporaryDirectory() as tmp:
        in_path = Path(tmp) / "in.pdf"
        out_path = Path(tmp) / "out.pdf"
        in_path.write_bytes(input_bytes)

        cmd = [
            gs,
            "-q",
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.5",
            "-dEmbedAllFonts=true",
            "-dSubsetFonts=true",
            "-dCompressFonts=true",
            "-dDownsampleColorImages=true",
            "-dDownsampleGrayImages=true",
            "-dDownsampleMonoImages=true",
            f"-dColorImageResolution={dpi['color']}",
            f"-dGrayImageResolution={dpi['gray']}",
            f"-dMonoImageResolution={dpi['mono']}",
            "-dColorImageDownsampleType=/Bicubic",
            "-dGrayImageDownsampleType=/Bicubic",
            "-dAutoFilterColorImages=true",
            "-dAutoFilterGrayImages=true",
            "-dCompressPages=true",
            "-dDetectDuplicateImages=true",
            "-dOptimize=true",
            f"-sOutputFile={out_path}",
            str(in_path),
        ]

        proc = subprocess.run(cmd, capture_output=True, timeout=90)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode(errors="ignore")[:400])
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError("Empty output from Ghostscript")

        return out_path.read_bytes()


# ══════════════════════════════════════════════════════════════════════════
# STRATEGY 2: pikepdf stream recompression (text-only PDFs)
# ══════════════════════════════════════════════════════════════════════════


def compress_streams_only(input_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with pikepdf.open(io.BytesIO(input_bytes), suppress_warnings=True) as pdf:
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            for k in list(meta.keys()):
                try:
                    del meta[k]
                except Exception:
                    pass
        if "/Info" in pdf.trailer:
            for k in list(pdf.trailer["/Info"].keys()):
                try:
                    del pdf.trailer["/Info"][k]
                except Exception:
                    pass
        for page in pdf.pages:
            for key in ("/Thumb", "/Metadata", "/AA", "/PieceInfo"):
                try:
                    if key in page:
                        del page[key]
                except Exception:
                    pass
        if "/Names" in pdf.Root:
            for key in ("/JavaScript", "/EmbeddedFiles"):
                try:
                    if key in pdf.Root["/Names"]:
                        del pdf.Root["/Names"][key]
                except Exception:
                    pass
        pdf.remove_unreferenced_resources()
        pdf.save(
            buf,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            normalize_content=True,
            recompress_flate=True,
        )
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════
# STRATEGY 3: pikepdf image recompression (fallback when no GS)
# ══════════════════════════════════════════════════════════════════════════


def recompress_one_image(raw: bytes, quality: int) -> bytes | None:
    try:
        img = Image.open(io.BytesIO(raw))
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode == "P":
            img = img.convert("RGB")
        elif img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
        return out.getvalue()
    except Exception:
        return None


def compress_images_pikepdf(input_bytes: bytes, level: str) -> bytes:
    quality = JPEG_QUALITY.get(level, 50)
    buf = io.BytesIO()
    compressed = skipped = 0
    seen = set()

    def process(obj):
        nonlocal compressed, skipped
        oid = id(obj)
        if oid in seen:
            return
        seen.add(oid)
        if not isinstance(obj, pikepdf.Stream):
            return
        if obj.get("/Subtype") != "/Image":
            return
        flt = obj.get("/Filter")
        if flt in (
            pikepdf.Name("/JPXDecode"),
            pikepdf.Name("/CCITTFaxDecode"),
            pikepdf.Name("/JBIG2Decode"),
        ):
            skipped += 1
            return
        try:
            raw = bytes(obj.read_bytes())
        except Exception:
            skipped += 1
            return
        new = recompress_one_image(raw, quality)
        if not new or len(new) >= len(raw):
            skipped += 1
            return
        obj.write(new, filter=pikepdf.Name("/DCTDecode"))
        try:
            reloaded = Image.open(io.BytesIO(new))
            obj["/Width"] = reloaded.width
            obj["/Height"] = reloaded.height
            obj["/BitsPerComponent"] = 8
            obj["/ColorSpace"] = (
                pikepdf.Name("/DeviceGray")
                if reloaded.mode == "L"
                else pikepdf.Name("/DeviceRGB")
            )
            if "/SMask" in obj:
                del obj["/SMask"]
        except Exception:
            pass
        compressed += 1

    with pikepdf.open(io.BytesIO(input_bytes), suppress_warnings=True) as pdf:
        for page in pdf.pages:
            try:
                res = page.get("/Resources")
                if res:
                    xobj = res.get("/XObject")
                    if xobj:
                        for name in xobj.keys():
                            try:
                                process(xobj[name])
                            except Exception:
                                pass
            except Exception:
                pass
        for obj in pdf.objects:
            try:
                process(obj)
            except Exception:
                pass

        # Metadata strip
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            for k in list(meta.keys()):
                try:
                    del meta[k]
                except Exception:
                    pass
        if "/Info" in pdf.trailer:
            for k in list(pdf.trailer["/Info"].keys()):
                try:
                    del pdf.trailer["/Info"][k]
                except Exception:
                    pass

        pdf.remove_unreferenced_resources()
        pdf.save(
            buf,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            normalize_content=True,
            recompress_flate=True,
        )

    print(f"[pikepdf-images] compressed={compressed} skipped={skipped}")
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════
# SMART DISPATCH
# ══════════════════════════════════════════════════════════════════════════


def do_compress(input_bytes: bytes, level: str = "medium") -> dict:
    original_size = len(input_bytes)
    info = analyze_pdf(input_bytes)
    gs = find_ghostscript()

    print(
        f"[analyze] type={info['pdf_type']} images={info['image_count']} "
        f"image_kb={info['total_image_kb']} gs={'yes' if gs else 'no'}"
    )

    candidates = []  # (bytes, method)

    # Always try Ghostscript if available — it handles all PDF types
    if gs:
        try:
            r = compress_ghostscript(input_bytes, level)
            candidates.append((r, "ghostscript"))
            print(f"[GS] {format_size(original_size)} → {format_size(len(r))}")
        except Exception as e:
            print(f"[GS] failed: {e}")

    # For image PDFs, also try pikepdf image recompression
    if info["pdf_type"] in ("image_heavy", "mixed"):
        try:
            r = compress_images_pikepdf(input_bytes, level)
            candidates.append((r, "pikepdf-images"))
            print(f"[pikepdf-img] {format_size(original_size)} → {format_size(len(r))}")
        except Exception as e:
            print(f"[pikepdf-images] failed: {e}")

    # Always try stream-only compression (fast, small gains on text)
    try:
        r = compress_streams_only(input_bytes)
        candidates.append((r, "pikepdf-streams"))
        print(f"[pikepdf-streams] {format_size(original_size)} → {format_size(len(r))}")
    except Exception as e:
        print(f"[pikepdf-streams] failed: {e}")

    # Pick the smallest result that is actually smaller than original
    best_bytes = input_bytes
    best_method = "none"
    reduced = False

    for result_bytes, method in candidates:
        if len(result_bytes) < len(best_bytes):
            best_bytes = result_bytes
            best_method = method
            reduced = True

    return {
        "bytes": best_bytes,
        "method": best_method,
        "info": info,
        "reduced": reduced,
    }


# ══════════════════════════════════════════════════════════════════════════
# MERGE
# ══════════════════════════════════════════════════════════════════════════


def do_merge(file_bytes_list: list[bytes]) -> bytes:
    buf = io.BytesIO()
    with pikepdf.new() as merged:
        for i, pdf_bytes in enumerate(file_bytes_list):
            try:
                with pikepdf.open(io.BytesIO(pdf_bytes), suppress_warnings=True) as src:
                    merged.pages.extend(src.pages)
            except Exception as e:
                print(f"[merge] skipping file {i+1}: {e}")
        merged.remove_unreferenced_resources()
        merged.save(
            buf,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════
# CLEANUP
# ══════════════════════════════════════════════════════════════════════════


def _cleanup():
    while True:
        time.sleep(3600)
        now = time.time()
        for f in OUTPUT_FOLDER.iterdir():
            try:
                if f.is_file() and now - f.stat().st_mtime > 3600:
                    f.unlink()
            except Exception:
                pass


threading.Thread(target=_cleanup, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/style.css")
def css():
    return send_from_directory(".", "style.css")


@app.route("/script.js")
def js():
    return send_from_directory(".", "script.js")


@app.route("/logo.png")
def logo():
    return send_from_directory(".", "logo.png")


@app.route("/api/compress", methods=["POST", "HEAD"])
def api_compress():
    if request.method == "HEAD":
        return "", 200

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    level = request.form.get("level", "medium")

    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400
    if level not in GS_DPI:
        return jsonify({"error": "Invalid level. Use: low, medium, high"}), 400

    try:
        input_bytes = f.read()
        if not input_bytes:
            return jsonify({"error": "Uploaded file is empty"}), 400

        original_size = len(input_bytes)
        res = do_compress(input_bytes, level)

        output_bytes = res["bytes"]
        compressed_size = len(output_bytes)
        reduction = round((1 - compressed_size / original_size) * 100, 1)

        out_name = f"compressed_{uuid.uuid4().hex[:8]}_{Path(f.filename).name}"
        (OUTPUT_FOLDER / out_name).write_bytes(output_bytes)

        pdf_type = res["info"]["pdf_type"]
        image_count = res["info"]["image_count"]

        if not res["reduced"]:
            if pdf_type == "text_only":
                note = (
                    "This PDF has only text/vectors — already fully optimized. "
                    "No further compression possible."
                )
            else:
                note = (
                    f"Images ({image_count}) appear already compressed at max quality. "
                    "Original file returned."
                )
        else:
            note = f"Compressed using {res['method']} — {reduction}% saved."

        return jsonify(
            {
                "success": True,
                "download_url": f"/download/{out_name}",
                "original_size": original_size,
                "compressed_size": compressed_size,
                "original_fmt": format_size(original_size),
                "compressed_fmt": format_size(compressed_size),
                "reduction": reduction,
                "method": res["method"],
                "pdf_type": pdf_type,
                "image_count": image_count,
                "actually_reduced": res["reduced"],
                "note": note,
                "filename": f"compressed_{Path(f.filename).name}",
            }
        )

    except pikepdf.PasswordError:
        return (
            jsonify({"error": "PDF is password-protected. Remove password first."}),
            400,
        )
    except Exception as e:
        print(f"[compress error] {e}")
        return jsonify({"error": "Compression failed. File may be corrupt."}), 500


@app.route("/api/merge", methods=["POST"])
def api_merge():
    files = request.files.getlist("files")
    if not files or len(files) < 2:
        return jsonify({"error": "Please upload at least 2 PDF files."}), 400

    try:
        file_bytes_list = []
        total_pages = 0
        for f in files:
            if not f.filename.lower().endswith(".pdf"):
                return jsonify({"error": f"'{f.filename}' is not a PDF."}), 400
            data = f.read()
            if not data:
                return jsonify({"error": f"'{f.filename}' is empty."}), 400
            file_bytes_list.append(data)
            try:
                with pikepdf.open(io.BytesIO(data), suppress_warnings=True) as p:
                    total_pages += len(p.pages)
            except Exception:
                pass

        merged_bytes = do_merge(file_bytes_list)
        out_name = f"merged_{uuid.uuid4().hex[:8]}.pdf"
        (OUTPUT_FOLDER / out_name).write_bytes(merged_bytes)

        return jsonify(
            {
                "success": True,
                "download_url": f"/download/{out_name}",
                "merged_size": len(merged_bytes),
                "merged_fmt": format_size(len(merged_bytes)),
                "page_count": total_pages,
                "filename": "merged_output.pdf",
            }
        )
    except Exception as e:
        print(f"[merge error] {e}")
        return jsonify({"error": "Merge failed. Check all files are valid PDFs."}), 500


@app.route("/api/status")
def api_status():
    gs = find_ghostscript()
    return jsonify(
        {
            "status": "ok",
            "ghostscript": gs is not None,
            "ghostscript_path": gs or "not found",
            "engine": "ghostscript + pikepdf" if gs else "pikepdf only",
        }
    )


@app.route("/download/<filename>")
def download(filename):
    safe = Path(filename).name
    path = OUTPUT_FOLDER / safe
    if not path.exists():
        return jsonify({"error": "File not found or expired."}), 404
    parts = safe.split("_", 2)
    display = f"{parts[0]}_{parts[2]}" if len(parts) == 3 else safe
    return send_file(path, as_attachment=True, download_name=display)


# ══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    gs = find_ghostscript()
    print("\n" + "=" * 60)
    print("  PDF Master v3.0 — Smart Compression")
    print("=" * 60)
    print(f"  Ghostscript : {'✓  ' + gs if gs else '✗  NOT FOUND'}")
    print(f"  pikepdf     : ✓  Available")
    print(f"  Strategy    : Auto (detects PDF type, picks best method)")
    print("=" * 60)
    print("  Open: http://localhost:5000")
    print("=" * 60 + "\n")
    app.run(debug=False, host="0.0.0.0", port=5000)
