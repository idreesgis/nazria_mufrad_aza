"""Pulse texts in ur | en | ar: the disclaimer, the safe error messages and the main pulse characteristics.
The analyser's detailed technical fields stay in English."""
from __future__ import annotations

DISCLAIMER = {
    "en": "Pulse analysis from a phone camera is experimental and only supports an examination by a qualified "
          "practitioner; it is not a diagnosis.",
    "ur": "فون کیمرے سے نبض کا یہ تجزیہ تجرباتی ہے اور صرف کسی مستند معالج کے معائنے میں مدد دیتا ہے؛ یہ تشخیص نہیں ہے۔",
    "ar": "تحليل النبض بكاميرا الهاتف تجريبي، وهو يساعد فقط في فحص المعالج المؤهل، وليس تشخيصًا.",
}
# the stored error (English) → (ur, ar)
ERRORS = {
    "the video is too short or the finger was not detected": (
        "ویڈیو بہت چھوٹی ہے یا انگلی نظر نہیں آئی", "الفيديو قصير جدًا أو لم يُكتشف الإصبع"),
    "no pulse signal was found in the video": ("ویڈیو میں نبض کا سگنل نہیں ملا", "لم يُعثر على إشارة نبض في الفيديو"),
    "too few heartbeats were detected; keep the finger still on the lens": (
        "دل کی دھڑکنیں بہت کم ملیں؛ انگلی لینز پر بغیر ہلائے رکھیں",
        "اكتُشف عدد قليل جدًا من النبضات؛ أبقِ الإصبع ثابتًا على العدسة"),
    "the video file could not be read": ("ویڈیو فائل پڑھی نہیں جا سکی", "تعذّرت قراءة ملف الفيديو"),
    "the video could not be analysed": ("ویڈیو کا تجزیہ نہیں ہو سکا", "تعذّر تحليل الفيديو"),
}
CHARACTERISTICS = {
    "very regular": ("بہت منتظم", "منتظم جدًا"), "regular": ("منتظم", "منتظم"),
    "regular with occasional variations": ("منتظم، کبھی کبھار فرق کے ساتھ", "منتظم مع تغيرات عرضية"),
    "irregular with missed beats": ("غیر منتظم، دھڑکنیں چھوٹتی ہیں", "غير منتظم مع نبضات فائتة"),
    "strong and bounding": ("قوی اور اچھلتی ہوئی", "قوي ووثّاب"), "moderate to strong": ("معتدل سے قوی", "معتدل إلى قوي"),
    "moderate": ("معتدل", "معتدل"), "weak and thready": ("ضعیف اور باریک", "ضعيف وخيطي"),
    "full and expansive": ("بھری ہوئی اور پھیلی ہوئی", "ممتلئ وواسع"), "full": ("بھری ہوئی", "ممتلئ"),
    "normal": ("معمول کے مطابق", "طبيعي"), "thin and narrow": ("پتلی اور تنگ", "رفيع وضيق"),
    "high": ("زیادہ", "مرتفع"), "low": ("کم", "منخفض"),
    "consistently elevated": ("مسلسل تیز", "مرتفع باستمرار"),
    "steady with minor elevations": ("ہموار، معمولی تیزی کے ساتھ", "ثابت مع ارتفاعات طفيفة"),
    "steady and normal": ("ہموار اور معمول کے مطابق", "ثابت وطبيعي"), "slow and steady": ("سست اور ہموار", "بطيء وثابت"),
    "slow with variations": ("سست، فرق کے ساتھ", "بطيء مع تغيرات"),
}
_I = {"ur": 0, "ar": 1}


def error_text(error: str, lang: str) -> str:
    if not error or lang == "en" or error not in ERRORS:
        return error
    return ERRORS[error][_I[lang]]


def characteristic(value, lang: str):
    if not isinstance(value, str) or lang == "en" or value not in CHARACTERISTICS:
        return value
    return CHARACTERISTICS[value][_I[lang]]


def summary(result: dict, lang: str) -> dict | None:
    """The main findings in the requested language (None when there is no result)."""
    if not result:
        return None
    pc = result.get("pulse_characteristics") or {}
    return {"heart_rate_bpm": result.get("average_heart_rate_bpm"),
            **{k: characteristic(pc.get(k), lang) for k in ("rhythm", "strength", "volume", "tension", "rate_pattern")}}
