# Nazria Mufrad Aza - Pulse Diagnosis System

A Django web application for Unani medicine pulse diagnosis based on the principles of Mizaj (temperament) and Tehreek (bodily movements) as described by Hakim Dost Muhammad Sabir Multani.

## Features

- Upload pulse videos captured via smartphone camera
- Automatic PPG (photoplethysmography) analysis
- Symptom collection interface
- Traditional Unani pulse characteristic analysis
- REST API for integration

## Installation

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run migrations:
```bash
python manage.py migrate
```

4. Create a superuser (optional):
```bash
python manage.py createsuperuser
```

5. Run the development server:
```bash
python manage.py runserver
```

6. Open http://localhost:8000 in your browser

## API Endpoints

- `POST /api/analyze/` - Upload video and symptoms for analysis
- `GET /api/analysis/<id>/` - Get analysis results
- `GET /api/analyses/` - List recent analyses
- `GET /api/symptoms/` - Get symptom suggestions

## How to Record Pulse Video

1. Clean your phone's camera lens
2. Place your index or middle finger flat on the camera lens
3. Apply gentle pressure (not too hard, not too light)
4. Record for 30-60 seconds while keeping still
5. Stay relaxed and breathe normally

## Project Structure

```
pulse_diagnosis/
├── analyzer/              # Main app
│   ├── models.py          # Database models
│   ├── views.py           # Frontend views
│   ├── api_views.py       # REST API views
│   ├── ppg_service.py     # PPG analysis service
│   └── urls.py            # URL routing
├── templates/             # HTML templates
├── static/                # CSS, JS, images
├── media/                 # Uploaded videos
└── pulse_diagnosis/       # Project settings
```

## The Six Mizaj Combinations

1. **Garm Khushk** (Hot & Dry) - Choleric
2. **Garm Ratab** (Hot & Moist) - Sanguine
3. **Sard Khushk** (Cold & Dry) - Melancholic
4. **Sard Ratab** (Cold & Moist) - Phlegmatic
5. **Mutadil Garm** (Moderately Hot)
6. **Mutadil Sard** (Moderately Cold)

## The Six Tahareeks

1. اعصابی غدی (Nervous-Glandular)
2. اعصابی عضلاتی (Nervous-Muscular)
3. عضلاتی اعصابی (Muscular-Nervous)
4. عضلاتی غدی (Muscular-Glandular)
5. غدی عضلاتی (Glandular-Muscular)
6. غدی اعصابی (Glandular-Nervous)

## License

This project is for educational and research purposes.
