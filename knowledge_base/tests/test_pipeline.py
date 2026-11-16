"""Unit tests on small synthetic fixtures (the book itself is not committed)."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nazria_kb.clean import HeaderModel, clean_page  # noqa: E402
from nazria_kb.dialogues import consultation, qa_pairs  # noqa: E402
from nazria_kb.entities import parse_ingredients, parse_quantity  # noqa: E402
from nazria_kb.normalize import normalize_urdu, search_key, to_int  # noqa: E402
from nazria_kb.parse import read_pages  # noqa: E402
from nazria_kb.structure import (Section, Topic, assign_treatises, build_chunks, build_topics,  # noqa: E402
                                 classify_role, detect_tehreek, heading_subject)


def _row(legacy, vol, page, text, section=1):
    esc = text.replace("'", "''").replace('"', "'\"")
    return (f'{legacy},{vol * 1000 + page},page_{page}.png,"{esc}",completed,,2025-10-28 13:22:16.5,pending,,,,,,'
            f'"<p>{esc}</p>",{section},{vol},,,,not_generated\n')


def test_csv_dialect_apostrophe_escape(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text(_row(1, 1, 2, 'متن "اقتباس" اور Saber\'s') + _row(2, 1, 1, "سطر اول\nسطر دوم"), encoding="utf-8")
    pages = read_pages(f)
    assert [p.page_no for p in pages] == [1, 2]          # sorted by page
    assert pages[1].ocr_text == 'متن "اقتباس" اور Saber\'s'
    assert pages[0].ocr_text == "سطر اول\nسطر دوم"
    assert pages[0].page_key == 1001 and pages[0].volume_no == 1


def test_normalization():
    assert normalize_urdu("كتاب يه") == "کتاب یہ"           # Arabic kaf/yeh/heh -> Urdu
    assert normalize_urdu("٣٧٤") == "۳۷۴"                    # Arabic-Indic -> Urdu digits
    assert search_key("کلّیات تحقیقاتِ") == "کلیات تحقیقات"   # diacritics stripped
    assert to_int("۲۳۶") == 236


def test_quantities():
    assert parse_quantity("ایک پاؤ") == (1, "پاؤ")
    assert parse_quantity("دو نیم پاؤ") == (2.5, "پاؤ")
    assert parse_quantity("4 تولے") == (4.0, "تولہ")
    assert parse_quantity("دوسیر") == (2, "سیر")
    ings = parse_ingredients("ٹماٹر ۴ سیر، کشمش نیم سیر، ادرک نیم پاؤ، نمک مرچ حسب ضرورت۔")
    assert [(i.name, i.quantity_value, i.unit) for i in ings] == [
        ("ٹماٹر", 4.0, "سیر"), ("کشمش", 0.5, "سیر"), ("ادرک", 0.5, "پاؤ"), ("نمک مرچ", None, None)]


def test_clean_page_strips_headers_and_artifacts():
    raw = ("Here is the extracted text with Markdown formatting:\n```markdown\n# کلیات تحقیقات صابر ملتانی\n"
           "## تحقیقات نزلہ و زکام\n۱۵۳\n\nنزلہ ایک عام مرض ہے۔\n\n**علاج:** گل بنفشہ پانچ حصے۔\n```")
    hm = HeaderModel().fit([raw] * 5)
    p = clean_page(raw, 2, 150, hm)
    assert p.printed_page_no == 153
    assert p.running_title == "تحقیقات نزلہ و زکام"
    assert "llm_preamble" in p.flags
    assert "```" not in p.text and "Here is" not in p.text
    assert [b.kind for b in p.blocks] == ["para", "label"]
    assert p.blocks[1].label == "علاج"


def test_degenerate_loop_and_hallucination_removed():
    raw = "اصل متن یہاں ہے۔ " + "ن م ر و " * 40 + "\nresponse = requests.get(api_url)\nprint(response.json())"
    p = clean_page(raw, 1, 5, HeaderModel())
    assert "degenerate_output" in p.flags and "hallucinated_text" in p.flags
    assert "requests" not in p.text and "ن م ر و ن م ر و" not in p.text
    assert "اصل متن" in p.text


def test_roles_and_subjects():
    assert classify_role("علامات") == "symptoms"
    assert classify_role("مقدار خوراک") == "dosage"
    assert classify_role("آتشک کے اسباب") == "causes"
    assert heading_subject("آتشک کے اسباب", "causes") == "آتشک"
    assert heading_subject("جریان کے لیے مفرد ادویہ", "recipe") == "جریان"


def test_tehreek_detection():
    primary, counts = detect_tehreek("یہ عضلاتی غدی دوا ہے۔ عضلاتی غدی تحریک میں مفید۔ غدی اعصابی نہیں۔")
    assert primary == "عضلاتی غدی" and counts["عضلاتی غدی"] == 2


def test_structure_and_dialogue_end_to_end():
    pages_raw = [
        "# کلیات تحقیقات صابر ملتانی\n## تحقیقات و علاج نزلہ و زکام\n۱۰\n\n## کھانسی\n\n### علامات\n\n"
        "گلے میں خراش ہوتی ہے۔ رات کو کھانسی بڑھ جاتی ہے۔ بلغم خارج ہوتا ہے۔ "
        "سینے میں بوجھ محسوس ہوتا ہے اور سانس لینے میں دقت ہوتی ہے۔ آواز بیٹھ جاتی ہے۔\n\n### اسباب\n\nسردی لگنا اور ٹھنڈی اشیاء کا استعمال، "
        "جو عضلاتی اعصابی تحریک پیدا کرتے ہیں۔",
        "# کلیات تحقیقات صابر ملتانی\n## تحقیقات و علاج نزلہ و زکام\n۱۱\n\n### نسخہ\n\nگل بنفشہ پانچ حصے، بادیان تین حصے، ملٹھی دو حصے، سب کو باریک پیس لیں۔\n\n"
        "**مقدار خوراک:** ایک ماشہ دن میں تین بار۔\n\n### پرہیز\n\nٹھنڈی اشیاء، چاول اور دہی سے پرہیز کریں۔",
    ] * 1
    hm = HeaderModel().fit(pages_raw)
    pages = [clean_page(t, 2, 10 + i, hm) for i, t in enumerate(pages_raw)]
    treatises, pm = assign_treatises(pages)
    assert len(treatises) == 1
    topics = build_topics(pages, treatises, pm)
    cough = next(t for t in topics if t.title == "کھانسی")
    assert {"symptoms", "causes", "recipe", "dosage", "diet"} <= set(cough.roles)
    assert cough.topic_type == "disease" and cough.tehreek == "عضلاتی اعصابی"
    chunks = build_chunks(topics, treatises)
    assert all(c.text and c.pages for c in chunks)
    ti = topics.index(cough)
    conv = consultation(ti, topics, random.Random(1), 0, {})
    assert conv is not None
    roles = [t.role for t in conv.turns]
    assert roles[0] == "patient" and all(a != b for a, b in zip(roles, roles[1:]))
    hakeem_text = " ".join(t.content for t in conv.turns if t.role == "hakeem")
    assert "گل بنفشہ" in hakeem_text and "عضلاتی اعصابی" in hakeem_text and "مستند حکیم" in hakeem_text
    qa = qa_pairs(ti, cough, random.Random(1), {})
    assert qa and all(c.turns[1].refs for c in qa)


def test_qa_skips_short_sections():
    t = Topic(1, 1, "مثال", [Section("overview", "")])
    assert qa_pairs(0, t, random.Random(0), {}) == []
