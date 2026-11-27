"""Diet plan by tehreek: the book's corrective food group, three meals, fruits, dry fruits and qehwa."""
from nazria_kb.diet import FOOD_GROUPS, NEXT_TEHREEK, diet_plans, plan_for, render_plans
from nazria_kb.questionnaire import TEHREEK_MIZAJ


def test_every_tehreek_gets_the_next_groups_foods():
    assert set(NEXT_TEHREEK) == set(TEHREEK_MIZAJ) == set(FOOD_GROUPS)
    assert NEXT_TEHREEK["عضلاتی غدی"] == "غدی عضلاتی" and NEXT_TEHREEK["اعصابی غدی"] == "اعصابی عضلاتی"
    seen = set()
    for t in TEHREEK_MIZAJ:
        p = plan_for(t)
        assert p["tehreek"] == t and p["mizaj"] == TEHREEK_MIZAJ[t] and p["choose_if"] is None
        assert p["breakfast"] and p["lunch"] and p["dinner"] and p["qehwa"]["name"] and p["qehwa"]["how"]
        assert p["breakfast"] == FOOD_GROUPS[NEXT_TEHREEK[t]]["breakfast"]
        seen.add(NEXT_TEHREEK[t])
    assert seen == set(FOOD_GROUPS)                 # a cycle: every food group is used once


def test_glandular_muscular_patient_gets_glandular_nervous_foods():
    p = plan_for("غدی عضلاتی")
    assert "بادام" in p["dry_fruits"] and "مونگ کی دال" in p["lunch"] and "ادرک" in p["qehwa"]["name"]


def test_groups_without_dry_fruits_say_so():
    p = plan_for("غدی اعصابی")                       # → اعصابی غدی foods: no dry fruits in the book
    assert p["dry_fruits"] == [] and any("میوہ جات نہ لیں" in r for r in p["rules"])
    assert "میوہ جات: اس حالت میں میوہ جات نہ لیں۔" in render_plans([p])


def test_only_the_dominant_system_gives_its_two_tehreeks_to_choose_from():
    plans = diet_plans(None, "عضلاتی")
    assert [p["tehreek"] for p in plans] == ["عضلاتی اعصابی", "عضلاتی غدی"]
    assert all(p["choose_if"] for p in plans) and "سردی" in plans[0]["choose_if"] and "گرمی" in plans[1]["choose_if"]
    assert diet_plans(None, None) == [] and len(diet_plans("اعصابی غدی", "اعصابی")) == 1


def test_notes_from_the_patients_health():
    p = plan_for("عضلاتی اعصابی", conditions=["diabetes", "hypertension"], caution=True, vulnerable=True)
    joined = " ".join(p["notes"])
    assert "شوگر" in joined and "نمک کم" in joined and "الرجی" in joined and "بچوں" in joined
    assert plan_for("عضلاتی اعصابی")["notes"] == []


def test_plan_text_has_meals_and_no_references():
    text = render_plans(diet_plans(None, "غدی"))
    for word in ("غذائی پلان", "ناشتہ", "دوپہر کا کھانا", "رات کا کھانا", "پھل", "میوہ جات", "قہوہ", "غذا کے اصول"):
        assert word in text
    for ref in ("صفحہ", "جلد اول", "جلد دوم", "کتاب", "حکیم"):
        assert ref not in text
