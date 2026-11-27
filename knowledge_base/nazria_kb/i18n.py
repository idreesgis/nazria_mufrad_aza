"""Languages of everything a patient sees: Urdu (ur, the source), English (en) and Arabic (ar).

Urdu stays the canonical text: the question bank, the CLI, the stored answers and the book are Urdu. Every fixed
Urdu string a patient can see has an English and an Arabic translation in ``CATALOG``; ``tr(text, lang)`` looks it up
and falls back to the Urdu text (e.g. a question a Hakeem added in the database, not translated yet).
``tests/test_i18n.py`` fails when a built-in string has no translation.

Book excerpts (topic description, recipe, dose, the chapter's diet note, fallback passages) are never machine
translated: they are shown in the original Urdu and marked as such, because a mistranslated recipe could harm.
"""
from __future__ import annotations

import re

LANGUAGES = ("ur", "en", "ar")
DEFAULT_LANGUAGE = "ur"
DIRECTION = {"ur": "rtl", "ar": "rtl", "en": "ltr"}
LANGUAGE_NAMES = {"ur": "اردو", "en": "English", "ar": "العربية"}
_IDX = {"en": 0, "ar": 1}


def normalize_lang(value: str | None) -> str | None:
    """'en', 'en-US', 'ar_SA', 'UR' → 'en' / 'ar' / 'ur'; anything else → None."""
    if not value:
        return None
    code = re.split(r"[-_;,\s]", value.strip().lower(), maxsplit=1)[0]
    return code if code in LANGUAGES else None


def from_accept_language(header: str | None) -> str | None:
    """The first supported language of an Accept-Language header, by quality."""
    if not header:
        return None
    items = []
    for i, part in enumerate(header.split(",")):
        bits = part.strip().split(";")
        q = 1.0
        for b in bits[1:]:
            if b.strip().startswith("q="):
                try:
                    q = float(b.strip()[2:])
                except ValueError:
                    q = 0.0
        items.append((-q, i, bits[0]))
    for _, _, tag in sorted(items):
        lang = normalize_lang(tag)
        if lang:
            return lang
    return None


# --------------------------------------------------------------------------- systems, tehreek, mizaj
SYSTEM_CODES = {"اعصابی": "nervous", "عضلاتی": "muscular", "غدی": "glandular"}
SYSTEM_NAMES = {"اعصابی": ("Nervous", "عصبي"), "عضلاتی": ("Muscular", "عضلي"), "غدی": ("Glandular", "غدّي")}


def system_code(system: str | None) -> str | None:
    return SYSTEM_CODES.get(system) if system else None


def system_name(system: str | None, lang: str) -> str | None:
    if not system or lang == "ur" or system not in SYSTEM_NAMES:
        return system
    return SYSTEM_NAMES[system][_IDX[lang]]


def tehreek_code(tehreek: str | None) -> str | None:
    return "_".join(SYSTEM_CODES[s] for s in tehreek.split()) if tehreek else None


def tehreek_name(tehreek: str | None, lang: str) -> str | None:
    if not tehreek or lang == "ur":
        return tehreek
    parts = [system_name(s, lang) for s in tehreek.split()]
    return "-".join(parts) if lang == "en" else " ".join(parts)


def sep(lang: str) -> str:
    return ", " if lang == "en" else "، "


def stop(lang: str) -> str:
    return "." if lang == "en" else ("۔" if lang == "ur" else ".")


# --------------------------------------------------------------------------- templates (with {placeholders})
MSG: dict[str, dict[str, str]] = {
    "thanks": {"ur": "شکریہ۔ آپ کے جوابات کی بنیاد پر:", "en": "Thank you. Based on your answers:",
               "ar": "شكرًا لك. بناءً على إجاباتك:"},
    "primary": {"ur": "• غالب نظام: {system} ({organs})", "en": "• Dominant system: {system} ({organs})",
                "ar": "• الجهاز الغالب: {system} ({organs})"},
    "tehreek": {"ur": "• اندازاً تحریک: «{tehreek}» — مزاج: {mizaj}",
                "en": "• Likely tehreek (excitation): «{tehreek}» — temperament (mizaj): {mizaj}",
                "ar": "• التحريك المرجّح: «{tehreek}» — المزاج: {mizaj}"},
    "evidence_head": {"ur": "• یہ نتیجہ ان علامات سے اخذ کیا گیا:", "en": "• This finding is based on these symptoms:",
                      "ar": "• استُخلصت هذه النتيجة من الأعراض التالية:"},
    "inconclusive": {"ur": "• آپ کے جوابات سے کوئی واضح تحریک ظاہر نہیں ہوتی۔ نبض اور قارورہ کا براہ راست معائنہ ضروری ہے۔",
                     "en": "• Your answers do not show a clear tehreek. A direct examination of the pulse and urine "
                           "is needed.",
                     "ar": "• لا تُظهر إجاباتك تحريكًا واضحًا. لا بد من فحص النبض والبول مباشرة."},
    "topic": {"ur": "«{title}» کے بارے میں:", "en": "About «{title}» (original text in Urdu):",
              "ar": "عن «{title}» (النص الأصلي بالأردية):"},
    "recipe": {"ur": "نسخہ:", "en": "Recipe (original text in Urdu):", "ar": "الوصفة (النص الأصلي بالأردية):"},
    "dosage": {"ur": "مقدار خوراک: ", "en": "Dose (in Urdu): ", "ar": "الجرعة (بالأردية): "},
    "topic_diet": {"ur": "اس تکلیف میں غذا کے بارے میں: ", "en": "Diet for this complaint (in Urdu): ",
                   "ar": "الغذاء في هذه الشكوى (بالأردية): "},
    "passages": {"ur": "اس موضوع پر متعلقہ معلومات:", "en": "Related information (original text in Urdu):",
                 "ar": "معلومات ذات صلة (النص الأصلي بالأردية):"},
    "nothing_found": {"ur": "اس تکلیف کے بارے میں کوئی واضح معلومات نہیں ملیں۔",
                      "en": "No clear information was found about this complaint.",
                      "ar": "لم يُعثر على معلومات واضحة عن هذه الشكوى."},
    "diet_title": {"ur": "غذائی پلان:", "en": "Diet plan:", "ar": "الخطة الغذائية:"},
    "diet_head": {"ur": "تحریک «{tehreek}» (مزاج: {mizaj})", "en": "Tehreek «{tehreek}» (temperament: {mizaj})",
                  "ar": "التحريك «{tehreek}» (المزاج: {mizaj})"},
    "diet_choose": {"ur": "{choose_if}، {head}:", "en": "{choose_if}: {head}", "ar": "{choose_if}: {head}"},
    "breakfast": {"ur": "• ناشتہ: ", "en": "• Breakfast: ", "ar": "• الفطور: "},
    "lunch": {"ur": "• دوپہر کا کھانا: ", "en": "• Lunch: ", "ar": "• الغداء: "},
    "dinner": {"ur": "• رات کا کھانا: ", "en": "• Dinner: ", "ar": "• العشاء: "},
    "fruits": {"ur": "• پھل: ", "en": "• Fruits: ", "ar": "• الفواكه: "},
    "dry_fruits": {"ur": "• میوہ جات: ", "en": "• Dry fruits and nuts: ", "ar": "• المكسرات والفواكه المجففة: "},
    "qehwa": {"ur": "• قہوہ: {name} ({ingredients})۔ {how}", "en": "• Qehwa (herbal tea): {name} ({ingredients}). {how}",
              "ar": "• القهوة العشبية: {name} ({ingredients}). {how}"},
    "diet_rules": {"ur": "غذا کے اصول:", "en": "Eating rules:", "ar": "قواعد الأكل:"},
    "explanation": {"ur": "وضاحت:", "en": "Explanation:", "ar": "الشرح:"},
}


def msg(key: str, lang: str, **kw) -> str:
    entry = MSG[key]
    return (entry.get(lang) or entry["ur"]).format(**kw)


# --------------------------------------------------------------------------- fixed Urdu strings → (en, ar)
_ROWS: list[tuple[str, str, str]] = [
    # ---- safety messages
    ("آپ نے جو علامت بتائی ہے وہ ہنگامی نوعیت کی ہو سکتی ہے۔ برائے مہربانی فوراً قریبی ہسپتال کی ایمرجنسی "
     "جائیں یا ایمبولینس کو کال کریں۔ اس حالت میں گھر پر کوئی دیسی دوا استعمال نہ کریں۔",
     "The symptom you described may be an emergency. Please go to the emergency department of the nearest hospital "
     "now or call an ambulance. Do not use any home or herbal remedy in this condition.",
     "قد يكون العَرَض الذي ذكرته حالة طارئة. يرجى التوجه فورًا إلى قسم الطوارئ في أقرب مستشفى أو الاتصال بالإسعاف. "
     "لا تستعمل أي علاج منزلي أو عشبي في هذه الحالة."),
    ("آپ اکیلے نہیں ہیں۔ براہ کرم ابھی کسی قریبی عزیز سے بات کریں اور فوراً قریبی ہسپتال یا ہنگامی سروس سے رابطہ کریں۔",
     "You are not alone. Please talk to someone close to you now, and contact the nearest hospital or emergency "
     "service immediately.",
     "لست وحدك. يرجى التحدث الآن إلى شخص قريب منك، والتواصل فورًا مع أقرب مستشفى أو خدمة طوارئ."),
    ("یہ نتیجہ نظریہ مفرد اعضاء کے مطابق آپ کی بتائی ہوئی علامات کی بنیاد پر صرف رہنمائی کے لیے ہے، یہ تشخیص نہیں ہے۔ "
     "حتمی تشخیص اور علاج کے لیے کسی مستند معالج سے نبض اور قارورہ کا معائنہ ضرور کروائیں۔",
     "This result, based on the symptoms you reported according to the theory of simple organs (Nazria Mufrad "
     "Aza), is for guidance only; it is not a diagnosis. For a final diagnosis and treatment, have your pulse and "
     "urine examined by a qualified practitioner.",
     "هذه النتيجة مبنية على الأعراض التي ذكرتها وفق نظرية الأعضاء المفردة، وهي للإرشاد فقط وليست تشخيصًا. "
     "للتشخيص النهائي والعلاج يرجى فحص النبض والبول لدى معالج مؤهل."),
    ("یہ وضاحت نظریہ مفرد اعضاء کی روشنی میں صرف رہنمائی کے لیے ہے، یہ تشخیص نہیں ہے۔ "
     "حتمی تشخیص اور علاج کے لیے کسی مستند معالج سے نبض اور قارورہ کا معائنہ ضرور کروائیں۔",
     "This explanation, in the light of the theory of simple organs, is for guidance only; it is not a diagnosis. "
     "For a final diagnosis and treatment, have your pulse and urine examined by a qualified practitioner.",
     "هذا الشرح في ضوء نظرية الأعضاء المفردة للإرشاد فقط وليس تشخيصًا. للتشخيص النهائي والعلاج يرجى فحص النبض "
     "والبول لدى معالج مؤهل."),
    ("اس تکلیف کے نسخے میں ایسے اجزاء ({items}) شامل ہیں جو غلط مقدار میں زہریلے "
     "ہو سکتے ہیں، اس لیے یہ نسخہ یہاں نہیں دکھایا جا رہا۔ یہ صرف مستند معالج کی نگرانی میں استعمال ہو سکتا ہے۔",
     "The recipe for this complaint contains ingredients ({items}) that can be poisonous in the wrong amount, so it "
     "is not shown here. It may only be used under the supervision of a qualified practitioner.",
     "تحتوي وصفة هذه الشكوى على مكونات ({items}) قد تكون سامة بالمقدار الخاطئ، لذلك لا تُعرض هنا. لا تُستعمل إلا "
     "تحت إشراف معالج مؤهل."),
    ("بچوں، حاملہ یا دودھ پلانے والی خواتین اور بزرگوں کے لیے یہاں کوئی نسخہ تجویز نہیں کیا جاتا۔ "
     "براہ کرم براہ راست کسی مستند معالج یا ڈاکٹر سے رجوع کریں۔",
     "No recipe is suggested here for children, pregnant or breast-feeding women, or the elderly. Please see a "
     "qualified practitioner or a doctor directly.",
     "لا تُقترح هنا أي وصفة للأطفال أو الحوامل أو المرضعات أو كبار السن. يرجى مراجعة معالج مؤهل أو طبيب مباشرة."),
    ("مریض کو پہلے سے گردے، جگر یا دل کی بیماری ہے، اس لیے یہاں کوئی نسخہ تجویز نہیں کیا جاتا۔ "
     "براہ کرم اپنے معالج سے براہ راست رجوع کریں۔",
     "The patient already has a kidney, liver or heart disease, so no recipe is suggested here. Please see your "
     "doctor directly.",
     "يعاني المريض من مرض في الكلى أو الكبد أو القلب، لذلك لا تُقترح هنا أي وصفة. يرجى مراجعة طبيبك مباشرة."),
    ("مریض پہلے سے دوائیں لے رہا ہے، یا اسے کسی چیز سے الرجی ہے: کوئی بھی دیسی نسخہ شروع کرنے سے پہلے "
     "اپنے معالج سے ضرور مشورہ کریں، کیونکہ دوائیں آپس میں اثر کر سکتی ہیں۔",
     "The patient is already taking medicines or has an allergy: consult your doctor before starting any herbal "
     "remedy, because medicines can interact.",
     "يتناول المريض أدوية أو لديه حساسية: استشر طبيبك قبل البدء بأي علاج عشبي، لأن الأدوية قد تتفاعل فيما بينها."),
    ("چونکہ تکلیف پرانی ہے، کسی مستند معالج سے باقاعدہ معائنہ ضرور کروائیں۔",
     "Because the complaint is long-standing, have a proper examination by a qualified practitioner.",
     "بما أن الشكوى مزمنة، يرجى إجراء فحص منتظم لدى معالج مؤهل."),
    ("جو معلومات مجھے ملیں ان میں آپ کے اس سوال کا واضح جواب موجود نہیں ہے۔ "
     "اس بارے میں براہ کرم کسی مستند معالج سے براہ راست رجوع کریں۔",
     "The information I found does not clearly answer this question. Please ask a qualified practitioner directly.",
     "المعلومات التي وجدتها لا تجيب بوضوح عن هذا السؤال. يرجى سؤال معالج مؤهل مباشرة."),
    ("اطلاع: آپ کے سوالات کے جواب کے لیے ایک بیرونی AI سروس ({provider}) استعمال ہو رہی ہے۔ "
     "آپ کا نام، فون نمبر، شناختی کارڈ نمبر اور ای میل بھیجنے سے پہلے حذف کر دیے جاتے ہیں، "
     "پھر بھی براہ کرم اپنی ذاتی معلومات نہ لکھیں۔",
     "Notice: an external AI service ({provider}) is used to answer. Your name, phone number, ID card number and "
     "e-mail are removed before anything is sent; still, please do not write personal details.",
     "تنبيه: تُستخدم خدمة ذكاء اصطناعي خارجية ({provider}) للإجابة. يُحذف اسمك ورقم هاتفك ورقم بطاقتك وبريدك "
     "الإلكتروني قبل الإرسال، ومع ذلك يرجى عدم كتابة بياناتك الشخصية."),
    # ---- organs, mizaj
    ("دماغ و اعصاب", "brain and nerves", "الدماغ والأعصاب"),
    ("قلب و عضلات", "heart and muscles", "القلب والعضلات"),
    ("جگر و غدد", "liver and glands", "الكبد والغدد"),
    ("سرد تر", "cold and moist", "بارد رطب"), ("تر گرم", "moist and hot", "رطب حار"),
    ("سرد خشک", "cold and dry", "بارد يابس"), ("خشک گرم", "dry and hot", "يابس حار"),
    ("گرم خشک", "hot and dry", "حار يابس"), ("گرم تر", "hot and moist", "حار رطب"),
    # ---- hazard names
    ("سنکھیا/سم الفار", "arsenic", "الزرنيخ"), ("پارہ/شنگرف", "mercury / cinnabar", "الزئبق / الزنجفر"),
    ("نیلا طوطیہ", "copper sulphate", "كبريتات النحاس"), ("سرب", "lead", "الرصاص"),
    ("بچھناگ", "aconite", "خانق الذئب"), ("کچلہ", "nux vomica", "جوز القيء"), ("دھتورا", "datura", "الداتورة"),
    ("افیون", "opium", "الأفيون"), ("بھنگ", "cannabis", "القنب"), ("اجوائن خراسانی", "henbane", "البنج"),
    ("جمال گوٹہ", "croton seed", "حب الملوك"), ("کشتہ جات", "calcined metals (kushta)", "الكشتات (المعادن المكلسة)"),
    ("کنیر", "oleander", "الدفلى"), ("شوکران", "hemlock", "الشوكران"),
    # ---- red flags (question options and free-text codes)
    ("سینے میں شدید درد یا دباؤ", "Severe chest pain or pressure", "ألم شديد أو ضغط في الصدر"),
    ("سانس لینے میں شدید دشواری", "Severe difficulty breathing", "صعوبة شديدة في التنفس"),
    ("بے ہوشی، دورہ (جھٹکے) یا شدید غنودگی", "Fainting, a fit (convulsions) or severe drowsiness",
     "إغماء أو نوبة (تشنجات) أو نعاس شديد"),
    ("چہرہ ٹیڑھا ہونا، بازو/ٹانگ اچانک کمزور ہونا یا بولنے میں دقت",
     "Face drooping, sudden weakness of an arm or leg, or difficulty speaking",
     "تدلّي الوجه أو ضعف مفاجئ في الذراع أو الساق أو صعوبة في الكلام"),
    ("خون کی قے، پاخانے میں کالا یا تازہ خون، یا شدید خون بہنا",
     "Vomiting blood, black or fresh blood in the stool, or heavy bleeding",
     "تقيؤ الدم أو دم أسود أو طازج في البراز أو نزيف شديد"),
    ("تیز بخار کے ساتھ گردن اکڑ جانا یا جسم پر سرخ دھبے", "High fever with a stiff neck or a red rash on the body",
     "حمى شديدة مع تيبّس الرقبة أو بقع حمراء على الجسم"),
    ("حمل کے دوران خون آنا یا پیٹ میں شدید درد", "Bleeding or severe abdominal pain during pregnancy",
     "نزيف أو ألم شديد في البطن أثناء الحمل"),
    ("پانچ سال سے کم عمر بچے میں تیز بخار یا پانی کی شدید کمی",
     "High fever or severe dehydration in a child under five", "حمى شديدة أو جفاف شديد لدى طفل دون الخامسة"),
    ("خود کو نقصان پہنچانے کے خیالات", "Thoughts of harming yourself", "أفكار لإيذاء النفس"),
    ("ان میں سے کوئی نہیں", "None of these", "لا شيء مما سبق"),
    ("زہر یا دوا کی زیادہ مقدار کھا لینا", "Poisoning or a medicine overdose", "تسمم أو جرعة زائدة من دواء"),
    ("اچانک شدید سر درد", "Sudden severe headache", "صداع شديد مفاجئ"),
    ("چہرے، ہونٹوں یا گلے کی سوجن کے ساتھ سانس کی دشواری",
     "Swelling of the face, lips or throat with difficulty breathing",
     "تورّم الوجه أو الشفتين أو الحلق مع صعوبة في التنفس"),
    ("پیٹ میں شدید درد", "Severe abdominal pain", "ألم شديد في البطن"),
    # ---- questions and options
    ("پہلے یہ بتائیں: کیا آپ کو ان میں سے کوئی علامت ہے؟ (جو لاگو ہوں ان کے نمبر لکھیں)",
     "First: do you have any of these symptoms? (choose all that apply)",
     "أولًا: هل لديك أي من هذه الأعراض؟ (اختر كل ما ينطبق)"),
    ("اپنی بنیادی تکلیف مختصراً بتائیں (مثلاً قبض، کھانسی، نزلہ، بخار، دمہ)۔",
     "Briefly describe your main complaint (for example constipation, cough, catarrh, fever, asthma).",
     "صِف شكواك الرئيسية باختصار (مثل الإمساك أو السعال أو الزكام أو الحمى أو الربو)."),
    ("یہ تکلیف کب سے ہے؟", "How long have you had this complaint?", "منذ متى وأنت تعاني من هذه الشكوى؟"),
    ("چند دن سے", "For a few days", "منذ بضعة أيام"), ("چند ہفتوں سے", "For a few weeks", "منذ بضعة أسابيع"),
    ("کئی مہینوں سے یا پرانی ہے", "For many months, or it is long-standing", "منذ عدة أشهر أو أنها مزمنة"),
    ("آپ کی عمر؟", "Your age?", "عمرك؟"), ("12 سال سے کم", "Under 12 years", "أقل من 12 سنة"),
    ("12 سے 60 سال", "12 to 60 years", "من 12 إلى 60 سنة"), ("60 سال سے زیادہ", "Over 60 years", "أكثر من 60 سنة"),
    ("کیا آپ حاملہ ہیں یا بچے کو دودھ پلاتی ہیں؟", "Are you pregnant or breast-feeding?", "هل أنتِ حامل أو مرضع؟"),
    ("ہاں", "Yes", "نعم"), ("نہیں", "No", "لا"), ("لاگو نہیں", "Not applicable", "لا ينطبق"),
    ("آپ کے پیشاب (قارورہ) کا رنگ عام طور پر کیسا رہتا ہے؟", "What colour is your urine usually?",
     "ما لون بولك عادةً؟"),
    ("سرخ یا سرخی مائل", "Red or reddish", "أحمر أو مائل إلى الحمرة"),
    ("زرد یا زردی مائل", "Yellow or yellowish", "أصفر أو مائل إلى الصفرة"),
    ("سفید یا سفیدی مائل", "White or whitish", "أبيض أو مائل إلى البياض"),
    ("معلوم نہیں / ایسا کچھ نہیں", "Don't know / nothing like this", "لا أعرف / لا شيء من هذا"),
    ("اجابت (پاخانہ) کی کیا کیفیت ہے؟", "How are your bowel movements?", "كيف حال التبرّز لديك؟"),
    ("قبض رہتی ہے، اکثر شدید یا پرانی", "Constipation, often severe or long-standing",
     "إمساك، غالبًا شديد أو مزمن"),
    ("پاخانہ تسلی سے نہیں ہوتا، مروڑ یا پیچش", "Incomplete stools, cramps or dysentery",
     "تبرّز غير كامل أو مغص أو زحار"),
    ("اسہال یا پتلا پاخانہ", "Diarrhoea or loose stools", "إسهال أو براز ليّن"),
    ("معمول کے مطابق", "Normal", "طبيعي"),
    ("اپنے جسم کی عمومی کیفیت کیسی محسوس کرتے ہیں؟", "How does your body generally feel?",
     "كيف تشعر بجسمك عمومًا؟"),
    ("جسم میں خشکی، دبلا پن", "Dryness in the body, thinness", "جفاف في الجسم ونحافة"),
    ("جسم میں حرارت، ہاتھ پاؤں جلتے ہیں", "Heat in the body, burning hands and feet",
     "حرارة في الجسم وحرقان في اليدين والقدمين"),
    ("بلغم زیادہ، جسم بھاری یا موٹا", "Much phlegm, a heavy or overweight body", "بلغم كثير وجسم ثقيل أو بدين"),
    ("پیٹ کی کیا کیفیت رہتی ہے؟", "How is your stomach usually?", "كيف حال بطنك عادةً؟"),
    ("گیس (ریاح) اور اپھارہ زیادہ", "Much gas and bloating", "غازات وانتفاخ كثير"),
    ("کھانے کے بعد حرارت بڑھ جاتی ہے یا پیٹ میں رکاوٹ محسوس ہوتی ہے",
     "Heat rises after eating, or the stomach feels blocked", "تزداد الحرارة بعد الأكل أو يُحس بانسداد في البطن"),
    ("منہ کا ذائقہ عام طور پر کیسا رہتا ہے؟", "What does your mouth usually taste like?", "ما طعم فمك عادةً؟"),
    ("ترش (کھٹا)", "Sour", "حامض"), ("میٹھا", "Sweet", "حلو"), ("کڑوا", "Bitter", "مر"),
    ("کیا دل گھبراتا ہے یا دھڑکن تیز رہتی ہے؟", "Do you feel anxious at heart, or is your heartbeat fast?",
     "هل تشعر بضيق في القلب أو بسرعة في نبضاته؟"),
    ("کیا پیشاب میں جلن ہوتی ہے؟", "Do you have burning when passing urine?", "هل تشعر بحرقة عند التبول؟"),
    ("کیا نزلہ، سر درد یا جسم میں سوجن اکثر رہتی ہے؟", "Do you often have catarrh, headache or swelling in the body?",
     "هل تعاني كثيرًا من الزكام أو الصداع أو تورّم في الجسم؟"),
    ("اگر بلغم آتا ہے تو کیسا ہے؟", "If you bring up phlegm, what is it like?", "إن كان لديك بلغم، فكيف هو؟"),
    ("گاڑھا، مشکل سے نکلتا ہے", "Thick, hard to bring up", "كثيف ويصعب إخراجه"),
    ("زردی مائل", "Yellowish", "مائل إلى الصفرة"),
    ("بہت زیادہ رطوبت، اعضاء ڈھیلے محسوس ہوتے ہیں", "A lot of fluid, the limbs feel slack",
     "رطوبة كثيرة جدًا والأطراف تبدو مرتخية"),
    ("بلغم نہیں آتا", "No phlegm", "لا يوجد بلغم"),
    ("بھوک کیسی رہتی ہے؟", "How is your appetite?", "كيف شهيتك؟"),
    ("بھوک بالکل نہیں لگتی، کھانے کو جی نہیں چاہتا (جوع البقر)",
     "No appetite at all, no wish to eat (loss of appetite)", "لا شهية إطلاقًا ولا رغبة في الأكل (جوع البقر)"),
    ("بہت بھوک لگتی ہے، کھانے کے بعد بھی پیٹ نہیں بھرتا (جوع الکلب)",
     "Very hungry, still not full after eating (excessive hunger)", "جوع شديد ولا شبع حتى بعد الأكل (جوع الكلب)"),
    ("پیاس کیسی رہتی ہے؟", "How is your thirst?", "كيف حال العطش لديك؟"),
    ("بہت پیاس لگتی ہے اور پانی پینے سے بھی نہیں بجھتی", "Very thirsty, and drinking water does not quench it",
     "عطش شديد لا يرويه شرب الماء"),
    ("اگر جسم میں درد رہتا ہے تو کب بڑھتا ہے؟", "If you have pain in the body, when does it get worse?",
     "إن كان لديك ألم في الجسم، فمتى يزداد؟"),
    ("حرکت کرنے سے بڑھتا ہے، آرام سے سکون ملتا ہے", "Worse with movement, eased by rest",
     "يزداد بالحركة ويخفّ بالراحة"),
    ("آرام کرنے سے بڑھتا ہے، چلنے پھرنے سے سکون ملتا ہے", "Worse at rest, eased by moving about",
     "يزداد بالراحة ويخفّ بالحركة"),
    ("درد نہیں رہتا", "No pain", "لا يوجد ألم"),
    ("جوڑوں کی کیا کیفیت ہے؟", "How are your joints?", "كيف حال مفاصلك؟"),
    ("سوجن زیادہ اور درد کم، خاص طور پر بڑے جوڑوں میں (وجع المفاصل)",
     "More swelling than pain, especially in large joints (arthritis)",
     "تورّم أكثر من الألم، خاصة في المفاصل الكبيرة (وجع المفاصل)"),
    ("شدید درد مگر سوجن نہیں، چھوٹے جوڑوں سے شروع ہوتا ہے (نقرس)",
     "Severe pain without swelling, starting in the small joints (gout)",
     "ألم شديد بلا تورّم يبدأ في المفاصل الصغيرة (النقرس)"),
    ("جوڑ اکڑ جاتے ہیں اور سخت ہو جاتے ہیں (تحجر المفاصل)", "The joints stiffen and harden (joint stiffening)",
     "تتيبّس المفاصل وتتصلّب (تحجّر المفاصل)"),
    ("جوڑوں میں کوئی تکلیف نہیں", "No trouble in the joints", "لا توجد مشكلة في المفاصل"),
    ("جلد پر ان میں سے کیا ہے؟ (جو لاگو ہوں)", "Which of these do you have on the skin? (choose all that apply)",
     "أيّ هذه لديك على الجلد؟ (اختر كل ما ينطبق)"),
    ("جلد پھٹتی ہے، جیسے ایڑیاں یا ہاتھ (شقاق)", "Cracking skin, such as on the heels or hands (fissures)",
     "تشقق الجلد كما في الكعبين أو اليدين (الشقاق)"),
    ("خشک کھردرے دھبے جن میں خارش ہو اور چھلکے اتریں (داد)", "Dry, rough, itchy patches that flake (ringworm-like)",
     "بقع جافة خشنة تسبب الحكة وتتقشّر (القوباء)"),
    ("چہرے پر کیل مہاسے", "Acne on the face", "حب الشباب على الوجه"),
    ("جسم پر سرخ ابھار جن میں خارش ہو (شری، پتی اچھلنا)", "Itchy red wheals on the body (urticaria, hives)",
     "انتفاخات حمراء مثيرة للحكة على الجسم (الشَّرى)"),
    ("سرخ یا زردی مائل جلن والی پھنسیاں یا پھوڑے (جمرہ، دمل)", "Red or yellowish burning pimples or boils",
     "بثور أو دمامل حمراء أو مائلة للصفرة مع حرقة (الجمرة، الدمل)"),
    ("جلد پر سفید داغ (برص)", "White patches on the skin (vitiligo)", "بقع بيضاء على الجلد (البرص)"),
    ("بالوں کی کیا کیفیت ہے؟", "How is your hair?", "كيف حال شعرك؟"),
    ("وقت سے پہلے سفید ہو رہے ہیں", "Turning grey early", "يشيب قبل أوانه"),
    ("تیزی سے گر رہے ہیں (داء الثعلب)", "Falling out fast (alopecia)", "يتساقط بسرعة (داء الثعلب)"),
    ("آج کل طبیعت پر کون سی کیفیت زیادہ رہتی ہے؟", "Which feeling is strongest in you these days?",
     "أيّ شعور يغلب عليك هذه الأيام؟"),
    ("ڈر، خوف یا گھبراہٹ", "Fear, dread or nervousness", "خوف أو رهبة أو قلق"),
    ("غم اور اداسی", "Grief and sadness", "حزن وكآبة"),
    ("ان میں سے کوئی خاص نہیں", "Nothing in particular", "لا شيء بعينه"),
    ("ان میں سے کیا اکثر ہوتا ہے؟ (جو لاگو ہوں)", "Which of these happen often? (choose all that apply)",
     "أيّ هذه يحدث لك كثيرًا؟ (اختر كل ما ينطبق)"),
    ("سر چکراتا ہے (دوار)", "Dizziness (vertigo)", "دوار"),
    ("ہاتھ پاؤں کانپتے ہیں (رعشہ)", "Trembling hands or feet (tremor)", "ارتعاش اليدين أو القدمين (الرعشة)"),
    ("رات کو کم دکھائی دیتا ہے (شب کوری)", "Poor vision at night (night blindness)", "ضعف الرؤية ليلًا (العشى الليلي)"),
    ("چھینکیں بہت آتی ہیں (عطاس)", "Frequent sneezing", "عطاس كثير"),
    ("آواز بیٹھ جاتی ہے", "Hoarse voice", "بحّة في الصوت"),
    ("ہچکی بار بار آتی ہے (فواق)", "Frequent hiccups", "فُواق (حازوقة) متكرر"),
    ("متلی یا قے", "Nausea or vomiting", "غثيان أو قيء"),
    ("نیند میں پیشاب نکل جاتا ہے (بول فی الفراش)", "Passing urine during sleep (bedwetting)",
     "التبول أثناء النوم (البول في الفراش)"),
    # ---- diet: foods
    ("لسی", "lassi (buttermilk)", "اللبن الرائب المخفوق (لسّي)"),
    ("جوار یا باجرے کی روٹی", "sorghum or millet bread", "خبز الذرة الرفيعة أو الدخن"),
    ("لوبیا", "black-eyed beans", "اللوبياء"), ("آلو مٹر", "potatoes with peas", "البطاطا مع البازلاء"),
    ("گوبھی یا بینگن", "cauliflower or aubergine", "القرنبيط أو الباذنجان"),
    ("مچھلی یا بھینس کا گوشت (یا سری پائے)", "fish or buffalo meat (or head-and-trotters broth)",
     "السمك أو لحم الجاموس (أو الرأس والكوارع)"),
    ("اروی یا آلو کی سبزی", "taro or potato curry", "القلقاس أو البطاطا مطبوخة"),
    ("سیب", "apple", "التفاح"), ("جامن", "jamun (Java plum)", "الجامون (برقوق جاوة)"),
    ("فالسہ", "phalsa berries", "الفالسا"), ("انناس", "pineapple", "الأناناس"), ("سنگترہ", "orange", "البرتقال"),
    ("آلوچہ", "plum", "البرقوق"), ("بیر", "jujube (ber)", "النبق"), ("ترش آڑو", "sour peach", "الخوخ الحامض"),
    ("مونگ پھلی", "peanuts", "الفول السوداني"),
    ("کھجور خشک یا انجیر", "dried dates or figs", "التمر المجفف أو التين"), ("اخروٹ", "walnuts", "الجوز"),
    ("پالک یا سرسوں کا ساگ", "spinach or mustard greens", "السبانخ أو أوراق الخردل"),
    ("کریلے", "bitter gourd", "القرع المر"), ("پیاز", "onion", "البصل"),
    ("گائے یا کبوتر کا گوشت", "beef or pigeon meat", "لحم البقر أو الحمام"),
    ("شلجم کی سبزی", "turnip curry", "اللفت مطبوخًا"), ("شیریں آڑو", "sweet peach", "الخوخ الحلو"),
    ("کھجور", "dates", "التمر"), ("انجیر", "figs", "التين"), ("پستہ", "pistachios", "الفستق"),
    ("کشمش", "raisins", "الزبيب"), ("منقی", "large raisins (munaqqa)", "الزبيب الكبير (المنقّى)"),
    ("خشک انجیر", "dried figs", "التين المجفف"), ("خشک کھجور", "dried dates", "التمر المجفف"),
    ("انڈے", "eggs", "البيض"), ("چنے", "chickpeas", "الحمص"),
    ("چنے کی دال یا سالن", "split chickpea lentils or chickpea curry", "عدس الحمص أو الحمص المطبوخ"),
    ("میتھی کا ساگ", "fenugreek greens", "أوراق الحلبة"),
    ("ادرک، لہسن اور پیاز کے ساتھ", "with ginger, garlic and onion", "مع الزنجبيل والثوم والبصل"),
    ("بکری یا دیسی مرغی کا گوشت", "goat meat or free-range chicken", "لحم الماعز أو الدجاج البلدي"),
    ("آم", "mango", "المانجو"), ("شیریں خوبانی", "sweet apricot", "المشمش الحلو"),
    ("آلو بخارا", "prunes (aloo bukhara)", "البرقوق المجفف (آلو بخارا)"), ("شہتوت", "mulberries", "التوت"),
    ("چلغوزہ", "pine nuts", "الصنوبر"),
    ("بکری کا دودھ", "goat's milk", "حليب الماعز"), ("گندم کی روٹی یا دلیہ", "wheat bread or porridge",
                                                          "خبز القمح أو العصيدة"),
    ("مونگ کی دال", "mung lentils", "عدس الماش"), ("بھنڈی", "okra", "البامية"),
    ("گندم کی روٹی", "wheat bread", "خبز القمح"),
    ("بٹیر، تیتر یا بطخ کا گوشت", "quail, partridge or duck meat", "لحم السمان أو الحجل أو البط"),
    ("شیریں انگور", "sweet grapes", "العنب الحلو"), ("خربوزہ", "melon", "الشمام"), ("بادام", "almonds", "اللوز"),
    ("گائے کا دودھ", "cow's milk", "حليب البقر"), ("ساگودانہ", "sago", "الساغو"),
    ("ماش کی دال", "black gram (urad) lentils", "عدس الماش الأسود"),
    ("کدو یا لوکی", "pumpkin or bottle gourd", "اليقطين أو القرع"), ("گاجر", "carrots", "الجزر"),
    ("لوکی یا حلوا کدو کی سبزی", "bottle gourd or sweet pumpkin curry", "القرع أو اليقطين الحلو مطبوخًا"),
    ("مولی", "radish", "الفجل"), ("ضرورت ہو تو مچھلی (گوشت نہیں)", "fish if needed (no meat)",
                                  "السمك عند الحاجة (بدون لحم)"),
    ("ناشپاتی", "pears", "الكمثرى"), ("شیریں کیلا", "sweet bananas", "الموز الحلو"),
    ("زرد امرود", "yellow guava", "الجوافة الصفراء"),
    ("بھینس کا دودھ", "buffalo milk", "حليب الجاموس"), ("انڈے کی سفیدی", "egg whites", "بياض البيض"),
    ("چاول", "rice", "الأرز"), ("کھیرا اور ککڑی", "cucumber", "الخيار والقثاء"),
    ("شلجم یا چقندر", "turnip or beetroot", "اللفت أو الشمندر"),
    ("مچھلی یا سری پائے، بغیر نمک مرچ کے (گوشت نہیں)",
     "fish or head-and-trotters broth, without salt or chilli (no meat)",
     "السمك أو الرأس والكوارع بدون ملح أو فلفل (بدون لحم)"),
    ("چقندر یا شلجم کی سبزی", "beetroot or turnip curry", "الشمندر أو اللفت مطبوخًا"),
    # ---- diet: qehwa
    ("املی کا قہوہ", "tamarind qehwa", "قهوة التمر الهندي"),
    ("املی ایک چھوٹا ٹکڑا", "a small piece of tamarind", "قطعة صغيرة من التمر الهندي"),
    ("ایک کپ پانی میں املی ڈال کر پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔",
     "Boil the tamarind in a cup of water for five minutes, strain, and drink it lukewarm.",
     "اغلِ التمر الهندي في كوب ماء خمس دقائق، ثم صفِّه واشربه فاترًا."),
    ("دارچینی اور لونگ کا قہوہ", "cinnamon and clove qehwa", "قهوة القرفة والقرنفل"),
    ("دارچینی کا ایک چھوٹا ٹکڑا", "a small piece of cinnamon", "قطعة صغيرة من القرفة"),
    ("دو لونگ", "two cloves", "حبتا قرنفل"),
    ("ایک کپ پانی میں دارچینی اور لونگ ڈال کر پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔",
     "Boil the cinnamon and cloves in a cup of water for five minutes, strain, and drink it lukewarm.",
     "اغلِ القرفة والقرنفل في كوب ماء خمس دقائق، ثم صفِّه واشربه فاترًا."),
    ("اجوائن کا قہوہ", "carom (ajwain) qehwa", "قهوة الكمون الملوكي (النانخة)"),
    ("دیسی اجوائن آدھا چائے کا چمچ", "half a teaspoon of carom seeds", "نصف ملعقة صغيرة من بذور النانخة"),
    ("ایک کپ پانی میں اجوائن ڈال کر پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔",
     "Boil the carom seeds in a cup of water for five minutes, strain, and drink it lukewarm.",
     "اغلِ بذور النانخة في كوب ماء خمس دقائق، ثم صفِّه واشربه فاترًا."),
    ("ادرک اور ہلدی کا قہوہ", "ginger and turmeric qehwa", "قهوة الزنجبيل والكركم"),
    ("ادرک کا چھوٹا ٹکڑا یا سونٹھ ایک چٹکی", "a small piece of ginger, or a pinch of dried ginger",
     "قطعة صغيرة من الزنجبيل أو رشة من الزنجبيل المجفف"),
    ("ہلدی ایک چٹکی", "a pinch of turmeric", "رشة من الكركم"),
    ("ایک کپ پانی میں ادرک اور ہلدی ڈال کر پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔",
     "Boil the ginger and turmeric in a cup of water for five minutes, strain, and drink it lukewarm.",
     "اغلِ الزنجبيل والكركم في كوب ماء خمس دقائق، ثم صفِّه واشربه فاترًا."),
    ("چھوٹی الائچی کا قہوہ", "green cardamom qehwa", "قهوة الهيل الأخضر"),
    ("دو چھوٹی الائچی", "two green cardamoms", "حبتا هيل أخضر"),
    ("ایک کپ پانی میں الائچی کچل کر ڈالیں، پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔",
     "Crush the cardamom into a cup of water, boil for five minutes, strain, and drink it lukewarm.",
     "اسحق الهيل وضعه في كوب ماء، واغلِه خمس دقائق، ثم صفِّه واشربه فاترًا."),
    ("بڑی الائچی کا قہوہ", "black cardamom qehwa", "قهوة الهيل الأسود"),
    ("ایک بڑی الائچی", "one black cardamom", "حبة هيل أسود واحدة"),
    ("ایک کپ پانی میں بڑی الائچی کچل کر ڈالیں، پانچ منٹ ابالیں، چھان کر نیم گرم پی لیں۔",
     "Crush the black cardamom into a cup of water, boil for five minutes, strain, and drink it lukewarm.",
     "اسحق الهيل الأسود وضعه في كوب ماء، واغلِه خمس دقائق، ثم صفِّه واشربه فاترًا."),
    # ---- diet: rules, notes, choices
    ("کھانا صرف اصل بھوک لگنے پر اور مقررہ وقت پر کھائیں؛ دو کھانوں کے درمیان کم از کم چھ گھنٹے کا وقفہ رکھیں۔",
     "Eat only when truly hungry and at set times; keep at least six hours between two meals.",
     "لا تأكل إلا عند الجوع الحقيقي وفي أوقات محددة، واترك ست ساعات على الأقل بين الوجبتين."),
    ("اس پلان کی غذائیں آپس میں ملا سکتے ہیں، مگر دوسری قسم کی غذائیں ان کے ساتھ نہ ملائیں۔",
     "You may combine the foods of this plan, but do not mix them with other kinds of food.",
     "يمكنك الجمع بين أطعمة هذه الخطة، لكن لا تخلطها بأنواع أخرى من الطعام."),
    ("غذا تازہ ہو اور اچھی طرح گلا کر پکائی جائے؛ باسی کھانا نہ کھائیں۔",
     "Food should be fresh and cooked until soft; do not eat stale food.",
     "ليكن الطعام طازجًا ومطبوخًا جيدًا حتى ينضج، ولا تأكل الطعام البائت."),
    ("تھکن کی حالت میں کھانا نہ کھائیں، پہلے آرام کریں۔", "Do not eat when tired; rest first.",
     "لا تأكل وأنت متعب، استرح أولًا."),
    ("پیٹ بوجھل ہو یا گیس اور بے چینی ہو تو کھانا چھوڑ دیں؛ کمزوری ہو تو قہوہ، پھلوں کا رس یا ہلکا شوربہ لیں۔",
     "If the stomach feels heavy, or there is gas and discomfort, skip the meal; if you feel weak, take qehwa, fruit "
     "juice or a light broth.",
     "إذا كانت المعدة ثقيلة أو فيها غازات وانزعاج فاترك الوجبة، وإذا شعرت بالضعف فتناول قهوة عشبية أو عصير فاكهة "
     "أو مرقًا خفيفًا."),
    ("قہوہ دن میں ایک یا دو بار، کھانے کے بعد نیم گرم پئیں؛ قہوے میں لیموں بھی نچوڑ سکتے ہیں۔",
     "Drink the qehwa lukewarm once or twice a day, after meals; you may squeeze lemon into it.",
     "اشرب القهوة العشبية فاترة مرة أو مرتين يوميًا بعد الوجبات، ويمكنك أن تعصر فيها الليمون."),
    ("اس حالت میں میوہ جات نہ لیں۔", "Do not take dry fruits or nuts in this state.",
     "لا تتناول المكسرات والفواكه المجففة في هذه الحالة."),
    ("اس حالت میں پھل کم سے کم لیں؛ اوپر دی گئی غذاؤں پر ہی رہیں۔",
     "Keep fruit to a minimum in this state; stay with the foods above.",
     "قلّل الفاكهة إلى أدنى حد في هذه الحالة والتزم بالأطعمة المذكورة أعلاه."),
    ("شوگر کی وجہ سے میٹھے پھل، کھجور، کشمش، منقی اور ساگودانہ بہت کم لیں، اور قہوہ بغیر چینی کے پئیں۔",
     "Because of diabetes, take very little sweet fruit, dates, raisins and sago, and drink the qehwa without sugar.",
     "بسبب السكري، تناول القليل جدًا من الفواكه الحلوة والتمر والزبيب والساغو، واشرب القهوة العشبية بلا سكر."),
    ("بلند فشار خون کی وجہ سے نمک کم استعمال کریں۔", "Because of high blood pressure, use less salt.",
     "بسبب ارتفاع ضغط الدم، قلّل من الملح."),
    ("گردے، جگر یا دل کی بیماری کی وجہ سے غذا میں بڑی تبدیلی سے پہلے اپنے معالج سے مشورہ کریں۔",
     "Because of kidney, liver or heart disease, ask your doctor before any big change in diet.",
     "بسبب مرض الكلى أو الكبد أو القلب، استشر طبيبك قبل أي تغيير كبير في الغذاء."),
    ("جس چیز سے الرجی ہو وہ نہ لیں؛ دوائیں چل رہی ہوں تو قہوہ شروع کرنے سے پہلے معالج سے پوچھ لیں۔",
     "Avoid anything you are allergic to; if you take medicines, ask your doctor before starting the qehwa.",
     "تجنّب ما لديك حساسية منه، وإن كنت تتناول أدوية فاسأل طبيبك قبل البدء بالقهوة العشبية."),
    ("بچوں، حاملہ یا دودھ پلانے والی خواتین اور بزرگوں کے لیے مقدار کم رکھیں اور معالج سے مشورہ کریں۔",
     "For children, pregnant or breast-feeding women and the elderly, keep amounts small and consult a doctor.",
     "للأطفال والحوامل والمرضعات وكبار السن: قلّل الكميات واستشر الطبيب."),
    ("اگر جسم میں سردی اور تری (بلغم، رطوبت) زیادہ محسوس ہو", "If you feel more cold and moisture (phlegm, fluid)",
     "إذا شعرت ببرودة ورطوبة (بلغم) زائدة"),
    ("اگر جسم میں تری کے ساتھ گرمی محسوس ہو", "If you feel moisture with heat", "إذا شعرت برطوبة مع حرارة"),
    ("اگر جسم میں خشکی کے ساتھ سردی محسوس ہو", "If you feel dryness with cold", "إذا شعرت بجفاف مع برودة"),
    ("اگر جسم میں خشکی کے ساتھ گرمی محسوس ہو", "If you feel dryness with heat", "إذا شعرت بجفاف مع حرارة"),
    ("اگر جسم میں گرمی کے ساتھ خشکی محسوس ہو", "If you feel heat with dryness", "إذا شعرت بحرارة مع جفاف"),
    ("اگر جسم میں گرمی کے ساتھ تری محسوس ہو", "If you feel heat with moisture", "إذا شعرت بحرارة مع رطوبة"),
]
CATALOG: dict[str, tuple[str, str]] = {ur: (en, ar) for ur, en, ar in _ROWS}


def tr(text: str | None, lang: str) -> str | None:
    """The English/Arabic translation of a fixed Urdu string; the Urdu text itself when none exists."""
    if not text or lang == "ur" or lang not in _IDX:
        return text
    hit = CATALOG.get(text)
    return hit[_IDX[lang]] if hit else text


_DEFAULT_TEXT: dict | None = None


def _defaults() -> dict:
    """{question_id: Urdu text, (question_id, option_key): Urdu label} of the built-in question bank."""
    global _DEFAULT_TEXT
    if _DEFAULT_TEXT is None:
        from .questionnaire import DEFAULT_QUESTIONS
        d: dict = {}
        for q in DEFAULT_QUESTIONS:
            d[q.id] = q.text
            for o in q.options:
                d[(q.id, o.key)] = o.label
        _DEFAULT_TEXT = d
    return _DEFAULT_TEXT


def question_text(qid: str | None, text: str, lang: str) -> str:
    """A question's text: translated when its Urdu text (or, if a Hakeem edited it, the built-in one) is known."""
    if lang == "ur" or text in CATALOG:
        return tr(text, lang)
    base = _defaults().get(qid)
    return tr(base, lang) if base in CATALOG else text


def option_label(qid: str | None, key: str | None, label: str, lang: str) -> str:
    if lang == "ur" or label in CATALOG:
        return tr(label, lang)
    base = _defaults().get((qid, key))
    return tr(base, lang) if base in CATALOG else label


def tr_list(items: list[str], lang: str) -> list[str]:
    return [tr(i, lang) for i in items]


def has_translation(text: str) -> bool:
    return text in CATALOG


# --------------------------------------------------------------------------- complaints in English/Arabic
# The book is Urdu: an English or Arabic complaint is matched to the book's topics through these words.
COMPLAINT_GLOSSARY: list[tuple[str, str]] = [
    (r"constipat|إمساك|امساك|قبض", "قبض"), (r"cough|سعال|كحة", "کھانسی"), (r"asthma|ربو", "دمہ"),
    (r"catarrh|common cold|\bcold\b|runny nose|زكام|رشح", "نزلہ زکام"), (r"fever|حمى|حمّى|سخونة", "بخار"),
    (r"headache|صداع", "سر درد"), (r"migraine|شقيقة", "شقیقہ"), (r"diarrh|إسهال|اسهال", "اسہال"),
    (r"dysentery|زحار", "پیچش"), (r"jaundice|يرقان", "یرقان"), (r"piles|haemorrhoid|hemorrhoid|بواسير", "بواسیر"),
    (r"diabet|سكري|سكر", "ذیابیطس"), (r"\bgas\b|bloat|flatulen|غازات|انتفاخ", "ریاح"),
    (r"acidity|heartburn|حموضة|حرقة", "تیزابیت"), (r"insomnia|sleepless|أرق", "بے خوابی"),
    (r"joint pain|arthrit|ألم المفاصل|التهاب المفاصل", "وجع المفاصل"), (r"gout|نقرس", "نقرس"),
    (r"sciatica|عرق النسا", "عرق النساء"), (r"vertigo|dizz|دوار|دوخة", "دوار"),
    (r"vomit|nausea|قيء|غثيان", "قے"), (r"hiccup|فواق|حازوقة", "ہچکی"),
    (r"eczema|ringworm|قوباء|أكزيما", "داد"), (r"itch|حكة", "خارش"), (r"acne|pimple|حب الشباب", "کیل مہاسے"),
    (r"vitiligo|برص|بهاق", "برص"), (r"hair fall|hair loss|تساقط الشعر", "بال گرنا"),
    (r"stomach ?ache|abdominal pain|ألم المعدة|ألم البطن", "درد معدہ"),
    (r"indigestion|dyspepsia|عسر الهضم", "بد ہضمی"), (r"kidney stone|حصى الكلى|حصوة", "پتھری"),
    (r"palpitation|خفقان", "خفقان"), (r"weakness|fatigue|ضعف|إرهاق", "ضعف"),
    (r"obesity|overweight|سمنة", "موٹاپا"), (r"burning urin|حرقة البول", "جلن پیشاب"),
    (r"tooth|toothache|ألم الأسنان", "دانت درد"), (r"sore throat|throat|التهاب الحلق|الحلق", "گلا"),
    (r"leucorrh|سيلان", "لیکوریا"), (r"menstru|period|حيض|الدورة", "حیض"),
]
_GLOSSARY_RE = [(re.compile(p, re.IGNORECASE), ur) for p, ur in COMPLAINT_GLOSSARY]
_URDU_ONLY_RE = re.compile(r"[ٹڈڑںھہےۓۂپچژگکی]")      # letters Urdu has and Arabic does not


def complaint_urdu_terms(text: str | None) -> str:
    """Urdu topic words for an English/Arabic complaint ('' when the complaint is already Urdu or unknown)."""
    if not text or _URDU_ONLY_RE.search(text):
        return ""
    return " ".join(dict.fromkeys(ur for rx, ur in _GLOSSARY_RE if rx.search(text)))
