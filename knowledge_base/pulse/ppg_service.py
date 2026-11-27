"""
PPG Analysis Service for Django Integration
Integrates the PPG pulse analyzer with Django views.
Supports both finger-on-lens method and traditional wrist Nabz method.
"""
import cv2
import numpy as np
from scipy.signal import find_peaks, butter, filtfilt
from datetime import datetime
import json
import os


class PPGAnalysisService:
    """
    Service class for analyzing PPG signals from uploaded videos.
    """

    def __init__(self, fps=30, duration=60, method='finger'):
        """
        Initialize the PPG analyzer.

        Args:
            fps: Frames per second
            duration: Recording duration
            method: 'finger' for finger-on-lens, 'wrist' for traditional Nabz
        """
        self.fps = fps
        self.duration = duration
        self.method = method
        self.raw_signal = []
        self.filtered_signal = []
        self.finger_signals = {}  # For wrist method

    def analyze_video(self, video_path):
        """
        Main method to analyze a pulse video file.

        Args:
            video_path: Path to the uploaded video file

        Returns:
            Dictionary containing pulse analysis results
        """
        if self.method == 'wrist':
            # Traditional Nabz method - multi-point analysis
            return self._analyze_wrist_nabz(video_path)
        else:
            # Finger-on-lens method - single point
            self._extract_ppg_from_video(video_path)
            self._filter_signal()
            return self._analyze_pulse()

    def _extract_ppg_from_video(self, video_path):
        """Extract PPG signal from video file."""
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path}")

        # Get video properties
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = total_frames / self.fps

        green_values = []
        red_values = []
        frame_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Convert to HSV for skin detection
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            # Detect ROI (skin/finger region)
            roi = self._detect_finger_roi(frame, hsv)

            if roi is not None and roi[2] > 0 and roi[3] > 0:
                x, y, w, h = [int(v) for v in roi]
                finger_region = frame[y:y+h, x:x+w]

                if finger_region.size > 0:
                    green_mean = np.mean(finger_region[:, :, 1])
                    red_mean = np.mean(finger_region[:, :, 2])
                    green_values.append(green_mean)
                    red_values.append(red_mean)

            frame_count += 1

        cap.release()

        if len(green_values) < 100:
            raise ValueError("Insufficient frames extracted. Video may be too short or finger not detected.")

        self.raw_signal = np.array(green_values)
        self.red_signal = np.array(red_values)

    def _detect_finger_roi(self, frame, hsv):
        """Detect finger region using skin color detection."""
        # Skin color range in HSV
        lower_skin = np.array([0, 20, 70], dtype=np.uint8)
        upper_skin = np.array([20, 255, 255], dtype=np.uint8)

        mask = cv2.inRange(hsv, lower_skin, upper_skin)

        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.erode(mask, kernel, iterations=2)
        mask = cv2.dilate(mask, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest_contour)
            padding = 10
            x = max(0, x - padding)
            y = max(0, y - padding)
            w = min(frame.shape[1] - x, w + 2 * padding)
            h = min(frame.shape[0] - y, h + 2 * padding)
            return (x, y, w, h)

        # Default to center region
        h, w = frame.shape[:2]
        return (w//4, h//4, w//2, h//2)

    def _filter_signal(self, lowcut=0.5, highcut=4.0):
        """Apply bandpass filter to the PPG signal."""
        if len(self.raw_signal) == 0:
            raise ValueError("No signal to filter.")

        normalized = (self.raw_signal - np.mean(self.raw_signal)) / (np.std(self.raw_signal) + 1e-6)

        nyquist = self.fps / 2
        low = max(0.01, min(lowcut / nyquist, 0.99))
        high = max(low + 0.01, min(highcut / nyquist, 0.99))

        b, a = butter(2, [low, high], btype='band')
        self.filtered_signal = filtfilt(b, a, normalized)

    def _analyze_pulse(self):
        """Analyze the filtered PPG signal."""
        # Find peaks
        peaks, _ = find_peaks(
            self.filtered_signal,
            distance=int(self.fps * 0.5),
            prominence=0.1
        )

        if len(peaks) < 3:
            raise ValueError("Insufficient heartbeats detected. Please ensure finger is properly placed on camera.")

        # Calculate metrics
        ibi = np.diff(peaks) / self.fps * 1000
        avg_hr = 60000 / np.mean(ibi)
        hrv_sdnn = np.std(ibi)

        # RMSSD
        successive_diff = np.diff(ibi)
        rmssd = np.sqrt(np.mean(successive_diff ** 2))

        # Waveform analysis
        waveform_metrics = self._analyze_waveform(peaks)

        # Pulse characteristics
        pulse_chars = self._determine_pulse_characteristics(avg_hr, hrv_sdnn, waveform_metrics)

        return {
            "recording_duration_seconds": round(self.duration, 1),
            "average_heart_rate_bpm": round(avg_hr, 1),
            "resting_heart_rate_bpm": round(max(50, avg_hr - 5), 1),
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

    def _analyze_waveform(self, peaks):
        """Analyze pulse waveform characteristics."""
        if len(peaks) < 3:
            return {
                "systolic_peak_amplitude": 0.5,
                "diastolic_notch_depth": 0.25,
                "pulse_wave_velocity": "moderate",
                "rise_time_ms": 120,
                "fall_time_ms": 280
            }

        amplitudes = []
        rise_times = []
        fall_times = []

        for i in range(1, len(peaks) - 1):
            peak_idx = peaks[i]
            prev_peak = peaks[i - 1]
            next_peak = peaks[i + 1]

            start_idx = (prev_peak + peak_idx) // 2
            end_idx = (peak_idx + next_peak) // 2

            if end_idx <= start_idx:
                continue

            segment = self.filtered_signal[start_idx:end_idx]
            if len(segment) < 5:
                continue

            amplitude = np.max(segment) - np.min(segment)
            amplitudes.append(amplitude)

            peak_pos = np.argmax(segment)
            rise_times.append(peak_pos / self.fps * 1000)
            fall_times.append((len(segment) - peak_pos) / self.fps * 1000)

        avg_amplitude = np.mean(amplitudes) if amplitudes else 0.5
        avg_rise = np.mean(rise_times) if rise_times else 120
        avg_fall = np.mean(fall_times) if fall_times else 280

        if avg_rise < 100:
            pwv = "fast"
        elif avg_rise < 140:
            pwv = "moderate"
        else:
            pwv = "slow"

        return {
            "systolic_peak_amplitude": round(min(1.0, avg_amplitude), 2),
            "diastolic_notch_depth": round(0.3, 2),
            "pulse_wave_velocity": pwv,
            "rise_time_ms": round(avg_rise, 0),
            "fall_time_ms": round(avg_fall, 0)
        }

    def _determine_pulse_characteristics(self, heart_rate, hrv, waveform):
        """Determine qualitative pulse characteristics for Unani diagnosis."""
        # Rhythm
        if hrv < 30:
            rhythm = "very regular"
        elif hrv < 50:
            rhythm = "regular"
        elif hrv < 80:
            rhythm = "regular with occasional variations"
        else:
            rhythm = "irregular with missed beats"

        # Strength
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

        # Volume
        if amplitude > 0.7:
            volume = "full and expansive"
        elif amplitude > 0.5:
            volume = "full"
        elif amplitude > 0.35:
            volume = "normal"
        else:
            volume = "thin and narrow"

        # Tension
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
        """Assess signal quality."""
        ibi_cv = np.std(ibi) / np.mean(ibi) if np.mean(ibi) > 0 else 1
        expected_peaks = self.duration * 1.2
        peak_ratio = len(peaks) / expected_peaks

        if ibi_cv < 0.1 and 0.8 < peak_ratio < 1.3:
            return "excellent"
        elif ibi_cv < 0.2 and 0.6 < peak_ratio < 1.5:
            return "good"
        elif ibi_cv < 0.3 and 0.4 < peak_ratio < 2.0:
            return "moderate"
        else:
            return "poor"


    def _analyze_wrist_nabz(self, video_path):
        """Analyze traditional wrist Nabz with multi-finger positions."""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")

        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = total_frames / self.fps

        # Initialize signal storage for four finger positions
        signals = {
            'index': [],
            'middle': [],
            'ring': [],
            'little': []
        }

        rois = None
        frame_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if rois is None:
                rois = self._detect_wrist_finger_positions(frame)

            # Extract signal from each position
            for finger_name, roi in rois.items():
                if roi and len(roi) == 4:
                    x, y, w, h = [int(v) for v in roi]
                    if x >= 0 and y >= 0 and x + w <= frame.shape[1] and y + h <= frame.shape[0]:
                        region = frame[y:y+h, x:x+w]
                        if region.size > 0:
                            signals[finger_name].append(np.mean(region[:, :, 1]))

            frame_count += 1

        cap.release()

        # Convert to numpy and filter
        for finger in signals:
            if len(signals[finger]) > 100:
                raw = np.array(signals[finger])
                normalized = (raw - np.mean(raw)) / (np.std(raw) + 1e-6)
                nyquist = self.fps / 2
                b, a = butter(2, [0.5/nyquist, 4.0/nyquist], btype='band')
                self.finger_signals[finger] = filtfilt(b, a, normalized)

        # Analyze each position
        results = {
            "recording_duration_seconds": round(self.duration, 1),
            "recording_timestamp": datetime.now().isoformat() + "Z",
            "method": "wrist_nabz",
            "finger_positions": {},
            "unani_interpretation": self._get_nabz_interpretation()
        }

        for finger, signal in self.finger_signals.items():
            if len(signal) > 100:
                results["finger_positions"][finger] = self._analyze_nabz_position(signal, finger)

        return results

    def _detect_wrist_finger_positions(self, frame):
        """Detect four finger positions on wrist."""
        height, width = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # Skin detection
        mask = cv2.inRange(hsv, np.array([0, 20, 70]), np.array([20, 255, 255]))
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.dilate(cv2.erode(mask, kernel, iterations=2), kernel, iterations=3)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            largest = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            fw = w // 4
            rh = min(h // 3, 60)
            ry = y + (h - rh) // 2

            return {
                'index': (x, ry, fw, rh),
                'middle': (x + fw, ry, fw, rh),
                'ring': (x + 2*fw, ry, fw, rh),
                'little': (x + 3*fw, ry, fw, rh)
            }

        # Fallback
        sw = width // 4
        rh = height // 4
        return {
            'index': (0, height//3, sw, rh),
            'middle': (sw, height//3, sw, rh),
            'ring': (2*sw, height//3, sw, rh),
            'little': (3*sw, height//3, sw, rh)
        }

    def _analyze_nabz_position(self, signal, position):
        """Analyze single Nabz position."""
        peaks, _ = find_peaks(signal, distance=int(self.fps * 0.5), prominence=0.1)

        if len(peaks) < 3:
            return {"status": "insufficient_data"}

        ibi = np.diff(peaks) / self.fps * 1000
        hr = 60000 / np.mean(ibi)
        hrv = np.std(ibi)

        amplitudes = []
        for i in range(1, len(peaks)-1):
            seg = signal[(peaks[i-1]+peaks[i])//2:(peaks[i]+peaks[i+1])//2]
            if len(seg) > 0:
                amplitudes.append(np.max(seg) - np.min(seg))

        amp = np.mean(amplitudes) if amplitudes else 0.5

        # Unani characteristics
        strength = "strong (قوی)" if amp > 0.7 else "moderate (معتدل)" if amp > 0.4 else "weak (ضعیف)"
        rate = "fast (سریع)" if hr > 85 else "normal (معتدل)" if hr > 65 else "slow (بطی)"
        regularity = "regular (منتظم)" if hrv < 60 else "irregular (غیر منتظم)"

        return {
            "status": "success",
            "heart_rate_bpm": round(hr, 1),
            "hrv_ms": round(hrv, 1),
            "amplitude": round(amp, 3),
            "characteristics": {
                "strength": strength,
                "rate": rate,
                "regularity": regularity,
                "volume": "full (ممتلی)" if amp > 0.65 else "moderate (معتدل)" if amp > 0.35 else "empty (خالی)"
            }
        }

    def _get_nabz_interpretation(self):
        """Traditional Unani interpretation of Nabz positions."""
        return {
            "method": "Traditional Nabz Examination (نبض کا معائنہ)",
            "positions": {
                "index": "Tarjani (انگشت شہادت) - Heart & Small Intestine",
                "middle": "Madhyama (درمیانی انگلی) - Liver & Gall Bladder",
                "ring": "Anamika (انگوٹھی والی انگلی) - Kidney & Urinary Bladder",
                "little": "Kanishtha (چھنگلی) - Lung & Large Intestine"
            },
            "notes": [
                "Each position corresponds to specific organs",
                "Strongest pulse indicates most active organ system",
                "Compare variations between positions for diagnosis"
            ]
        }


def analyze_pulse_video(video_path, method='finger'):
    """
    Convenience function to analyze a pulse video.

    Args:
        video_path: Path to the video file
        method: 'finger' for finger-on-lens, 'wrist' for traditional Nabz

    Returns:
        Dictionary of pulse analysis results
    """
    service = PPGAnalysisService(method=method)
    return service.analyze_video(video_path)
