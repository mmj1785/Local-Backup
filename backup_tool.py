
import argparse
import hashlib
import logging
import logging.handlers
import os
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

    if rc_cfg.get("mirror"):
        args.append("/MIR")

    if rc_cfg.get("backup_mode"):
        args.append("/ZB")
    elif rc_cfg.get("restartable"):
        args.append("/Z")

    if dry_run:
        args.append("/L")
        logger.info("[DRY-RUN] لن يتم نسخ أي ملف فعلياً")

    logger.info(f"تنفيذ: {' '.join(args)}")

    sp_kwargs = _get_subprocess_kwargs()
    try:
        proc = subprocess.Popen(
            args,
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

    file_count = 0

    if progress_callback and not dry_run:
        progress_callback(5)

    # قراءة مخرجات Robocopy في الوقت الفعلي بدون أي استهلاك للموارد
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            # عند نسخ ملف جديد أو معدل يظهره Robocopy
            if any(marker in line for marker in ("New File", "Newer", "Older", "Changed", "*EXTRA")):
                file_count += 1
                parts = line.split()
                fname = parts[-1] if parts else line
                # اسم الملف فقط للاختصار
                short_name = os.path.basename(fname)
                if progress_callback:
                    # تحديث نسبي سلس
                    pct = min(95, 10 + (file_count * 3))
                    progress_callback(pct, short_name)
    except Exception as exc:
        logger.warning("تعذر قراءة تقدم Robocopy: %s", exc)

    proc.wait()
    exit_code = proc.returncode

    if progress_callback and not dry_run:
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
        logger.info(f"[{name}] محاولة {attempt}/{max_retries}: نسخ {src} -> {dst}")
        ok = run_robocopy(src, dst, cfg, logger, dry_run, progress_callback)
        if ok:
            return True
        if attempt < max_retries:
            logger.warning(f"[{name}] فشلت المحاولة {attempt}. الانتظار {wait_between} ثانية قبل إعادة المحاولة...")
            time.sleep(wait_between)

    logger.error(f"[{name}] فشلت كل المحاولات ({max_retries}).")
    return False


# ----------------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------------
def folder_stats(path: str):
    """يرجع (عدد الملفات، الحجم الكلي بالبايت) لمجلد."""
    total_files, total_size = 0, 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total_size += os.path.getsize(fp)
                total_files += 1
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
                        logger.warning(f"[{name}] اختلاف في الحجم للملف: {rel} (المصدر: {s_stat.st_size} بايت | الهدف: {d_stat.st_size} بايت)")
                        size_mismatches += 1
                        all_ok = False
                except OSError as e:
                    logger.warning(f"[{name}] تعذر قراءة بيانات الملف بالهدف {rel}: {e}")
                    all_ok = False

        if all_ok:
            logger.info(f"[{name}] تحقق ناجح: جميع ملفات المصدر ({checked_files} ملف، {total_src_size} بايت) موجودة ومتطابقة بالهدف.")
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
            server.login(e_cfg["username"], e_cfg["password"])
            server.sendmail(e_cfg["from_addr"], e_cfg["to_addrs"], msg.as_string())
        logger.info("تم إرسال إيميل التنبيه.")
    except Exception as e:
        logger.error(f"فشل إرسال الإيميل: {e}")


def validate_config(cfg: dict) -> None:
    """يتحقق من الإعدادات قبل أي كتابة على القرص.

    أهم قيد هنا هو منع جعل الوجهة داخل المصدر، لأن ذلك قد يحول النسخ إلى حلقة
    تتضخم فيها الملفات بلا نهاية.
    """
    sources = cfg.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("أضف مصدراً واحداً على الأقل قبل بدء النسخ.")
    if not str(cfg.get("target_root", "")).strip():
        raise ValueError("حدد مجلد النسخ الاحتياطي الرئيسي أولاً.")

    seen_names = set()
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError("صيغة أحد المصادر غير صحيحة.")
        name = str(item.get("name", "")).strip()
        src = str(item.get("path", "")).strip()
        dst = str(item.get("destination", "")).strip()
        if not name or not src:
            raise ValueError("كل مصدر يحتاج اسماً ومساراً صحيحين.")
        if name.casefold() in seen_names:
            raise ValueError(f"اسم المصدر مكرر: {name}")
        seen_names.add(name.casefold())

        # في الواجهة الوجهة صريحة، وفي ملفات CLI القديمة تحسب من target_root.
        effective_dst = dst or str(cfg.get("target_root", "")).strip()
        if not effective_dst:
            raise ValueError(f"لم تُحدد وجهة للمصدر: {name}")
        try:
            src_abs = os.path.abspath(src)
            dst_abs = os.path.abspath(effective_dst)
            if os.path.commonpath((src_abs, dst_abs)) == src_abs:
                raise ValueError(
                    f"الوجهة للمصدر «{name}» تقع داخل مجلد المصدر. اختر وجهة خارج المصدر."
                )
        except ValueError as exc:
            # Windows يرفع ValueError أيضاً لمسارات أقراص مختلفة؛ هذا آمن.
            if "تقع داخل" in str(exc):
                raise


# ----------------------------------------------------------------------------
# Main run
# ----------------------------------------------------------------------------
def run_backup(cfg: dict, logger: logging.Logger, dry_run: bool = False, progress_callback=None):
    """
    ينفذ عملية نسخ احتياطي كاملة حسب الإعدادات المعطاة.
    progress_callback(source_name: str, percent: int) اختياري - يُستدعى دورياً بنسبة
    الإنجاز الحالية (0-100) لكل مصدر أثناء نسخه.
    يرجع tuple: (overall_ok: bool, summary_text: str, run_target_root: str)
    """
    validate_config(cfg)
    logger.info("=" * 70)
    logger.info("بدء عملية النسخ الاحتياطي")
    logger.info("=" * 70)

    start_time = datetime.now()
    timestamp_folder = start_time.strftime("%Y-%m-%d_%H%M%S")

    target_base = cfg["target_root"]
    run_target_root = (
        os.path.join(target_base, timestamp_folder)
        if cfg.get("timestamped_backup", False)
        else target_base
    )

    results = {}
    used_folder_names = {}

    for src_cfg in cfg["sources"]:
        name, src = src_cfg["name"], src_cfg["path"]

        # دعم مجلد الوجهة الخاص بكل مصدر (destination)
        # إذا حُدِّد destination صراحةً يُستخدم مباشرةً، وإلا يُحسب تلقائياً
        explicit_dst = src_cfg.get("destination", "").strip()
        if explicit_dst:
            dst = explicit_dst
        else:
            base_folder_name = os.path.basename(os.path.normpath(src)) or name
            count = used_folder_names.get(base_folder_name, 0)
            folder_name = base_folder_name if count == 0 else f"{base_folder_name}_{count + 1}"
            used_folder_names[base_folder_name] = count + 1
            dst = os.path.join(run_target_root, folder_name)

        per_source_cb = (lambda pct, fname="", _name=name: progress_callback(_name, pct, fname)) if progress_callback else None
        copy_ok = backup_source_with_retry(name, src, dst, cfg, logger, dry_run, per_source_cb)
        verify_ok = True
        v_cfg = cfg.get("verification", {})
        if copy_ok and not dry_run and (v_cfg.get("compare_file_count_and_size", False) or v_cfg.get("checksum_verify_sources")):
            if progress_callback:
                progress_callback(name, -1, "تحقق")
            verify_ok = verify_backup(name, src, dst, cfg, logger)

        results[name] = (copy_ok, verify_ok)

    # سياسة الاحتفاظ (فقط لو كل نسخة بمجلد بتاريخ)
    if cfg.get("timestamped_backup", False) and not dry_run:
        apply_retention(target_base, cfg.get("retention_days", 30), logger)

    # ملخص
    duration = datetime.now() - start_time
    overall_ok = all(ok and vok for ok, vok in results.values())

    summary_lines = [f"ملخص عملية النسخ الاحتياطي - {start_time:%Y-%m-%d %H:%M:%S}", ""]
    for name, (ok, vok) in results.items():
        status = "✔ نجاح" if ok and vok else "✘ فشل"
        summary_lines.append(f"  - {name}: {status}  (نسخ: {'ناجح' if ok else 'فاشل'}, تحقق: {'ناجح' if vok else 'فاشل'})")
    summary_lines.append("")
    summary_lines.append(f"المدة الكلية: {duration}")
    summary_lines.append(f"الحالة العامة: {'نجاح كامل' if overall_ok else 'يوجد فشل - راجع اللوج'}")
    summary_text = "\n".join(summary_lines)

    logger.info("\n" + summary_text)

    e_cfg = cfg.get("email", {})
    if (overall_ok and e_cfg.get("send_on_success")) or (not overall_ok and e_cfg.get("send_on_failure")):
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
    overall_ok, _, _ = run_backup(cfg, logger, args.dry_run)
    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
