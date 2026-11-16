# Questionnaire weights — page check against the book (vol 2, scan pages 125–134)

Checked by reading the cleaned page text (`nazria.source_pages.clean_text`, `book_id = 2`). Page numbers are
**scan pages** (`page_no`); the printed page number is 3 higher in this part of the book. **No weight was changed.**
This check is for a Hakeem to confirm.

| question / option | weight | book evidence | pages |
|---|---|---|---|
| urine red | عضلاتی +2 | p125 «قارورہ سرخ یا سرخی مائل زرد»; p127 عضلاتی قبض «قارورہ سرخ»; p133 عضلاتی کھانسی «قارورہ میں سرخی» | 125, 127, 133 ✅ |
| urine yellow | غدی +2 | p125 «قارورہ زرد یا سفیدی مائل»; p127 غدی قبض «زرد یا زرد سرخی مائل»; p134 غدی دمہ «قارورے میں زردی» | 125, 127, 134 ✅ |
| urine white | اعصابی +2 | p126 «قارورہ سفید»; p128 اعصابی قبض «سفید یا سفیدی مائل»; p134 اعصابی دمہ «قارورہ سفید» | **126, 128, 134** (was 127) |
| bowel constipation | عضلاتی +2 | p125 «اکثر قبض»; p127 «عضلاتی قبض اکثر شدید … دائمی» | 125, 127 ✅ |
| bowel incomplete / مروڑ | غدی +2 | p125 «مروڑ اور پیچ سے پاخانہ»; p127 «تسلی نہیں ہوتی … مروڑ اور پیچ» | 125, 127 ✅ |
| bowel loose | اعصابی +2 | p126 «اکثر اسہال» | 126 ✅ |
| body dry | عضلاتی +1 | p125 «جسم میں خشکی»; p127 «بے حد خشکی … مریض دبلا» | 125, 127 ✅ |
| body heat | غدی +1 | p125 «جسم میں حرارت»; p127 «ہاتھ پاؤں جلتے ہیں» | 125, 127 ✅ |
| body phlegmatic / heavy | اعصابی +1 | p126 «بلغم کی زیادتی … جسم بھرا ہوا یا موٹا» | 126 ✅ |
| abdomen gas | عضلاتی +1 | p125, p127 «ریاح»; p133, p134 «ریاح شکم» | 125, 127, 133, 134 ✅ |
| abdomen heat after meals / رکاوٹ | غدی +1 | p125 «غذا کھانے کے بعد حرارت بڑھ جاتی ہے»; p127 «سدہ یا رکاوٹ» | **125, 127** (was 126) |
| taste sour | عضلاتی +1 | p125 «ذائقہ ترش» | 125 ✅ |
| taste sweet | غدی +1 | p125 «ذائقہ میٹھی» | **125** (126 removed) |
| taste bitter | اعصابی +1 | p126 «ذائقہ کڑوا» | 126 ✅ |
| heart palpitations | عضلاتی +1 | p133 «دل کا گھبرانا، نبض کا تیز چلنا»; p134 «دل کا گھبرانا، نبض تیز» | 133, 134 ✅ |
| burning urine | غدی +1 | p132 غدی کھانسی «پیشاب میں جلن»; p134 غدی دمہ «پیشاب میں جلن» | **132, 134** (133 removed) |
| catarrh / headache / swelling | اعصابی +1 | p128 «نزلہ اور ورم بڑھ جاتا ہے۔ اکثر درد سر» | **128** (127 removed) |
| phlegm thick | عضلاتی +1 | p133 «بلغم کا غلیظ ہونا اور … آسانی سے اخراج نہ پانا» | 133 ✅ ⚠️ see note |
| phlegm yellowish | غدی +1 | p134 «بلغم زردی مائل» | 134 ✅ |
| phlegm profuse, limbs loose | اعصابی +1 | p134 «رطوبت کی زیادتی … اعضاء ڈھیلے» | 134 ✅ |

**Result:** every weighted link points to the system the book names. Five citations were corrected (bold). On an
existing database the loader applies these corrections only where the row still has the old default pages
(`db.CITATION_CORRECTIONS`), so a Hakeem's own edits are kept.

**For the Hakeem to decide**
1. *phlegm thick*: the label «گاڑھا، مشکل سے نکلتا ہے» also fits اعصابی (p132 «اخراج بڑی دقت سے», p134 «بلغم کا اخراج
   مشکل»). Consider shortening it to «گاڑھا (غلیظ)».
2. *ہاضم* sections (pp128–129) give the opposite urine colours (ہاضم غدی: red, ہاضم عضلاتی: white, ہاضم اعصابی: yellow)
   because they describe *سکون* (sluggishness) of an organ, not its تحریک. The questionnaire correctly does not cite them.
