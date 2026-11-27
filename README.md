# nazria_mufrad_aza

Guidance based on Hakeem Dost Muhammad Saber Multani's نظریہ مفرد اعضاء and the book «کلیات تحقیقات صابر ملتانی».

| Path | What |
|---|---|
| [`knowledge_base/`](knowledge_base/) | **The backend.** It contains the knowledge-base pipeline (book → PostgreSQL) and the Django REST API used by the Android app: patient accounts, questionnaire and assessment, pulse-video analysis, staff access and the audit log. The Ubuntu deployment is in `knowledge_base/deploy/`. |
| `ppg_pulse_analyzer.py`, `traditional_nabz_analyzer.py`, `demo_pulse_analysis.py` | Standalone command-line pulse analysers (the API's pulse analysis is in `knowledge_base/pulse/`). |
| `WRIST_PULSE_RECORDING_GUIDE.md` | How to record a pulse video. |

The Android app is in a separate repository, `nazria_mufrad_aza_mobile`.
