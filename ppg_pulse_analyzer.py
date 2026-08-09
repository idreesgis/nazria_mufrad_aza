#!/usr/bin/env python3
"""
PPG Pulse Analyzer for Unani Medicine Diagnosis
Extracts and analyzes pulse data from finger videos using photoplethysmography (PPG)
"""

import cv2
import numpy as np
from scipy import signal
from scipy.fft import fft, fftfreq
from scipy.signal import find_peaks, butter, filtfilt
from datetime import datetime
import json
import argparse
from collections import deque
import warnings
warnings.filterwarnings('ignore')


class PPGPulseAnalyzer:
    """
    Analyzes pulse data from finger videos using camera-based photoplethysmography.
    """

    def __init__(self, fps=30, recording_duration=60):
        """
        Initialize the PPG analyzer.

        Args:
            fps: Frames per second of the video
            recording_duration: Duration to record/analyze in seconds
        """
        self.fps = fps
        self.recording_duration = recording_duration
        self.raw_signal = []
        self.filtered_signal = []
        self.timestamps = []

    def extract_ppg_from_video(self, video_source, roi_selection='auto'):
        """
        Extract PPG signal from a video file or camera feed.

        Args:
            video_source: Path to video file or camera index (0 for default camera)
            roi_selection: 'auto' for automatic ROI detection, 'manual' for user selection

        Returns:
            numpy array of PPG signal values
        """
        # Open video source
        if isinstance(video_source, str):
            cap = cv2.VideoCapture(video_source)
        else:
            cap = cv2.VideoCapture(video_source)

        if not cap.isOpened():
            raise ValueError(f"Could not open video source: {video_source}")

        # Get video properties
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(self.fps * self.recording_duration)

        print(f"Processing video at {self.fps} FPS...")
        print(f"Recording duration: {self.recording_duration} seconds")

        # Initialize signal storage
        green_values = []
        red_values = []
        frame_count = 0
        roi = None

        # For automatic ROI detection
        face_cascade = None

        while frame_count < total_frames:
            ret, frame = cap.read()
            if not ret:
                break

            # Convert to different color spaces
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            # ROI selection
            if roi is None:
                if roi_selection == 'manual':
                    roi = cv2.selectROI("Select Finger Region", frame, False)
                    cv2.destroyWindow("Select Finger Region")
                else:
                    # Auto-detect skin region (finger)
                    roi = self._auto_detect_finger_roi(frame, hsv)

            if roi is not None and roi[2] > 0 and roi[3] > 0:
                x, y, w, h = [int(v) for v in roi]
                finger_region = frame[y:y+h, x:x+w]

                # Extract color channels
                if finger_region.size > 0:
                    # Green channel is most sensitive to blood volume changes
                    green_mean = np.mean(finger_region[:, :, 1])
                    red_mean = np.mean(finger_region[:, :, 0])

                    green_values.append(green_mean)
                    red_values.append(red_mean)
                    self.timestamps.append(frame_count / self.fps)

            frame_count += 1

            # Show progress
            if frame_count % 100 == 0:
                print(f"Processed {frame_count}/{total_frames} frames...")

        cap.release()

        if len(green_values) == 0:
            raise ValueError("No valid frames were processed. Check video source and ROI.")

        # Store raw signal (inverted green channel for PPG)
        self.raw_signal = np.array(green_values)

        # Also store red channel for SpO2 estimation (optional)
        self.red_signal = np.array(red_values)

        print(f"Extracted {len(self.raw_signal)} samples")

        return self.raw_signal

    def _auto_detect_finger_roi(self, frame, hsv):
        """
        Automatically detect finger region using skin color detection.

        Args:
            frame: BGR frame
            hsv: HSV converted frame

        Returns:
            ROI tuple (x, y, w, h) or None
        """
        # Skin color range in HSV
        lower_skin = np.array([0, 20, 70], dtype=np.uint8)
        upper_skin = np.array([20, 255, 255], dtype=np.uint8)

        # Create mask for skin color
        mask = cv2.inRange(hsv, lower_skin, upper_skin)

        # Apply morphological operations
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.erode(mask, kernel, iterations=2)
        mask = cv2.dilate(mask, kernel, iterations=2)

        # Find contours
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            # Find largest contour (likely the finger)
            largest_contour = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest_contour)

            # Add some padding
            padding = 10
            x = max(0, x - padding)
            y = max(0, y - padding)
            w = min(frame.shape[1] - x, w + 2 * padding)
            h = min(frame.shape[0] - y, h + 2 * padding)

            return (x, y, w, h)

        # Default to center region if no skin detected
        h, w = frame.shape[:2]
        return (w//4, h//4, w//2, h//2)

    def filter_signal(self, lowcut=0.5, highcut=4.0):
        """
        Apply bandpass filter to remove noise and extract pulse signal.

        Args:
            lowcut: Low frequency cutoff (Hz) - removes baseline drift
            highcut: High frequency cutoff (Hz) - removes high-frequency noise

        Returns:
            Filtered PPG signal
        """
        if len(self.raw_signal) == 0:
            raise ValueError("No signal to filter. Run extract_ppg_from_video first.")

        # Normalize signal
        normalized = (self.raw_signal - np.mean(self.raw_signal)) / np.std(self.raw_signal)

        # Design Butterworth bandpass filter
        nyquist = self.fps / 2
        low = lowcut / nyquist
        high = highcut / nyquist

        # Ensure filter parameters are valid
        low = max(0.01, min(low, 0.99))
        high = max(low + 0.01, min(high, 0.99))

        b, a = butter(2, [low, high], btype='band')

        # Apply filter
        self.filtered_signal = filtfilt(b, a, normalized)

        return self.filtered_signal

    def analyze_pulse(self):
        """
        Analyze the filtered PPG signal to extract pulse characteristics.

        Returns:
            Dictionary containing pulse analysis results
        """
        if len(self.filtered_signal) == 0:
            self.filter_signal()

        # Find peaks (heartbeats)
        peaks, properties = find_peaks(
            self.filtered_signal,
            distance=int(self.fps * 0.5),  # Minimum 0.5s between beats
            prominence=0.1
        )

        if len(peaks) < 2:
            raise ValueError("Insufficient peaks detected. Check signal quality.")

        # Calculate inter-beat intervals (IBI)
        ibi = np.diff(peaks) / self.fps * 1000  # Convert to milliseconds

        # Calculate heart rate metrics
        avg_hr = 60000 / np.mean(ibi)  # BPM

        # Heart Rate Variability (HRV) - SDNN
        hrv_sdnn = np.std(ibi)

        # RMSSD (Root Mean Square of Successive Differences)
        successive_diff = np.diff(ibi)
        rmssd = np.sqrt(np.mean(successive_diff ** 2))

        # Analyze pulse waveform characteristics
        waveform_metrics = self._analyze_waveform(peaks)

        # Determine pulse characteristics based on analysis
        pulse_chars = self._determine_pulse_characteristics(avg_hr, hrv_sdnn, waveform_metrics)

        # Compile results
        results = {
            "recording_duration_seconds": self.recording_duration,
            "average_heart_rate_bpm": round(avg_hr, 1),
            "resting_heart_rate_bpm": round(np.min([avg_hr, avg_hr - 5]), 1),
            "heart_rate_variability_ms": round(hrv_sdnn, 1),
            "rmssd_ms": round(rmssd, 1),
            "pulse_characteristics": pulse_chars,
            "waveform_analysis": waveform_metrics,
            "signal_quality": self._assess_signal_quality(peaks, ibi),
            "recording_timestamp": datetime.now().isoformat() + "Z",
            "total_beats_detected": len(peaks),
            "analysis_metrics": {
                "mean_ibi_ms": round(np.mean(ibi), 1),
                "min_ibi_ms": round(np.min(ibi), 1),
                "max_ibi_ms": round(np.max(ibi), 1),
                "ibi_range_ms": round(np.max(ibi) - np.min(ibi), 1)
            }
        }

        return results

    def _analyze_waveform(self, peaks):
        """
        Analyze individual pulse waveform characteristics.

        Args:
            peaks: Indices of detected peaks

        Returns:
            Dictionary of waveform metrics
        """
        if len(peaks) < 3:
            return {
                "systolic_peak_amplitude": 0.5,
                "diastolic_notch_depth": 0.25,
                "pulse_wave_velocity": "moderate",
                "rise_time_ms": 120,
                "fall_time_ms": 280
            }

        # Analyze average waveform
        amplitudes = []
        rise_times = []
        fall_times = []
        diastolic_depths = []

        for i in range(1, len(peaks) - 1):
            peak_idx = peaks[i]
            prev_peak = peaks[i - 1]
            next_peak = peaks[i + 1]

            # Get waveform segment
            start_idx = (prev_peak + peak_idx) // 2
            end_idx = (peak_idx + next_peak) // 2

            if end_idx <= start_idx:
                continue

            segment = self.filtered_signal[start_idx:end_idx]

            if len(segment) < 5:
                continue

            # Peak amplitude
            amplitude = np.max(segment) - np.min(segment)
            amplitudes.append(amplitude)

            # Find peak position in segment
            peak_pos = np.argmax(segment)

            # Rise time (from start to peak)
            rise_time = peak_pos / self.fps * 1000
            rise_times.append(rise_time)

            # Fall time (from peak to end)
            fall_time = (len(segment) - peak_pos) / self.fps * 1000
            fall_times.append(fall_time)

            # Diastolic notch (look for local minimum after peak)
            if peak_pos < len(segment) - 5:
                post_peak = segment[peak_pos:]
                if len(post_peak) > 3:
                    diastolic_min = np.min(post_peak[:len(post_peak)//2])
                    notch_depth = (segment[peak_pos] - diastolic_min) / amplitude if amplitude > 0 else 0
                    diastolic_depths.append(notch_depth)

        # Calculate averages
        avg_amplitude = np.mean(amplitudes) if amplitudes else 0.5
        avg_rise = np.mean(rise_times) if rise_times else 120
        avg_fall = np.mean(fall_times) if fall_times else 280
        avg_diastolic = np.mean(diastolic_depths) if diastolic_depths else 0.25

        # Determine pulse wave velocity category
        if avg_rise < 100:
            pwv = "fast"
        elif avg_rise < 140:
            pwv = "moderate"
        else:
            pwv = "slow"

        return {
            "systolic_peak_amplitude": round(min(1.0, avg_amplitude), 2),
            "diastolic_notch_depth": round(min(1.0, avg_diastolic), 2),
            "pulse_wave_velocity": pwv,
            "rise_time_ms": round(avg_rise, 0),
            "fall_time_ms": round(avg_fall, 0)
        }

    def _determine_pulse_characteristics(self, heart_rate, hrv, waveform):
        """
        Determine qualitative pulse characteristics for Unani diagnosis.

        Args:
            heart_rate: Average heart rate in BPM
            hrv: Heart rate variability in ms
            waveform: Waveform analysis results

        Returns:
            Dictionary of pulse characteristics
        """
        # Rhythm assessment
        if hrv < 30:
            rhythm = "very regular"
        elif hrv < 50:
            rhythm = "regular"
        elif hrv < 80:
            rhythm = "regular with occasional variations"
        else:
            rhythm = "irregular with missed beats"

        # Strength assessment based on amplitude and rise time
        amplitude = waveform.get("systolic_peak_amplitude", 0.5)
        rise_time = waveform.get("rise_time_ms", 120)

        if amplitude > 0.7 and rise_time < 110:
            strength = "strong and bounding"
        elif amplitude > 0.5:
            strength = "moderate to strong"
        elif amplitude > 0.35:
            strength = "moderate"
        else:
            strength = "weak and thready"

        # Volume assessment
        if amplitude > 0.7:
            volume = "full and expansive"
        elif amplitude > 0.5:
            volume = "full"
        elif amplitude > 0.35:
            volume = "normal"
        else:
            volume = "thin and narrow"

        # Tension assessment based on diastolic characteristics
        diastolic = waveform.get("diastolic_notch_depth", 0.25)
        if diastolic > 0.4:
            tension = "high"
        elif diastolic > 0.25:
            tension = "moderate"
        else:
            tension = "low"

        # Rate pattern
        if heart_rate > 85:
            rate_pattern = "consistently elevated"
        elif heart_rate > 75:
            rate_pattern = "steady with minor elevations"
        elif heart_rate > 65:
            rate_pattern = "steady and normal"
        elif heart_rate > 55:
            rate_pattern = "slow and steady"
        else:
            rate_pattern = "slow with variations"

        return {
            "rhythm": rhythm,
            "strength": strength,
            "volume": volume,
            "tension": tension,
            "rate_pattern": rate_pattern
        }

    def _assess_signal_quality(self, peaks, ibi):
        """
        Assess the overall quality of the PPG signal.

        Args:
            peaks: Detected peak indices
            ibi: Inter-beat intervals

        Returns:
            Quality assessment string
        """
        # Check for consistent intervals
        ibi_cv = np.std(ibi) / np.mean(ibi) if np.mean(ibi) > 0 else 1

        # Check for sufficient peaks
        expected_peaks = self.recording_duration * 1.2  # Assuming ~72 BPM average
        peak_ratio = len(peaks) / expected_peaks

        if ibi_cv < 0.1 and 0.8 < peak_ratio < 1.3:
            return "excellent"
        elif ibi_cv < 0.2 and 0.6 < peak_ratio < 1.5:
            return "good"
        elif ibi_cv < 0.3 and 0.4 < peak_ratio < 2.0:
            return "moderate"
        else:
            return "poor"


class SymptomCollector:
    """
    Collects and organizes user symptoms for Unani diagnosis.
    """

    # Common symptoms categorized by system
    SYMPTOM_CATEGORIES = {
        "general": [
            "Fatigue and lethargy",
            "Feeling of internal heat",
            "Feeling cold internally",
            "Excessive sweating",
            "Weight changes",
            "Fever or chills"
        ],
        "digestive": [
            "Poor appetite",
            "Excessive appetite",
            "Constipation",
            "Diarrhea",
            "Bloating",
            "Heartburn",
            "Nausea"
        ],
        "respiratory": [
            "Shortness of breath",
            "Cough",
            "Excessive mucus",
            "Chest congestion"
        ],
        "neurological": [
            "Headaches",
            "Dizziness",
            "Anxiety",
            "Irritability",
            "Difficulty concentrating",
            "Memory problems",
            "Insomnia"
        ],
        "musculoskeletal": [
            "Joint pain",
            "Muscle cramps",
            "Stiffness",
            "Weakness"
        ],
        "skin": [
            "Dry skin",
            "Oily skin",
            "Acne",
            "Rashes",
            "Itching"
        ],
        "urinary": [
            "Frequent urination",
            "Burning urination",
            "Dark urine",
            "Reduced urination"
        ]
    }

    def __init__(self):
        self.symptoms = []

    def collect_interactive(self):
        """
        Interactively collect symptoms from the user via command line.

        Returns:
            List of symptom strings
        """
        print("\n" + "="*60)
        print("SYMPTOM COLLECTION")
        print("="*60)
        print("\nPlease report your symptoms. You can:")
        print("1. Type symptoms manually (one per line)")
        print("2. Enter 'list' to see common symptom categories")
        print("3. Enter 'done' when finished")
        print("-"*60)

        while True:
            user_input = input("\nEnter symptom (or 'list'/'done'): ").strip()

            if user_input.lower() == 'done':
                break
            elif user_input.lower() == 'list':
                self._show_symptom_categories()
            elif user_input.lower().startswith('cat '):
                # Show specific category
                category = user_input[4:].strip().lower()
                self._show_category_symptoms(category)
            elif user_input:
                self.symptoms.append(user_input)
                print(f"  ✓ Added: {user_input}")

        return self.symptoms

    def _show_symptom_categories(self):
        """Display available symptom categories."""
        print("\nAvailable symptom categories:")
        for i, category in enumerate(self.SYMPTOM_CATEGORIES.keys(), 1):
            print(f"  {i}. {category.title()}")
        print("\nType 'cat <category>' to see symptoms in that category")

    def _show_category_symptoms(self, category):
        """Display symptoms in a specific category."""
        if category in self.SYMPTOM_CATEGORIES:
            print(f"\n{category.title()} symptoms:")
            for symptom in self.SYMPTOM_CATEGORIES[category]:
                print(f"  - {symptom}")
        else:
            print(f"Category '{category}' not found. Type 'list' to see categories.")

    def collect_from_list(self, symptom_list):
        """
        Collect symptoms from a provided list.

        Args:
            symptom_list: List of symptom strings
        """
        self.symptoms = symptom_list

    def format_for_prompt(self):
        """
        Format collected symptoms for the diagnosis prompt.

        Returns:
            Formatted symptom string
        """
        if not self.symptoms:
            return "No symptoms reported"

        formatted = []
        for symptom in self.symptoms:
            formatted.append(f"- {symptom}")

        return "\n".join(formatted)

    def to_dict(self):
        """Convert symptoms to dictionary format."""
        return {"symptoms": self.symptoms, "count": len(self.symptoms)}


def real_time_capture(duration=60, display=True):
    """
    Capture PPG signal in real-time from camera.

    Args:
        duration: Recording duration in seconds
        display: Whether to display the video feed

    Returns:
        PPGPulseAnalyzer instance with captured data
    """
    analyzer = PPGPulseAnalyzer(recording_duration=duration)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise ValueError("Could not open camera")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    analyzer.fps = fps

    print("\n" + "="*60)
    print("REAL-TIME PPG CAPTURE")
    print("="*60)
    print("\nInstructions:")
    print("1. Place your fingertip gently on the camera lens")
    print("2. Ensure the finger covers the lens completely")
    print("3. Keep your hand steady during recording")
    print("4. Press 'q' to stop early")
    print("-"*60)

    input("\nPress Enter to start recording...")

    green_values = []
    red_values = []
    start_time = datetime.now()

    # For real-time display
    signal_buffer = deque(maxlen=300)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed >= duration:
            break

        # Extract color from center region
        h, w = frame.shape[:2]
        roi = frame[h//3:2*h//3, w//3:2*w//3]

        green_mean = np.mean(roi[:, :, 1])
        red_mean = np.mean(roi[:, :, 2])

        green_values.append(green_mean)
        red_values.append(red_mean)
        signal_buffer.append(green_mean)

        if display:
            # Create display frame
            display_frame = frame.copy()

            # Draw ROI rectangle
            cv2.rectangle(display_frame, (w//3, h//3), (2*w//3, 2*h//3), (0, 255, 0), 2)

            # Draw signal graph
            if len(signal_buffer) > 1:
                signal_array = np.array(signal_buffer)
                signal_normalized = (signal_array - np.min(signal_array)) / (np.max(signal_array) - np.min(signal_array) + 1e-6)

                for i in range(1, len(signal_normalized)):
                    pt1 = (int(i * w / 300), int((1 - signal_normalized[i-1]) * 100 + 20))
                    pt2 = (int((i+1) * w / 300), int((1 - signal_normalized[i]) * 100 + 20))
                    cv2.line(display_frame, pt1, pt2, (0, 255, 0), 1)

            # Show progress
            progress = int((elapsed / duration) * 100)
            cv2.putText(display_frame, f"Recording: {progress}%", (10, h-20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            cv2.imshow("PPG Capture - Press 'q' to stop", display_frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cap.release()
    cv2.destroyAllWindows()

    analyzer.raw_signal = np.array(green_values)
    analyzer.red_signal = np.array(red_values)
    analyzer.timestamps = [i / fps for i in range(len(green_values))]

    print(f"\nRecording complete! Captured {len(green_values)} samples")

    return analyzer


def generate_output(pulse_data, symptoms, output_format='json'):
    """
    Generate formatted output for the diagnosis prompt.

    Args:
        pulse_data: Dictionary of pulse analysis results
        symptoms: SymptomCollector instance or list of symptoms
        output_format: 'json' or 'text'

    Returns:
        Formatted output string
    """
    if output_format == 'json':
        output = {
            "pulse_data": pulse_data,
            "user_symptoms": symptoms if isinstance(symptoms, list) else symptoms.symptoms
        }
        return json.dumps(output, indent=2)
    else:
        # Text format for direct use in prompt
        pulse_json = json.dumps(pulse_data, indent=2)
        symptom_text = symptoms.format_for_prompt() if hasattr(symptoms, 'format_for_prompt') else "\n".join([f"- {s}" for s in symptoms])

        return f"""PULSE DATA:
```json
{pulse_json}
```

USER SYMPTOMS:
{symptom_text}
"""


def main():
    """Main function to run the PPG analyzer."""
    parser = argparse.ArgumentParser(description='PPG Pulse Analyzer for Unani Medicine')
    parser.add_argument('--source', type=str, default='camera',
                       help='Video source: "camera" or path to video file')
    parser.add_argument('--duration', type=int, default=60,
                       help='Recording duration in seconds')
    parser.add_argument('--output', type=str, default='pulse_analysis.json',
                       help='Output file path')
    parser.add_argument('--no-display', action='store_true',
                       help='Disable video display during capture')
    parser.add_argument('--symptoms-file', type=str,
                       help='Path to file containing symptoms (one per line)')

    args = parser.parse_args()

    print("\n" + "="*60)
    print("PPG PULSE ANALYZER FOR UNANI MEDICINE DIAGNOSIS")
    print("="*60)

    # Analyze pulse
    if args.source == 'camera':
        analyzer = real_time_capture(
            duration=args.duration,
            display=not args.no_display
        )
    else:
        analyzer = PPGPulseAnalyzer(recording_duration=args.duration)
        analyzer.extract_ppg_from_video(args.source)

    # Filter and analyze
    print("\nFiltering signal...")
    analyzer.filter_signal()

    print("Analyzing pulse characteristics...")
    pulse_data = analyzer.analyze_pulse()

    print("\n" + "-"*60)
    print("PULSE ANALYSIS RESULTS")
    print("-"*60)
    print(f"Heart Rate: {pulse_data['average_heart_rate_bpm']} BPM")
    print(f"HRV (SDNN): {pulse_data['heart_rate_variability_ms']} ms")
    print(f"Signal Quality: {pulse_data['signal_quality']}")
    print(f"Pulse Strength: {pulse_data['pulse_characteristics']['strength']}")
    print(f"Pulse Rhythm: {pulse_data['pulse_characteristics']['rhythm']}")

    # Collect symptoms
    symptom_collector = SymptomCollector()

    if args.symptoms_file:
        with open(args.symptoms_file, 'r') as f:
            symptoms = [line.strip() for line in f if line.strip()]
        symptom_collector.collect_from_list(symptoms)
    else:
        symptom_collector.collect_interactive()

    # Generate output
    output = generate_output(pulse_data, symptom_collector, 'json')

    # Save to file
    with open(args.output, 'w') as f:
        f.write(output)

    print(f"\n✓ Analysis saved to: {args.output}")

    # Also print formatted output for prompt
    print("\n" + "="*60)
    print("FORMATTED OUTPUT FOR DIAGNOSIS PROMPT")
    print("="*60)
    print(generate_output(pulse_data, symptom_collector, 'text'))

    return pulse_data, symptom_collector


if __name__ == "__main__":
    main()
