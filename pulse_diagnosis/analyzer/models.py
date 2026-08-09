"""
Models for Unani Medicine Pulse Diagnosis System
"""
from django.db import models
from django.utils import timezone
import uuid
import json


class PulseAnalysis(models.Model):
    """
    Model to store pulse video uploads and analysis results.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Video upload
    video_file = models.FileField(upload_to='videos/%Y/%m/%d/')

    # User information (optional)
    patient_name = models.CharField(max_length=255, blank=True, null=True)
    patient_age = models.PositiveIntegerField(blank=True, null=True)
    patient_gender = models.CharField(
        max_length=20,
        choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
        blank=True,
        null=True
    )

    # Symptoms (stored as JSON)
    symptoms = models.JSONField(default=list, blank=True)

    # Raw pulse data from PPG analysis
    pulse_data = models.JSONField(default=dict, blank=True)

    # Diagnosis results
    diagnosis_result = models.JSONField(default=dict, blank=True)

    # Mizaj diagnosis
    primary_mizaj = models.CharField(max_length=100, blank=True, null=True)
    primary_tehreek = models.CharField(max_length=100, blank=True, null=True)

    # Confidence level
    confidence_level = models.CharField(
        max_length=20,
        choices=[('high', 'High'), ('medium', 'Medium'), ('low', 'Low')],
        blank=True,
        null=True
    )

    # Processing status
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Pulse Analysis'
        verbose_name_plural = 'Pulse Analyses'

    def __str__(self):
        return f"Analysis {self.id} - {self.status}"

    def get_symptoms_list(self):
        """Return symptoms as a list."""
        if isinstance(self.symptoms, list):
            return self.symptoms
        return []

    def get_formatted_symptoms(self):
        """Return symptoms formatted for display."""
        return "\n".join([f"- {s}" for s in self.get_symptoms_list()])


class SymptomCategory(models.Model):
    """
    Predefined symptom categories for user selection.
    """
    name = models.CharField(max_length=100)
    name_urdu = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = 'Symptom Categories'

    def __str__(self):
        return self.name


class Symptom(models.Model):
    """
    Predefined symptoms for user selection.
    """
    category = models.ForeignKey(
        SymptomCategory,
        on_delete=models.CASCADE,
        related_name='symptoms'
    )
    name = models.CharField(max_length=255)
    name_urdu = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    # Associated mizaj tendencies
    mizaj_association = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.category.name}: {self.name}"
