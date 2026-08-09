# Traditional Nabz (Wrist Pulse) Recording Guide

## نبض کی ویڈیو بنانے کی رہنمائی

This guide explains how to record wrist pulse video for traditional Unani medicine Nabz examination using a mobile camera.

---

## Overview

In traditional Unani medicine, a Hakim examines the pulse (Nabz) by placing **three to four fingers** on the **radial artery** at the wrist. Each finger position corresponds to specific organ systems:

| Finger Position | Urdu Name | Organ Correspondence |
|----------------|-----------|---------------------|
| **Index Finger** (near thumb) | انگشت شہادت (Tarjani) | Heart (قلب) & Small Intestine |
| **Middle Finger** | درمیانی انگلی (Madhyama) | Liver (جگر) & Gall Bladder |
| **Ring Finger** | انگوٹھی والی انگلی (Anamika) | Kidney (گردہ) & Urinary Bladder |
| **Little Finger** (optional) | چھنگلی (Kanishtha) | Lung (پھیپھڑے) & Large Intestine |

---

## Equipment Needed

1. **Smartphone with camera** (preferably with good low-light performance)
2. **Phone stand or tripod** (highly recommended)
3. **Good lighting** (natural daylight or white LED light)
4. **Clean surface** to rest the hand

---

## Recording Setup

### Method 1: Top-Down View (Recommended)

This method captures the wrist from above, showing all four finger positions.

#### Step-by-Step Instructions:

1. **Position the Phone:**
   - Mount phone on a stand/tripod pointing straight down
   - Position 20-30 cm (8-12 inches) above the table
   - Ensure camera is parallel to the table surface

2. **Prepare the Wrist:**
   - Place left wrist palm-up on a dark-colored cloth/mat
   - Position wrist in center of camera frame
   - Keep wrist relaxed, not flexed

3. **Lighting Setup:**
   - Use natural daylight from the side (not directly above)
   - Or use a desk lamp positioned at 45° angle
   - Avoid harsh shadows on the wrist
   - Skin should appear natural color, not washed out

4. **Mark the Pulse Points (Optional):**
   - Locate radial artery (thumb side of wrist, just below wrist crease)
   - Can mark with washable pen: 4 dots approximately 1cm apart
   - This helps the algorithm identify finger positions

5. **Camera Settings:**
   - Use rear camera (better quality)
   - Set video to **1080p or 720p**
   - **30 FPS** (frames per second)
   - Focus on the wrist (tap on wrist area to lock focus)
   - Turn OFF flash (use ambient lighting instead)

6. **Recording:**
   - Start recording
   - Place three fingers (index, middle, ring) on the radial artery
   - Keep fingers aligned, parallel to each other
   - Maintain gentle, consistent pressure
   - **Keep absolutely still for 60 seconds**
   - Avoid talking or moving during recording

---

### Method 2: Side View

This method captures pulse from the side, showing finger pressure depth.

#### Setup:
1. Position phone on its side, pointing at the wrist
2. Hand rests palm-up on table
3. Camera captures profile view of fingers on wrist
4. Same lighting and recording guidelines as Method 1

---

## Critical Recording Tips

### ✅ DO:
- **Rest your arm on a stable surface** - eliminates hand shake
- **Keep fingers parallel** and aligned along the artery
- **Maintain consistent light pressure** throughout
- **Record for full 60 seconds minimum** (90 seconds ideal)
- **Stay relaxed** - tension affects pulse reading
- **Wait 5 minutes** after exercise before recording
- **Avoid caffeine/smoking** 30 minutes before recording
- **Record in sitting position** with back support

### ❌ DON'T:
- Don't press too hard (occludes artery)
- Don't press too lightly (misses pulse)
- Don't move fingers during recording
- Don't talk or laugh during recording
- Don't record immediately after meals
- Don't use flash (causes glare and color distortion)
- Don't record in poor lighting
- Don't hold phone in hand (causes shake)

---

## Optimal Recording Conditions

### Time of Day:
- **Best:** Early morning (after waking, before breakfast)
- **Good:** Late afternoon (4-6 PM)
- **Avoid:** Immediately after meals or exercise

### Patient Preparation:
1. **Rest for 5 minutes** before recording
2. **Sit comfortably** with back supported
3. **Extend arm** naturally on table
4. **Breathe normally** - don't hold breath
5. **Relax shoulders** and neck

### Environmental:
- **Temperature:** Room temperature (20-24°C)
- **Lighting:** Bright but not harsh
- **Noise:** Quiet environment (for patient relaxation)
- **Position:** Seated, arm at heart level

---

## Video Specifications

| Parameter | Recommended Setting |
|-----------|-------------------|
| **Resolution** | 1080p (1920x1080) or 720p |
| **Frame Rate** | 30 FPS |
| **Duration** | 60-90 seconds |
| **Format** | MP4, MOV |
| **File Size** | 50-200 MB |
| **Orientation** | Landscape (horizontal) |
| **Focus** | Manual focus on wrist |
| **Exposure** | Auto (ensure skin is visible, not too dark/bright) |

---

## Finger Positioning Guide

### Traditional Three-Finger Method:

```
        Thumb side ←  → Little finger side
        
  Index    Middle    Ring      
    ●        ●        ●       ← Radial artery
    │        │        │
    │        │        │
  ═══════════════════════    ← Wrist
    
  Position fingers:
  - 1 cm below wrist crease
  - 1 cm apart from each other
  - Parallel alignment
  - Light, equal pressure
```

### Pressure Levels:
- **Superficial (سطحی):** Light touch - detects surface pulse
- **Medium (درمیانی):** Normal pressure - standard examination
- **Deep (گہرا):** Firm pressure - detects deep pulse qualities

For video recording, use **medium pressure** throughout.

---

## Troubleshooting Common Issues

### Issue: Pulse Not Detected
**Solutions:**
- Verify finger placement on radial artery (thumb side of wrist)
- Increase lighting slightly
- Ensure fingers are visible in frame
- Check that skin color is visible (not too dark in video)
- Use more pressure (but not excessive)

### Issue: Video Too Dark
**Solutions:**
- Increase ambient lighting
- Move closer to window (natural light)
- Use desk lamp from the side
- Adjust camera exposure (+1 or +2)

### Issue: Video Shaky
**Solutions:**
- Use phone stand/tripod (essential!)
- Rest forearm on table
- Ensure table is stable
- Wait a few seconds after pressing record

### Issue: Skin Appears Washed Out
**Solutions:**
- Reduce lighting intensity
- Move light source further away
- Use diffused light (through white paper/cloth)
- Adjust camera exposure (-1)

---

## Analysis Process

After recording, the video is analyzed as follows:

1. **ROI Detection:** Algorithm identifies four finger positions on wrist
2. **Signal Extraction:** Green channel PPG extracted from each position
3. **Filtering:** Bandpass filter (0.5-4 Hz) removes noise
4. **Peak Detection:** Identifies heartbeats at each position
5. **Comparative Analysis:** Compares pulse qualities between positions
6. **Unani Interpretation:** Maps findings to organ systems

---

## Expected Results

The analysis will provide:

### For Each Finger Position:
- Heart rate (BPM)
- Heart rate variability (HRV)
- Pulse amplitude
- Pulse strength: Strong (قوی), Moderate (معتدل), Weak (ضعیف)
- Pulse rate: Fast (سریع), Normal (معتدل), Slow (بطی)
- Pulse regularity: Regular (منتظم), Irregular (غیر منتظم)
- Pulse volume: Full (ممتلی), Moderate, Empty (خالی)

### Comparative Analysis:
- Strongest pulse position → Most active organ system
- Weakest pulse position → Possible deficiency
- Variation pattern → Imbalance indicators

### Unani Interpretation:
- Organ system correspondence
- Potential Mizaj indicators
- Recommendations for further symptoms correlation

---

## Sample Recording Script

Follow this script for consistent recordings:

```
1. Set up camera (top-down, 25cm above wrist)
2. Adjust lighting (even, no harsh shadows)
3. Position wrist in frame, palm up
4. Focus camera on wrist (tap to focus)
5. REST for 2 minutes
6. Start recording
7. Place 3 fingers gently on radial artery
8. Hold still for 60 seconds
9. Breathe normally, don't talk
10. Stop recording after 60+ seconds
```

---

## Quality Checklist

Before submitting video, verify:

- [ ] Video is 60+ seconds long
- [ ] Wrist is clearly visible
- [ ] All three/four finger positions visible
- [ ] Lighting is adequate (skin color natural)
- [ ] Video is stable (no shaking)
- [ ] Fingers remain still throughout
- [ ] Adequate contrast (fingers distinguishable from wrist)
- [ ] File size < 200 MB
- [ ] Format is MP4 or MOV

---

## Scientific Basis

This method combines:

1. **Traditional Unani Nabz Examination:** 
   - Four finger positions
   - Organ system correspondence
   - Pulse quality assessment

2. **Modern PPG (Photoplethysmography):**
   - Detects blood volume changes via camera
   - Non-invasive measurement
   - Validated for heart rate monitoring

3. **Nazria Mufrad Aza Principles:**
   - Multi-organ system analysis
   - Temperament (Mizaj) indicators
   - Bodily movements (Tehreek) correlation

---

## Important Notes

⚠️ **Medical Disclaimer:**
This is a diagnostic aid tool based on traditional Unani medicine principles. It does NOT replace professional medical consultation. Always consult a qualified Hakim or physician for health concerns.

🔬 **Research Tool:**
This method is designed for educational and research purposes in traditional Unani medicine pulse diagnosis.

📊 **Data Quality:**
Analysis quality depends heavily on video quality. Follow recording guidelines carefully for best results.

---

## Quick Reference: Recording Summary

| What | How | Why |
|------|-----|-----|
| **Setup** | Phone on stand, top-down view | Stable, clear view |
| **Distance** | 20-30 cm above wrist | Optimal focus range |
| **Lighting** | Natural/LED from side | Even skin tone visibility |
| **Position** | Wrist palm-up, arm on table | Stability, relaxation |
| **Fingers** | 3-4 fingers on radial artery | Traditional Nabz positions |
| **Pressure** | Medium, consistent | Accurate pulse detection |
| **Duration** | 60-90 seconds | Statistical reliability |
| **Stillness** | No movement or talking | Clean signal |

---

## Contact & Support

For questions about:
- Recording technique
- Video quality issues
- Analysis interpretation
- Unani medicine principles

Refer to the project documentation or consult a qualified Unani medicine practitioner.

---

**Version:** 1.0  
**Date:** 2026-08-09  
**Based on:** Nazria Mufrad Aza by Hakim Dost Muhammad Sabir Multani
