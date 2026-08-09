#!/usr/bin/env python3
"""
Traditional Wrist Pulse Analyzer (Nabz Examination)
Based on classical Unani medicine - examining pulse at multiple finger positions on the radial artery
"""

import cv2
import numpy as np
from scipy import signal
from scipy.signal import find_peaks, butter, filtfilt
from datetime import datetime
import json


class WristPulseAnalyzer:
    """
    Analyzes pulse from wrist using four finger positions (traditional Nabz examination).

    Traditional Unani Nabz positions:
    - Index finger (Tarjani) - Heart & Small Intestine
    - Middle finger (Madhyama) - Liver & Gall Bladder
    - Ring finger (Anamika) - Kidney & Urinary Bladder
    - Little finger (Kanishtha) - Lung & Large Intestine (optional)
    """

    def __init__(self, fps=30, duration=60):
        self.fps = fps
        self.duration = duration
        self.finger_signals = {
            'index': [],      # Tarjani - nearest to thumb
            'middle': [],     # Madhyama
            'ring': [],       # Anamika
            'little': []      # Kanishtha - optional
        }
        self.filtered_signals = {}

    def analyze_wrist_video(self, video_path, method='auto'):
        """
        Analyze pulse video of wrist with multiple finger positions.

        Args:
            video_path: Path to the video file
            method: 'auto' for automatic detection, 'manual' for user-defined ROIs

        Returns:
            Dictionary containing multi-point pulse analysis
        """
        # Extract PPG signals from four finger positions
        self._extract_multi_point_ppg(video_path, method)

        # Filter all signals
        self._filter_all_signals()

        # Analyze each position
        results = self._analyze_multi_point_pulse()

        return results

    def _extract_multi_point_ppg(self, video_path, method='auto'):
        """Extract PPG signals from four finger positions on wrist."""
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")

        # Get video properties
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = total_frames / self.fps

        print(f"Analyzing wrist pulse video...")
        print(f"FPS: {self.fps}, Duration: {self.duration:.1f}s")

        # Storage for each finger position
        signals = {
            'index': [],
            'middle': [],
            'ring': [],
            'little': []
        }

        # ROI (Region of Interest) for each finger
        rois = None
        frame_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Detect or use defined ROIs
            if rois is None:
                rois = self._detect_finger_positions(frame, method)

            # Extract signal from each ROI
            for finger_name, roi in rois.items():
                if roi is not None and len(roi) == 4:
                    x, y, w, h = [int(v) for v in roi]

                    # Ensure ROI is within frame bounds
                    if x >= 0 and y >= 0 and x + w <= frame.shape[1] and y + h <= frame.shape[0]:
                        region = frame[y:y+h, x:x+w]

                        if region.size > 0:
                            # Green channel for PPG
                            green_mean = np.mean(region[:, :, 1])
                            signals[finger_name].append(green_mean)

            frame_count += 1

            if frame_count % 100 == 0:
                print(f"Processed {frame_count}/{total_frames} frames")

        cap.release()

        # Convert to numpy arrays
        for finger_name in signals:
            if len(signals[finger_name]) > 0:
                self.finger_signals[finger_name] = np.array(signals[finger_name])
            else:
                print(f"Warning: No signal detected for {finger_name} finger")
                self.finger_signals[finger_name] = np.array([])

        print(f"Extraction complete. Signals captured for: {[k for k, v in self.finger_signals.items() if len(v) > 0]}")

    def _detect_finger_positions(self, frame, method='auto'):
        """
        Detect the four finger positions on the wrist.

        Returns:
            Dictionary of ROIs for each finger position
        """
        height, width = frame.shape[:2]

        if method == 'auto':
            # Automatic detection based on skin color and positioning
            # In a traditional wrist pulse video, fingers are aligned horizontally
            # We divide the skin region into 4 zones

            # Detect wrist/skin region
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            # Skin color range
            lower_skin = np.array([0, 20, 70], dtype=np.uint8)
            upper_skin = np.array([20, 255, 255], dtype=np.uint8)

            mask = cv2.inRange(hsv, lower_skin, upper_skin)

            # Morphological operations
            kernel = np.ones((5, 5), np.uint8)
            mask = cv2.erode(mask, kernel, iterations=2)
            mask = cv2.dilate(mask, kernel, iterations=3)

            # Find the largest contour (wrist region)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if contours:
                largest_contour = max(contours, key=cv2.contourArea)
                x, y, w, h = cv2.boundingRect(largest_contour)

                # Divide into 4 horizontal segments for 4 fingers
                # Traditional positioning: Index (thumb side) to Little finger
                finger_width = w // 4
                roi_height = min(h // 3, 60)  # ROI height (centered vertically)
                roi_y = y + (h - roi_height) // 2

                rois = {
                    'index': (x, roi_y, finger_width, roi_height),
                    'middle': (x + finger_width, roi_y, finger_width, roi_height),
                    'ring': (x + 2 * finger_width, roi_y, finger_width, roi_height),
                    'little': (x + 3 * finger_width, roi_y, finger_width, roi_height)
                }
            else:
                # Fallback: divide frame into 4 equal horizontal segments
                segment_width = width // 4
                roi_height = height // 4
                roi_y = height // 3

                rois = {
                    'index': (0, roi_y, segment_width, roi_height),
                    'middle': (segment_width, roi_y, segment_width, roi_height),
                    'ring': (2 * segment_width, roi_y, segment_width, roi_height),
                    'little': (3 * segment_width, roi_y, segment_width, roi_height)
                }
        else:
            # Manual selection would be done interactively
            # For now, use default positions
            segment_width = width // 4
            roi_height = height // 4
            roi_y = height // 3

            rois = {
                'index': (0, roi_y, segment_width, roi_height),
                'middle': (segment_width, roi_y, segment_width, roi_height),
                'ring': (2 * segment_width, roi_y, segment_width, roi_height),
                'little': (3 * segment_width, roi_y, segment_width, roi_height)
            }

        return rois

    def _filter_all_signals(self, lowcut=0.5, highcut=4.0):
        """Apply bandpass filter to all finger signals."""
        nyquist = self.fps / 2
        low = max(0.01, min(lowcut / nyquist, 0.99))
        high = max(low + 0.01, min(highcut / nyquist, 0.99))

        b, a = butter(2, [low, high], btype='band')

        for finger_name, raw_signal in self.finger_signals.items():
            if len(raw_signal) > 100:
                # Normalize
                normalized = (raw_signal - np.mean(raw_signal)) / (np.std(raw_signal) + 1e-6)

                # Filter
                filtered = filtfilt(b, a, normalized)
                self.filtered_signals[finger_name] = filtered
            else:
                self.filtered_signals[finger_name] = np.array([])

    def _analyze_multi_point_pulse(self):
        """Analyze pulse from all four finger positions."""
        results = {
            "recording_duration_seconds": round(self.duration, 1),
            "recording_timestamp": datetime.now().isoformat() + "Z",
            "method": "wrist_multi_point",
            "finger_positions": {},
            "comparative_analysis": {},
            "unani_interpretation": {}
        }

        # Analyze each finger position
        for finger_name, filtered_signal in self.filtered_signals.items():
            if len(filtered_signal) > 100:
                finger_analysis = self._analyze_single_position(filtered_signal, finger_name)
                results["finger_positions"][finger_name] = finger_analysis
            else:
                results["finger_positions"][finger_name] = {
                    "status": "insufficient_data",
                    "message": f"No valid signal detected at {finger_name} finger position"
                }

        # Comparative analysis between positions
        results["comparative_analysis"] = self._compare_positions()

        # Unani medicine interpretation
        results["unani_interpretation"] = self._unani_interpretation()

        return results

    def _analyze_single_position(self, signal, position_name):
        """Analyze pulse at a single finger position."""
        # Find peaks
        peaks, properties = find_peaks(
            signal,
            distance=int(self.fps * 0.5),
            prominence=0.1
        )

        if len(peaks) < 3:
            return {
                "status": "insufficient_peaks",
                "message": f"Not enough heartbeats detected at {position_name} position"
            }

        # Calculate metrics
        ibi = np.diff(peaks) / self.fps * 1000  # Inter-beat interval in ms
        avg_hr = 60000 / np.mean(ibi)
        hrv = np.std(ibi)

        # Amplitude analysis
        amplitudes = []
        for i in range(1, len(peaks) - 1):
            start = (peaks[i-1] + peaks[i]) // 2
            end = (peaks[i] + peaks[i+1]) // 2
            segment = signal[start:end]
            if len(segment) > 0:
                amplitudes.append(np.max(segment) - np.min(segment))

        avg_amplitude = np.mean(amplitudes) if amplitudes else 0.5

        # Pulse characteristics for this position
        characteristics = self._determine_position_characteristics(avg_hr, hrv, avg_amplitude)

        return {
            "status": "success",
            "heart_rate_bpm": round(avg_hr, 1),
            "hrv_ms": round(hrv, 1),
            "average_amplitude": round(avg_amplitude, 3),
            "total_beats": len(peaks),
            "characteristics": characteristics,
            "quality": self._assess_quality(ibi)
        }

    def _determine_position_characteristics(self, hr, hrv, amplitude):
        """Determine pulse characteristics for Unani diagnosis."""
        # Based on traditional Unani pulse qualities

        # Strength (Quwwat)
        if amplitude > 0.7:
            strength = "strong (qawi)"
        elif amplitude > 0.4:
            strength = "moderate (mutadil)"
        else:
            strength = "weak (za'if)"

        # Rate (Harkat)
        if hr > 85:
            rate = "fast (sari)"
        elif hr > 65:
            rate = "normal (mutadil)"
        else:
            rate = "slow (bati)"

        # Regularity (Intizam)
        if hrv < 35:
            regularity = "very regular (muntazim)"
        elif hrv < 60:
            regularity = "regular (mutadil)"
        else:
            regularity = "irregular (ghair-muntazim)"

        # Volume (Hajm)
        if amplitude > 0.65:
            volume = "full (mumtali)"
        elif amplitude > 0.35:
            volume = "moderate (mutadil)"
        else:
            volume = "empty (khali)"

        return {
            "strength": strength,
            "rate": rate,
            "regularity": regularity,
            "volume": volume
        }

    def _compare_positions(self):
        """Compare pulse characteristics across finger positions."""
        comparison = {
            "signal_quality_ranking": [],
            "amplitude_comparison": {},
            "rate_variation": {},
            "clinical_significance": []
        }

        # Rank positions by signal quality
        quality_scores = {}
        for finger, data in self.filtered_signals.items():
            if len(data) > 100:
                # Simple quality metric: signal-to-noise ratio
                quality = np.std(data) / (np.mean(np.abs(data)) + 1e-6)
                quality_scores[finger] = quality

        comparison["signal_quality_ranking"] = sorted(
            quality_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Compare amplitudes
        amplitudes = {}
        for finger, analysis in self.filtered_signals.items():
            if len(analysis) > 0:
                amplitudes[finger] = np.max(analysis) - np.min(analysis)

        comparison["amplitude_comparison"] = amplitudes

        # Clinical significance based on Unani principles
        if quality_scores:
            strongest_position = max(quality_scores, key=quality_scores.get)
            comparison["clinical_significance"].append(
                f"Strongest pulse detected at {strongest_position} finger position"
            )

            # Traditional Unani organ correspondence
            organ_map = {
                'index': 'Heart & Small Intestine',
                'middle': 'Liver & Gall Bladder',
                'ring': 'Kidney & Urinary Bladder',
                'little': 'Lung & Large Intestine'
            }

            if strongest_position in organ_map:
                comparison["clinical_significance"].append(
                    f"May indicate activity/imbalance in: {organ_map[strongest_position]}"
                )

        return comparison

    def _unani_interpretation(self):
        """Interpret findings according to Unani medicine principles."""
        interpretation = {
            "pulse_type": "multi_point_nabz",
            "examination_method": "Four finger positions on radial artery",
            "traditional_positions": {
                "index_finger": "Tarjani - Heart (Qalb) & Small Intestine",
                "middle_finger": "Madhyama - Liver (Jigar) & Gall Bladder",
                "ring_finger": "Anamika - Kidney (Gurda) & Urinary Bladder",
                "little_finger": "Kanishtha - Lung (Phephre) & Large Intestine"
            },
            "interpretation_notes": [
                "Each finger position corresponds to specific organs in Unani medicine",
                "Pulse quality variations between positions indicate organ-specific conditions",
                "Strongest pulse indicates most active organ system",
                "Compare with symptoms for comprehensive Mizaj diagnosis"
            ]
        }

        return interpretation

    def _assess_quality(self, ibi):
        """Assess signal quality."""
        if len(ibi) < 3:
            return "poor"

        cv = np.std(ibi) / np.mean(ibi)

        if cv < 0.15:
            return "excellent"
        elif cv < 0.25:
            return "good"
        elif cv < 0.35:
            return "moderate"
        else:
            return "poor"


def analyze_wrist_pulse_video(video_path, method='auto'):
    """
    Convenience function to analyze a wrist pulse video.

    Args:
        video_path: Path to the video file
        method: 'auto' or 'manual' ROI detection

    Returns:
        Dictionary of multi-point pulse analysis
    """
    analyzer = WristPulseAnalyzer()
    return analyzer.analyze_wrist_video(video_path, method)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python traditional_nabz_analyzer.py <video_path>")
        sys.exit(1)

    video_path = sys.argv[1]

    print("\n" + "="*70)
    print("TRADITIONAL NABZ (PULSE) ANALYZER")
    print("Based on Unani Medicine - Four Finger Wrist Examination")
    print("="*70 + "\n")

    results = analyze_wrist_pulse_video(video_path)

    print("\n" + json.dumps(results, indent=2))

    # Save results
    output_file = "nabz_analysis_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n✓ Results saved to: {output_file}")
