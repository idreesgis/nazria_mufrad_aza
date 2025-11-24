"""
Views for Unani Medicine Pulse Diagnosis System
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from .models import PulseAnalysis, SymptomCategory, Symptom
from .ppg_service import analyze_pulse_video
import json


class HomeView(View):
    """Landing page with video capture instructions."""

    def get(self, request):
        return render(request, 'analyzer/home.html')


class UploadView(View):
    """View for uploading pulse video and entering symptoms."""

    def get(self, request):
        # Get predefined symptoms for selection
        symptom_categories = SymptomCategory.objects.prefetch_related('symptoms').all()

        # Predefined symptoms if database is empty
        default_symptoms = {
            'general': [
                'Fatigue and lethargy',
                'Feeling of internal heat',
                'Feeling cold internally',
                'Excessive sweating',
                'Weight changes',
            ],
            'digestive': [
                'Poor appetite',
                'Excessive appetite',
                'Constipation',
                'Diarrhea',
                'Bloating',
                'Heartburn',
            ],
            'neurological': [
                'Headaches',
                'Dizziness',
                'Anxiety',
                'Irritability',
                'Difficulty concentrating',
                'Insomnia',
            ],
            'musculoskeletal': [
                'Joint pain',
                'Muscle cramps',
                'Stiffness',
                'Weakness',
            ],
            'skin': [
                'Dry skin',
                'Oily skin',
                'Acne',
                'Itching',
            ],
            'respiratory': [
                'Shortness of breath',
                'Cough',
                'Excessive mucus',
            ],
        }

        context = {
            'symptom_categories': symptom_categories,
            'default_symptoms': default_symptoms,
        }
        return render(request, 'analyzer/upload.html', context)

    def post(self, request):
        # Get uploaded video
        video_file = request.FILES.get('video_file')
        if not video_file:
            messages.error(request, 'Please upload a pulse video.')
            return redirect('upload')

        # Get symptoms
        symptoms = request.POST.getlist('symptoms')
        custom_symptoms = request.POST.get('custom_symptoms', '').strip()

        if custom_symptoms:
            # Parse custom symptoms (one per line)
            custom_list = [s.strip() for s in custom_symptoms.split('\n') if s.strip()]
            symptoms.extend(custom_list)

        # Get patient info (optional)
        patient_name = request.POST.get('patient_name', '').strip()
        patient_age = request.POST.get('patient_age')
        patient_gender = request.POST.get('patient_gender', '')

        # Create analysis record
        analysis = PulseAnalysis.objects.create(
            video_file=video_file,
            symptoms=symptoms,
            patient_name=patient_name if patient_name else None,
            patient_age=int(patient_age) if patient_age else None,
            patient_gender=patient_gender if patient_gender else None,
            status='processing'
        )

        # Process the video
        try:
            video_path = analysis.video_file.path
            pulse_data = analyze_pulse_video(video_path)

            analysis.pulse_data = pulse_data
            analysis.status = 'completed'
            analysis.processed_at = timezone.now()
            analysis.save()

            return redirect('results', analysis_id=analysis.id)

        except Exception as e:
            analysis.status = 'failed'
            analysis.error_message = str(e)
            analysis.save()

            messages.error(request, f'Analysis failed: {str(e)}')
            return redirect('upload')


class ResultsView(View):
    """View for displaying analysis results."""

    def get(self, request, analysis_id):
        analysis = get_object_or_404(PulseAnalysis, id=analysis_id)

        context = {
            'analysis': analysis,
            'pulse_data': analysis.pulse_data,
            'symptoms': analysis.get_symptoms_list(),
            'pulse_data_json': json.dumps(analysis.pulse_data, indent=2),
            'symptoms_formatted': analysis.get_formatted_symptoms(),
        }
        return render(request, 'analyzer/results.html', context)


class HistoryView(View):
    """View for displaying analysis history."""

    def get(self, request):
        analyses = PulseAnalysis.objects.all()[:20]
        context = {
            'analyses': analyses,
        }
        return render(request, 'analyzer/history.html', context)


def health_check(request):
    """Simple health check endpoint."""
    return JsonResponse({'status': 'ok', 'service': 'Pulse Diagnosis API'})
