#!/usr/bin/env python3
"""
Demo script to generate sample pulse data and symptoms for testing
the Unani medicine diagnosis prompt without requiring camera input.
"""

import numpy as np
import json
from datetime import datetime


def generate_synthetic_ppg(
    heart_rate=72,
    duration=60,
    fps=30,
    hrv_level='normal',
    pulse_strength='moderate',
    noise_level=0.1
):
    """
    Generate synthetic PPG signal for testing purposes.

    Args:
        heart_rate: Target heart rate in BPM
        duration: Signal duration in seconds
        fps: Samples per second
        hrv_level: 'low', 'normal', or 'high'
        pulse_strength: 'weak', 'moderate', or 'strong'
        noise_level: Amount of noise to add (0-1)

    Returns:
        numpy array of synthetic PPG values
    """
    num_samples = int(duration * fps)
    t = np.linspace(0, duration, num_samples)

    # Base frequency from heart rate
    base_freq = heart_rate / 60

    # HRV simulation
    hrv_map = {'low': 0.02, 'normal': 0.05, 'high': 0.1}
    hrv_factor = hrv_map.get(hrv_level, 0.05)

    # Strength affects amplitude
    strength_map = {'weak': 0.3, 'moderate': 0.6, 'strong': 0.9}
    amplitude = strength_map.get(pulse_strength, 0.6)

    # Generate PPG waveform with harmonics
    # Main pulse wave
    signal = amplitude * np.sin(2 * np.pi * base_freq * t)

    # Add harmonics for realistic pulse shape
    signal += 0.3 * amplitude * np.sin(4 * np.pi * base_freq * t)
    signal += 0.1 * amplitude * np.sin(6 * np.pi * base_freq * t)

    # Add HRV (frequency modulation)
    hrv_mod = hrv_factor * np.sin(2 * np.pi * 0.1 * t)  # Slow variation
    signal = amplitude * np.sin(2 * np.pi * base_freq * t * (1 + hrv_mod))

    # Add dicrotic notch simulation
    notch = -0.15 * amplitude * np.sin(2 * np.pi * base_freq * t - np.pi/3)
    signal += notch

    # Add noise
    noise = noise_level * np.random.randn(num_samples)
    signal += noise

    # Normalize to typical PPG range (0-255 for green channel)
    signal = 128 + 50 * signal

    return signal


def analyze_synthetic_signal(signal, fps=30, duration=60):
    """
    Analyze synthetic PPG signal and return pulse data dictionary.
    """
    from scipy.signal import find_peaks, butter, filtfilt

    # Normalize
    normalized = (signal - np.mean(signal)) / np.std(signal)

    # Filter
    nyquist = fps / 2
    b, a = butter(2, [0.5/nyquist, 4.0/nyquist], btype='band')
    filtered = filtfilt(b, a, normalized)

    # Find peaks
    peaks, _ = find_peaks(filtered, distance=int(fps * 0.5), prominence=0.1)

    # Calculate metrics
    ibi = np.diff(peaks) / fps * 1000
    avg_hr = 60000 / np.mean(ibi)
    hrv = np.std(ibi)

    # Amplitude analysis
    amplitudes = []
    for i in range(1, len(peaks)-1):
        start = (peaks[i-1] + peaks[i]) // 2
        end = (peaks[i] + peaks[i+1]) // 2
        segment = filtered[start:end]
        if len(segment) > 0:
            amplitudes.append(np.max(segment) - np.min(segment))

    avg_amplitude = np.mean(amplitudes) if amplitudes else 0.5

    # Determine characteristics
    if avg_hr > 85:
        rate_pattern = "consistently elevated"
    elif avg_hr > 75:
        rate_pattern = "steady with minor elevations"
    elif avg_hr > 65:
        rate_pattern = "steady and normal"
    else:
        rate_pattern = "slow and steady"

    if avg_amplitude > 0.7:
        strength = "strong and bounding"
        volume = "full and expansive"
    elif avg_amplitude > 0.5:
        strength = "moderate to strong"
        volume = "full"
    elif avg_amplitude > 0.35:
        strength = "moderate"
        volume = "normal"
    else:
        strength = "weak and thready"
        volume = "thin and narrow"

    if hrv < 30:
        rhythm = "very regular"
    elif hrv < 50:
        rhythm = "regular"
    else:
        rhythm = "regular with occasional variations"

    return {
        "recording_duration_seconds": duration,
        "average_heart_rate_bpm": round(avg_hr, 1),
        "resting_heart_rate_bpm": round(avg_hr - 5, 1),
        "heart_rate_variability_ms": round(hrv, 1),
        "pulse_characteristics": {
            "rhythm": rhythm,
            "strength": strength,
            "volume": volume,
            "tension": "moderate",
            "rate_pattern": rate_pattern
        },
        "waveform_analysis": {
            "systolic_peak_amplitude": round(min(1.0, avg_amplitude), 2),
            "diastolic_notch_depth": round(0.3, 2),
            "pulse_wave_velocity": "moderate",
            "rise_time_ms": 120,
            "fall_time_ms": 280
        },
        "signal_quality": "good",
        "recording_timestamp": datetime.now().isoformat() + "Z"
    }


# Pre-defined symptom sets for different mizaj types
SYMPTOM_SETS = {
    "garm_khushk": [
        "Frequent headaches, especially in the temples",
        "Feeling of internal heat and warmth",
        "Dry mouth and excessive thirst",
        "Irritability and anger episodes",
        "Difficulty sleeping, restless nights",
        "Constipation with dry stools",
        "Skin feels dry and rough",
        "Burning sensation during urination",
        "Joint stiffness, especially in mornings",
        "Increased appetite but food feels unsatisfying"
    ],
    "sard_ratab": [
        "Constant fatigue and lethargy",
        "Feeling cold, especially in hands and feet",
        "Excessive mucus and phlegm production",
        "Heaviness in the body and limbs",
        "Poor appetite and slow digestion",
        "Loose stools or watery diarrhea",
        "Swelling in feet and ankles",
        "White coating on tongue",
        "Excessive salivation",
        "Mental fog and difficulty concentrating",
        "Weight gain despite eating less",
        "Feeling sleepy during the day"
    ],
    "garm_ratab": [
        "Excessive sweating, especially at night",
        "Skin feels oily and prone to acne",
        "Feeling of warmth with humidity sensitivity",
        "Frequent thirst with preference for cold drinks",
        "Loose stools but not watery",
        "Redness in face and eyes",
        "Restlessness and hyperactivity",
        "Sweet or metallic taste in mouth",
        "Bleeding gums",
        "Heavy menstrual flow (if applicable)",
        "Feeling overheated in warm environments"
    ],
    "sard_khushk": [
        "Anxiety and worry without clear cause",
        "Dry skin that cracks easily",
        "Feeling cold internally",
        "Constipation with hard, dry stools",
        "Insomnia with racing thoughts",
        "Joint pain that worsens in cold weather",
        "Brittle nails and dry hair",
        "Pale complexion",
        "Poor memory and concentration",
        "Irregular appetite",
        "Feeling of heaviness in chest",
        "Muscle cramps and stiffness"
    ],
    "mutadil_garm": [
        "Occasional feeling of warmth",
        "Mild irritability under stress",
        "Normal appetite but prefers light meals",
        "Slight dryness in throat",
        "Generally good energy but occasional fatigue",
        "Mild difficulty falling asleep",
        "Occasional heartburn after spicy food",
        "Normal bowel movements with occasional hardness",
        "Slight sensitivity to hot weather",
        "Minor skin sensitivity"
    ],
    "mutadil_sard": [
        "Mild feeling of coldness in extremities",
        "Slight tendency to gain weight",
        "Prefers warm foods and drinks",
        "Occasional sluggish digestion",
        "Generally calm temperament",
        "Slight mucus in the morning",
        "Normal but slow bowel movements",
        "Preference for warm environments",
        "Mild water retention",
        "Occasional afternoon fatigue"
    ]
}

# Pulse patterns for each mizaj
PULSE_PATTERNS = {
    "garm_khushk": {
        "heart_rate": 88,
        "hrv_level": "low",
        "pulse_strength": "strong"
    },
    "sard_ratab": {
        "heart_rate": 62,
        "hrv_level": "high",
        "pulse_strength": "weak"
    },
    "garm_ratab": {
        "heart_rate": 78,
        "hrv_level": "normal",
        "pulse_strength": "moderate"
    },
    "sard_khushk": {
        "heart_rate": 65,
        "hrv_level": "low",
        "pulse_strength": "weak"
    },
    "mutadil_garm": {
        "heart_rate": 74,
        "hrv_level": "normal",
        "pulse_strength": "moderate"
    },
    "mutadil_sard": {
        "heart_rate": 68,
        "hrv_level": "normal",
        "pulse_strength": "moderate"
    }
}


def generate_sample_data(mizaj_type='garm_khushk'):
    """
    Generate complete sample data for a specific mizaj type.

    Args:
        mizaj_type: One of the six mizaj types

    Returns:
        tuple of (pulse_data_dict, symptoms_list)
    """
    if mizaj_type not in PULSE_PATTERNS:
        raise ValueError(f"Unknown mizaj type: {mizaj_type}. Choose from: {list(PULSE_PATTERNS.keys())}")

    pattern = PULSE_PATTERNS[mizaj_type]
    symptoms = SYMPTOM_SETS[mizaj_type]

    # Generate synthetic signal
    signal = generate_synthetic_ppg(
        heart_rate=pattern['heart_rate'],
        hrv_level=pattern['hrv_level'],
        pulse_strength=pattern['pulse_strength']
    )

    # Analyze signal
    pulse_data = analyze_synthetic_signal(signal)

    return pulse_data, symptoms


def format_for_prompt(pulse_data, symptoms):
    """
    Format data for use in the diagnosis prompt.
    """
    pulse_json = json.dumps(pulse_data, indent=2)
    symptom_text = "\n".join([f"- {s}" for s in symptoms])

    return {
        "pulse_data": pulse_json,
        "user_symptoms": symptom_text
    }


def main():
    """Generate and display sample data for all mizaj types."""
    print("="*70)
    print("SAMPLE DATA GENERATOR FOR UNANI MEDICINE DIAGNOSIS")
    print("="*70)

    print("\nAvailable mizaj types:")
    for i, mizaj in enumerate(PULSE_PATTERNS.keys(), 1):
        print(f"  {i}. {mizaj}")

    print("\n" + "-"*70)

    # Generate one example
    selected = input("\nEnter mizaj type to generate (or 'all' for all types): ").strip().lower()

    if selected == 'all':
        for mizaj_type in PULSE_PATTERNS.keys():
            print(f"\n{'='*70}")
            print(f"SAMPLE DATA FOR: {mizaj_type.upper()}")
            print("="*70)

            pulse_data, symptoms = generate_sample_data(mizaj_type)
            formatted = format_for_prompt(pulse_data, symptoms)

            print("\n<pulse_data>")
            print(formatted['pulse_data'])
            print("</pulse_data>")

            print("\n<user_symptoms>")
            print(formatted['user_symptoms'])
            print("</user_symptoms>")

            # Save to file
            filename = f"sample_{mizaj_type}.json"
            with open(filename, 'w') as f:
                json.dump({
                    "pulse_data": pulse_data,
                    "user_symptoms": symptoms
                }, f, indent=2)
            print(f"\n✓ Saved to: {filename}")
    else:
        if selected not in PULSE_PATTERNS:
            print(f"Unknown type. Using 'garm_khushk' as default.")
            selected = 'garm_khushk'

        pulse_data, symptoms = generate_sample_data(selected)
        formatted = format_for_prompt(pulse_data, symptoms)

        print(f"\n{'='*70}")
        print(f"SAMPLE DATA FOR: {selected.upper()}")
        print("="*70)

        print("\n<pulse_data>")
        print(formatted['pulse_data'])
        print("</pulse_data>")

        print("\n<user_symptoms>")
        print(formatted['user_symptoms'])
        print("</user_symptoms>")

        # Save to file
        filename = f"sample_{selected}.json"
        with open(filename, 'w') as f:
            json.dump({
                "pulse_data": pulse_data,
                "user_symptoms": symptoms
            }, f, indent=2)
        print(f"\n✓ Saved to: {filename}")


if __name__ == "__main__":
    main()
