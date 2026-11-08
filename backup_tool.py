
import argparse
from collections import deque
import hashlib
import logging
import logging.handlers
import os
import re
import shutil
import smtplib
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

try:
    import yaml
except ImportError:
    print("مكتبة PyYAML مفقودة. ثبّتها عبر: pip install pyyaml")
    sys.exit(1)


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
def setup_logging(log_dir: str, keep_days: int) -> logging.Logger:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / f"backup_{datetime.now():%Y%m%d}.log"

    logger = logging.getLogger("backup_tool")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # تنظيف ملفات اللوج القديمة
    cutoff = datetime.now() - timedelta(days=keep_days)
    for f in Path(log_dir).glob("backup_*.log*"):
        try:
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
        except OSError:
            pass

    return logger


# ----------------------------------------------------------------------------
# Robocopy
# ----------------------------------------------------------------------------
ROBOCOPY_EXIT_MEANINGS = {
    0: "لا توجد ملفات للنسخ (متطابق مسبقاً)",
    1: "تم نسخ الملفات بنجاح",
    2: "توجد ملفات/مجلدات إضافية بالهدف (extra items)",
    3: "نسخ ناجح + ملفات إضافية بالهدف",
    4: "توجد اختلافات (mismatched items)",
    5: "نسخ ناجح + اختلافات",
    6: "اختلافات + ملفات إضافية",
    7: "نسخ ناجح + اختلافات + ملفات إضافية",
}


def _get_subprocess_kwargs():
    """خيارات إخفاء النافذة السوداء في ويندوز تماماً"""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000
        )
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs


# أعلام robocopy الممنوعة نهائياً: تنقل/تحذف من المصدر أو تحذف من الوجهة
_FORBIDDEN_FLAGS = {"/MOV", "/MOVE", "/PURGE", "/MIR"}


def _assert_safe_args(args):
    """حماية أخيرة: لا يُسمح أبداً بتنفيذ أمر يمكنه حذف أو نقل ملفات."""
    bad = [a for a in args[3:] if a.upper().split(":")[0] in _FORBIDDEN_FLAGS]
    if bad:
        raise RuntimeError(f"أعلام robocopy ممنوعة لحماية الملفات: {bad}")


# سطر ملف منسوخ في مخرجات robocopy مع /BYTES:  "New File   1234   path"
_COPIED_LINE = re.compile(r"^\s*(New File|Newer|Older|Changed|Modified)\s+(\d+)\s+(.+?)\s*$")

# إلغاء العملية من الواجهة (أو من أي خيط آخر)
CANCEL = threading.Event()
_active_proc = [None]


def request_cancel():
    """يطلب إيقاف النسخ الجاري: يوقف robocopy فوراً ولا يبدأ مصادر جديدة."""
    CANCEL.set()
    proc = _active_proc[0]
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass


def _decode_console(raw: bytes) -> str:
    """robocopy يكتب عبر الأنبوب بترميز OEM الخاص بويندوز (وليس UTF-8)،
    فنفكّه بنفس الترميز حتى تظهر أسماء الملفات العربية سليمة."""
    if sys.platform == "win32":
        try:
            return raw.decode("oem", errors="replace")
        except LookupError:
            pass
    return raw.decode("utf-8", errors="replace")


def run_robocopy(src: str, dst: str, cfg: dict, logger: logging.Logger, dry_run: bool,
                 progress_callback=None) -> bool:
    """ينفذ Robocopy بسرعة عالية وبدون أي شاشات سوداء."""
    # لا تنشئ أي مجلد أثناء التجربة؛ dry-run يجب أن يبقى عملية قراءة فقط.
    if not dry_run:
        try:
            Path(dst).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("تعذر إنشاء مجلد الوجهة %s: %s", dst, exc)
            return False

    rc_cfg = cfg.get("robocopy", {})
    threads = rc_cfg.get("threads", 8)
    retries = rc_cfg.get("retries", 3)
    wait_sec = rc_cfg.get("wait_seconds", 5)

    # تجهيز أوامر Robocopy السريعة والتزايدية (Incremental)
    # /E: نسخ المجلدات بما فيها الفارغة
    # /FFT: التسامح مع فروقات التوقيت البسيطة (2 ثانية) بين أنظمة الملفات والشبكة لمنع إعادة نسخ المتطابق
    args = [
        "robocopy",
        src,
        dst,
        "/E",
        "/FFT",
        f"/R:{retries}",
        f"/W:{wait_sec}",
        f"/MT:{threads}",
        "/NP",        # إلغاء النسبة المئوية المزعجة لكل بايت لتسريع الإخراج
        "/BYTES",
        # لا نستخدم /TEE: المخرجات مقروءة هنا من الـ pipe، وإرسالها أيضاً إلى
        # نافذة مخفية يزيد الحمل بلا فائدة.
    ]

    # الافتراضي: لا يُستبدل أي ملف موجود في الوجهة (يُنسخ الجديد فقط):
    #   /XC تخطي المتغيّر  /XN تخطي الأحدث بالمصدر  /XO تخطي الأقدم بالمصدر
    overwrite = bool(rc_cfg.get("overwrite_existing", False))
    if not overwrite:
        args += ["/XC", "/XN", "/XO"]

    if rc_cfg.get("backup_mode"):
        args.append("/ZB")
    elif rc_cfg.get("restartable"):
        args.append("/Z")

    if dry_run:
        args.append("/L")
        logger.info("[DRY-RUN] لن يتم نسخ أي ملف فعلياً")

    _assert_safe_args(args)
    logger.info(f"تنفيذ: {' '.join(args)}")

    if CANCEL.is_set():
        return False

    # الحجم الكلي للمصدر مرة واحدة (لحساب نسبة تقدم حقيقية بالبايت)
    total_size = 0
    if progress_callback and not dry_run:
        _, total_size = folder_stats(src)

    sp_kwargs = _get_subprocess_kwargs()
    try:
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **sp_kwargs
        )
    except FileNotFoundError:
        logger.error("أمر robocopy غير موجود - تأكد أنك تشغل هذا على ويندوز.")
        return False
    except OSError as exc:
        logger.error("تعذر بدء Robocopy: %s", exc)
        return False

    _active_proc[0] = proc
    copied = 0
    kept_different = 0  # ملفات موجودة بالوجهة بنسخة مختلفة ولم تُستبدل
    tail = deque(maxlen=60)  # آخر الأسطر فقط (الملخص) حتى لا يتضخم اللوج
    report = progress_callback is not None and not dry_run

    if report:
        progress_callback(0)

    try:
        for raw in iter(proc.stdout.readline, b""):
            line = _decode_console(raw).strip()
            if not line:
                continue
            tail.append(line)
            if CANCEL.is_set():
                break
            m = _COPIED_LINE.match(line)
            if m:
                label = m.group(1)
                if label != "New File" and not overwrite:
                    kept_different += 1   # تم تخطيه (موجود بالوجهة) وليس منسوخاً
                    continue
                if report:
                    copied += int(m.group(2))
                    pct = min(99, int(copied * 100 / total_size)) if total_size > 0 else 0
                    progress_callback(pct, re.split(r"[\\/]", m.group(3))[-1])
    except Exception as exc:
        logger.warning("تعذر قراءة تقدم Robocopy: %s", exc)

    cancelled = CANCEL.is_set()
    if cancelled and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass
    try:
        proc.wait(timeout=15 if cancelled else None)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    finally:
        _active_proc[0] = None

    if tail:
        logger.debug("\n".join(tail))

    if cancelled:
        logger.warning("تم إيقاف Robocopy بطلب المستخدم.")
        return False

    if kept_different:
        logger.warning(f"{kept_different} ملف موجود بالوجهة بنسخة مختلفة عن المصدر لم يُستبدل "
                       f"(الوضع الآمن: لا يُستبدل أي ملف موجود).")

    exit_code = proc.returncode
    if report:
        progress_callback(100, "اكتمل")

    # Robocopy: الأكواد 0-7 نجاح (0: متطابق مسبقاً، 1: تم نسخ ملفات، 2: ملفات إضافية، 3: 1+2)
    if exit_code < 8:
        meaning = ROBOCOPY_EXIT_MEANINGS.get(exit_code, "نجاح")
        logger.info(f"Robocopy انتهى برمز {exit_code} ({meaning})")
        return True

    logger.error(f"Robocopy فشل برمز خروج {exit_code}")
    return False


def backup_source_with_retry(name: str, src: str, dst: str, cfg: dict, logger: logging.Logger,
                             dry_run: bool, progress_callback=None) -> bool:
    """يكرر محاولة نسخ مصدر واحد كامل عند الفشل الكلي (مثل انقطاع شبكة تام)."""
    max_retries = cfg.get("job_retries", 3)
    wait_between = cfg.get("job_retry_wait_seconds", 60)

    if not os.path.exists(src):
        logger.error(f"[{name}] المسار المصدر غير موجود: {src}")
        return False

    for attempt in range(1, max_retries + 1):
        if CANCEL.is_set():
            return False
        logger.info(f"[{name}] محاولة {attempt}/{max_retries}: نسخ {src} -> {dst}")
        ok = run_robocopy(src, dst, cfg, logger, dry_run, progress_callback)
        if ok:
            return True
        if attempt < max_retries:
            logger.warning(f"[{name}] فشلت المحاولة {attempt}. الانتظار {wait_between} ثانية قبل إعادة المحاولة...")
            if CANCEL.wait(wait_between):  # انتظار قابل للإلغاء
                return False

    logger.error(f"[{name}] فشلت كل المحاولات ({max_retries}).")
    return False


# ----------------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------------
def folder_stats(path: str):
    """يرجع (عدد الملفات، الحجم الكلي بالبايت) لمجلد."""
    total_files, total_size = 0, 0
    stack = [path]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total_size += e.stat(follow_symlinks=False).st_size
                            total_files += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return total_files, total_size


def sha256_of_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_backup(name: str, src: str, dst: str, cfg: dict, logger: logging.Logger) -> bool:
    """
    التحقق من صحة النسخ الاحتياطي:
    يفحص أن كل ملف موجود في المصدر قد تم نسخه بنجاح للهدف وتطابق حجمه.
    وجود ملفات سابقة أو إضافية في الهدف (النسخ التزايدي Incremental) لا يُعد فشلاً!
    """
    v_cfg = cfg.get("verification", {})
    all_ok = True

    if v_cfg.get("compare_file_count_and_size", True):
        overwrite_existing = bool(cfg.get("robocopy", {}).get("overwrite_existing", False))
        kept_old = 0
        missing_count = 0
        size_mismatches = 0
        checked_files = 0
        total_src_size = 0

        for root, _, files in os.walk(src):
            for fname in files:
                src_file = os.path.join(root, fname)
                rel = os.path.relpath(src_file, src)
                dst_file = os.path.join(dst, rel)

                checked_files += 1
                try:
                    s_stat = os.stat(src_file)
                    total_src_size += s_stat.st_size
                except OSError:
                    continue

                if not os.path.exists(dst_file):
                    logger.warning(f"[{name}] ملف مفقود بالهدف: {rel}")
                    missing_count += 1
                    all_ok = False
                    continue

                try:
                    d_stat = os.stat(dst_file)
                    if s_stat.st_size != d_stat.st_size:
                        if not overwrite_existing:
                            kept_old += 1
                            logger.warning(f"[{name}] نسخة مختلفة محفوظة بالوجهة ولم تُستبدل: {rel}")
                        else:
                            logger.warning(f"[{name}] اختلاف في الحجم للملف: {rel} (المصدر: {s_stat.st_size} بايت | الهدف: {d_stat.st_size} بايت)")
                            size_mismatches += 1
                            all_ok = False
                except OSError as e:
                    logger.warning(f"[{name}] تعذر قراءة بيانات الملف بالهدف {rel}: {e}")
                    all_ok = False

        if all_ok:
            logger.info(f"[{name}] تحقق ناجح: جميع ملفات المصدر ({checked_files} ملف، {total_src_size} بايت) موجودة بالهدف.")
            if kept_old:
                logger.warning(f"[{name}] تنبيه: {kept_old} ملف بنسخة مختلفة بالوجهة (لم تُستبدل حسب الوضع الآمن).")
        else:
            logger.warning(f"[{name}] فشل التحقق: {missing_count} ملف مفقود، {size_mismatches} ملف مختلف الحجم.")

    if name in v_cfg.get("checksum_verify_sources", []):
        logger.info(f"[{name}] بدء التحقق بـ checksum (قد يستغرق وقتاً حسب حجم الملفات)...")
        mismatches = 0
        for root, _, files in os.walk(src):
            for fname in files:
                src_file = os.path.join(root, fname)
                rel = os.path.relpath(src_file, src)
                dst_file = os.path.join(dst, rel)
                if not os.path.exists(dst_file):
                    logger.warning(f"[{name}] ملف مفقود بالهدف: {rel}")
                    mismatches += 1
                    continue
                if sha256_of_file(src_file) != sha256_of_file(dst_file):
                    logger.warning(f"[{name}] checksum غير متطابق: {rel}")
                    mismatches += 1
        if mismatches:
            logger.warning(f"[{name}] عدد الملفات غير المتطابقة بالـ checksum: {mismatches}")
            all_ok = False
        else:
            logger.info(f"[{name}] كل ملفات checksum متطابقة تماماً.")

    return all_ok


# ----------------------------------------------------------------------------
# Retention
# ----------------------------------------------------------------------------
def apply_retention(target_root: str, retention_days: int, logger: logging.Logger):
    if not os.path.isdir(target_root):
        return
    cutoff = datetime.now() - timedelta(days=retention_days)
    for entry in os.listdir(target_root):
        full_path = os.path.join(target_root, entry)
        if not os.path.isdir(full_path):
            continue
        try:
            folder_date = datetime.strptime(entry, "%Y-%m-%d_%H%M%S")
        except ValueError:
            continue  # ليس مجلد نسخة بصيغتنا، لا نلمسه
        if folder_date < cutoff:
            logger.info(f"حذف نسخة قديمة تجاوزت سياسة الاحتفاظ ({retention_days} يوم): {full_path}")
            try:
                shutil.rmtree(full_path)
            except OSError as e:
                logger.error(f"فشل حذف {full_path}: {e}")


# ----------------------------------------------------------------------------
# Email
# ----------------------------------------------------------------------------
def send_email(subject: str, body: str, cfg: dict, logger: logging.Logger):
    e_cfg = cfg.get("email", {})
    if not e_cfg.get("enabled"):
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = e_cfg["from_addr"]
        msg["To"] = ", ".join(e_cfg["to_addrs"])
        with smtplib.SMTP(e_cfg["smtp_server"], e_cfg["smtp_port"], timeout=30) as server:
            server.starttls()
            server.login(e_cfg["username"], os.environ.get("BACKUP_SMTP_PASSWORD") or e_cfg.get("password", ""))
            server.sendmail(e_cfg["from_addr"], e_cfg["to_addrs"], msg.as_string())
        logger.info("تم إرسال إيميل التنبيه.")
    except Exception as e:
        logger.error(f"فشل إرسال الإيميل: {e}")


# ----------------------------------------------------------------------------
# Jobs planning + validation (منع تداخل المصادر والوجهات)
# ----------------------------------------------------------------------------
def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def _is_inside(child: str, parent: str) -> bool:
    """True لو child مساوٍ لـ parent أو بداخله (بدون حساسية لحالة الأحرف على ويندوز)."""
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def _overlaps(a: str, b: str) -> bool:
    return _is_inside(a, b) or _is_inside(b, a)


def plan_jobs(cfg: dict, timestamp_folder: str = None):
    """يحوّل الإعدادات إلى مهام (name, src, dst).
    - destination صريحة للمصدر: تُستخدم كما هي (تُنسخ محتوياته مباشرة إليها).
    - وإلا: target_root + مجلد باسم المصدر (مع منع تكرار الأسماء)، وبمجلد التاريخ لو مفعّل."""
    default_root = str(cfg.get("target_root") or "").strip()
    stamped = bool(cfg.get("timestamped_backup", False) and timestamp_folder)
    used_folder_names = {}
    jobs = []
    for item in cfg.get("sources") or []:
        name, src = item.get("name", ""), item.get("path", "")
        explicit = str(item.get("destination") or "").strip()
        if explicit:
            dst = explicit
        elif default_root:
            run_root = os.path.join(default_root, timestamp_folder) if stamped else default_root
            base_folder_name = os.path.basename(os.path.normpath(src)) or name
            count = used_folder_names.get(base_folder_name, 0)
            folder_name = base_folder_name if count == 0 else f"{base_folder_name}_{count + 1}"
            used_folder_names[base_folder_name] = count + 1
            dst = os.path.join(run_root, folder_name)
        else:
            dst = ""
        jobs.append({"name": name, "src": src, "dst": dst})
    return jobs


def collect_config_errors(cfg: dict):
    """يرجع قائمة بكل أخطاء الإعدادات (فارغة = سليمة)، قبل أي كتابة على القرص."""
    sources = cfg.get("sources")
    if not isinstance(sources, list) or not sources:
        return ["أضف مصدراً واحداً على الأقل قبل بدء النسخ."]

    errors, seen = [], set()
    if (cfg.get("robocopy") or {}).get("mirror"):
        errors.append("خيار mirror ممنوع: يحذف من الوجهة كل ما ليس في المصدر. "
                      "هذه الأداة لا تحذف أي ملف من الوجهة أبداً.")
    default_root = str(cfg.get("target_root") or "").strip()
    for item in sources:
        if not isinstance(item, dict):
            errors.append("صيغة أحد المصادر غير صحيحة.")
            continue
        name = str(item.get("name", "")).strip()
        src = str(item.get("path", "")).strip()
        if not name or not src:
            errors.append("كل مصدر يحتاج اسماً ومساراً صحيحين.")
            continue
        if name.casefold() in seen:
            errors.append(f"اسم المصدر مكرر: {name}")
        seen.add(name.casefold())
        if not (str(item.get("destination") or "").strip() or default_root):
            errors.append(f"لم تُحدد وجهة للمصدر: {name}")
    if errors:
        return errors

    jobs = plan_jobs(cfg)
    for i, a in enumerate(jobs):
        if _overlaps(a["src"], a["dst"]):
            errors.append(f"«{a['name']}»: المصدر والوجهة متداخلان (إحداهما داخل الأخرى):\n"
                          f"     المصدر: {a['src']}\n     الوجهة: {a['dst']}")
        for b in jobs[i + 1:]:
            if _overlaps(a["dst"], b["dst"]):
                errors.append(f"تداخل بين وجهتي «{a['name']}» و«{b['name']}» (ستختلط ملفاتهما):\n"
                              f"     {a['dst']}\n     {b['dst']}")
            if _overlaps(a["dst"], b["src"]):
                errors.append(f"وجهة «{a['name']}» تتداخل مع مصدر «{b['name']}»:\n"
                              f"     {a['dst']}\n     {b['src']}")
            if _overlaps(b["dst"], a["src"]):
                errors.append(f"وجهة «{b['name']}» تتداخل مع مصدر «{a['name']}»:\n"
                              f"     {b['dst']}\n     {a['src']}")
    return errors


def validate_config(cfg: dict) -> None:
    """يرفع ValueError برسالة تجمع كل الأخطاء لو الإعدادات غير سليمة."""
    errors = collect_config_errors(cfg)
    if errors:
        raise ValueError("\n\n".join(errors))


# ----------------------------------------------------------------------------
# Main run
# ----------------------------------------------------------------------------
def run_backup(cfg: dict, logger: logging.Logger, dry_run: bool = False, progress_callback=None):
    """
    ينفذ عملية نسخ احتياطي كاملة حسب الإعدادات المعطاة.
    progress_callback(source_name: str, percent: int, file_name: str = "") اختياري -
    يُستدعى دورياً بنسبة الإنجاز (0-100) لكل مصدر أثناء نسخه، و -1 أثناء التحقق.
    يمكن إيقافها بـ request_cancel().
    يرجع tuple: (overall_ok: bool, summary_text: str, run_target_root: str)
    يرفع ValueError لو الإعدادات غير سليمة (قبل أي كتابة على القرص).
    """
    validate_config(cfg)
    CANCEL.clear()
    logger.info("=" * 70)
    logger.info("بدء عملية النسخ الاحتياطي")
    logger.info("=" * 70)

    start_time = datetime.now()
    timestamp_folder = start_time.strftime("%Y-%m-%d_%H%M%S")
    stamped = cfg.get("timestamped_backup", False)

    target_base = str(cfg.get("target_root") or "").strip()
    run_target_root = os.path.join(target_base, timestamp_folder) if (stamped and target_base) else target_base

    jobs = plan_jobs(cfg, timestamp_folder)
    results = {}
    v_cfg = cfg.get("verification", {})
    verify_enabled = v_cfg.get("compare_file_count_and_size", False) or v_cfg.get("checksum_verify_sources")

    for job in jobs:
        name, src, dst = job["name"], job["src"], job["dst"]
        if CANCEL.is_set():
            results[name] = None  # لم يبدأ
            continue
        logger.info(f"[{name}] {src}  ->  {dst}")

        per_source_cb = (lambda pct, fname="", _name=name: progress_callback(_name, pct, fname)) if progress_callback else None
        copy_ok = backup_source_with_retry(name, src, dst, cfg, logger, dry_run, per_source_cb)
        verify_ok = True
        if copy_ok and not dry_run and not CANCEL.is_set() and verify_enabled:
            if progress_callback:
                progress_callback(name, -1, "تحقق")
            verify_ok = verify_backup(name, src, dst, cfg, logger)

        results[name] = (copy_ok, verify_ok)

    cancelled = CANCEL.is_set()

    # سياسة الاحتفاظ (فقط لو كل نسخة بمجلد بتاريخ)
    if stamped and cfg.get("retention_enabled", False) and target_base and not dry_run and not cancelled:
        apply_retention(target_base, cfg.get("retention_days", 30), logger)

    # ملخص
    duration = datetime.now() - start_time
    overall_ok = (not cancelled) and all(r is not None and r[0] and r[1] for r in results.values())

    summary_lines = [f"ملخص عملية النسخ الاحتياطي - {start_time:%Y-%m-%d %H:%M:%S}", ""]
    for job in jobs:
        name, r = job["name"], results[job["name"]]
        if r is None:
            summary_lines.append(f"  - {name}: ⏹ لم يبدأ (أُلغيت العملية)")
        elif cancelled and not r[0]:
            summary_lines.append(f"  - {name}: ⏹ أُلغي أثناء النسخ")
        else:
            ok, vok = r
            status = "✔ نجاح" if ok and vok else "✘ فشل"
            summary_lines.append(f"  - {name}: {status}  (نسخ: {'ناجح' if ok else 'فاشل'}, تحقق: {'ناجح' if vok else 'فاشل'})")
        summary_lines.append(f"      {job['src']}  ->  {job['dst']}")
    summary_lines.append("")
    summary_lines.append(f"المدة الكلية: {duration}")
    state = "أُلغيت بطلب المستخدم" if cancelled else ("نجاح كامل" if overall_ok else "يوجد فشل - راجع اللوج")
    summary_lines.append(f"الحالة العامة: {state}")
    summary_text = "\n".join(summary_lines)

    logger.info("\n" + summary_text)

    e_cfg = cfg.get("email", {})
    if not cancelled and ((overall_ok and e_cfg.get("send_on_success")) or (not overall_ok and e_cfg.get("send_on_failure"))):
        subject = "[Backup Tool] نجاح النسخ الاحتياطي" if overall_ok else "[Backup Tool] فشل النسخ الاحتياطي - يتطلب مراجعة"
        send_email(subject, summary_text, cfg, logger)

    return overall_ok, summary_text, run_target_root


def main():
    parser = argparse.ArgumentParser(description="أداة نسخ احتياطي للوثائق ونسخ قاعدة بيانات Jade")
    parser.add_argument("--config", default="config.yaml", help="مسار ملف الإعدادات")
    parser.add_argument("--dry-run", action="store_true", help="تجربة بدون نسخ فعلي (يعرض فقط ماذا سيحدث)")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    logger = setup_logging(cfg["logging"]["log_dir"], cfg["logging"]["keep_log_days"])
    try:
        overall_ok, _, _ = run_backup(cfg, logger, args.dry_run)
    except ValueError as e:
        logger.error("إعدادات غير صالحة:\n%s", e)
        sys.exit(2)
    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
