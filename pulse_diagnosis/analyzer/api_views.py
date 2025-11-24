"""
REST API Views for Pulse Diagnosis System
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.utils import timezone
from .models import PulseAnalysis
from .ppg_service import analyze_pulse_video
import json


class AnalyzePulseAPI(APIView):
    """
    API endpoint for analyzing pulse videos.

    POST /api/analyze/
    - video_file: The pulse video file
    - symptoms: List of symptoms (JSON array or comma-separated string)
    - patient_name: Optional patient name
    - patient_age: Optional patient age
    - patient_gender: Optional patient gender
    """
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        # Get video file
        video_file = request.FILES.get('video_file')
        if not video_file:
            return Response(
                {'error': 'No video file provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get symptoms
        symptoms_data = request.data.get('symptoms', '[]')
        if isinstance(symptoms_data, str):
            try:
                symptoms = json.loads(symptoms_data)
            except json.JSONDecodeError:
                # Try comma-separated
                symptoms = [s.strip() for s in symptoms_data.split(',') if s.strip()]
        else:
            symptoms = list(symptoms_data)

        # Get optional patient info
        patient_name = request.data.get('patient_name', '')
        patient_age = request.data.get('patient_age')
        patient_gender = request.data.get('patient_gender', '')

        # Create analysis record
        analysis = PulseAnalysis.objects.create(
            video_file=video_file,
            symptoms=symptoms,
            patient_name=patient_name if patient_name else None,
            patient_age=int(patient_age) if patient_age else None,
            patient_gender=patient_gender if patient_gender else None,
            status='processing'
        )

        try:
            # Analyze the video
            video_path = analysis.video_file.path
            pulse_data = analyze_pulse_video(video_path)

            # Update analysis record
            analysis.pulse_data = pulse_data
            analysis.status = 'completed'
            analysis.processed_at = timezone.now()
            analysis.save()

            # Return results
            return Response({
                'success': True,
                'analysis_id': str(analysis.id),
                'pulse_data': pulse_data,
                'symptoms': symptoms,
                'formatted_output': {
                    'pulse_data_json': json.dumps(pulse_data, indent=2),
                    'symptoms_text': '\n'.join([f'- {s}' for s in symptoms])
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            analysis.status = 'failed'
            analysis.error_message = str(e)
            analysis.save()

            return Response({
                'success': False,
                'error': str(e),
                'analysis_id': str(analysis.id)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GetAnalysisAPI(APIView):
    """
    API endpoint for retrieving analysis results.

    GET /api/analysis/<analysis_id>/
    """

    def get(self, request, analysis_id):
        try:
            analysis = PulseAnalysis.objects.get(id=analysis_id)
        except PulseAnalysis.DoesNotExist:
            return Response(
                {'error': 'Analysis not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({
            'analysis_id': str(analysis.id),
            'status': analysis.status,
            'pulse_data': analysis.pulse_data,
            'symptoms': analysis.symptoms,
            'patient_info': {
                'name': analysis.patient_name,
                'age': analysis.patient_age,
                'gender': analysis.patient_gender
            },
            'diagnosis': analysis.diagnosis_result,
            'created_at': analysis.created_at.isoformat(),
            'processed_at': analysis.processed_at.isoformat() if analysis.processed_at else None,
            'error_message': analysis.error_message
        })


class ListAnalysesAPI(APIView):
    """
    API endpoint for listing recent analyses.

    GET /api/analyses/
    """

    def get(self, request):
        analyses = PulseAnalysis.objects.all()[:20]

        results = []
        for analysis in analyses:
            results.append({
                'id': str(analysis.id),
                'status': analysis.status,
                'patient_name': analysis.patient_name,
                'created_at': analysis.created_at.isoformat(),
                'heart_rate': analysis.pulse_data.get('average_heart_rate_bpm') if analysis.pulse_data else None
            })

        return Response({'analyses': results})


class SymptomSuggestionsAPI(APIView):
    """
    API endpoint for getting symptom suggestions.

    GET /api/symptoms/
    """

    def get(self, request):
        symptoms = {
            'general': [
                'Fatigue and lethargy',
                'Feeling of internal heat',
                'Feeling cold internally',
                'Excessive sweating',
                'Weight gain',
                'Weight loss',
                'Fever or chills',
            ],
            'digestive': [
                'Poor appetite',
                'Excessive appetite',
                'Constipation with dry stools',
                'Loose stools or diarrhea',
                'Bloating and gas',
                'Heartburn',
                'Nausea',
                'Excessive thirst',
            ],
            'neurological': [
                'Headaches',
                'Dizziness',
                'Anxiety and worry',
                'Irritability and anger',
                'Difficulty concentrating',
                'Poor memory',
                'Insomnia',
                'Excessive sleep',
            ],
            'musculoskeletal': [
                'Joint pain',
                'Joint stiffness',
                'Muscle cramps',
                'Muscle weakness',
                'Body heaviness',
            ],
            'skin': [
                'Dry skin',
                'Oily skin',
                'Acne',
                'Skin rashes',
                'Itching',
                'Pale complexion',
            ],
            'respiratory': [
                'Shortness of breath',
                'Cough',
                'Excessive mucus/phlegm',
                'Chest congestion',
            ],
            'urinary': [
                'Frequent urination',
                'Burning urination',
                'Dark urine',
                'Reduced urination',
            ],
            'circulatory': [
                'Cold hands and feet',
                'Swelling in extremities',
                'Bleeding gums',
                'Easy bruising',
            ]
        }

        return Response({'symptom_categories': symptoms})
