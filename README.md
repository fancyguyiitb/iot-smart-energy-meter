[![Review Assignment Due Date](https://classroom.github.com/assets/deadline-readme-button-22041afd0340ce965d47ae6ef1cefeee28c7c493a6346c4f15d667ab976d596c.svg)](https://classroom.github.com/a/NJLWAR4a)

![Docs Added](https://github.com/edl-iitb/edl-25-project-submission-edl25_tue17/actions/workflows/classroom.yml/badge.svg)

<!-- DON'T MODIFY ANYTHING ABOVE -->
<!-- Modify from here -->

# Project Overview

### Project Name: [IOT Enabled 3-Phase Power Quality and Energy Meter]()

### Team Number: [TUE-17]()

### Team Members

- [Saurabh Kumar](https://www.github.com/srbh001)
- [Aryan Tamboli](https://www.github.com/Aryan-Tamboli)
- [Ayush Gaur](https://www.github.com/gaurkama)
- [Cherish Jain](https://www.github.com/CJain2004)
- [Sarthak Niranjan](https://www.github.com/fancyguyiitb)

### Problem Statement and Solution

We developed an IoT-based 3-phase smart energy meter that enables users to monitor power parameters, analyze power quality, and remotely control the power supply. The system supports real-time data logging, mobile access, and predictive maintenance via harmonics analysis.  
For setup and usage instructions, refer to [Manual.md](Manual.md)..

#### Team & Contributions

Our team of 5 worked collaboratively across various components:

- PCB design and hardware integration for accurate signal acquisition
- App development for Android with real-time graphs and analytics
- Server-side APIs and cloud storage for historical data access
- GUI and control functionalities on Raspberry Pi
- Relay-based remote disconnection of supply

#### Key Learnings & Achievements

- Practical experience in embedded systems, IoT, and full-stack development
- Developed a complete system from hardware to cloud and mobile
- Built scalable architecture and an intuitive UI for energy monitoring

## 1. Source Code

### Application/

Flutter frontend for real-time monitoring and control. Contains Dart UI code (`lib/`), assets, platform-specific code, and Flutter config files.

### RPi/

Python scripts for data collection from ADE9000, local caching via SQLite, device control, syncing, and status tracking.

### Server/

FastAPI backend for authentication, data ingestion (InfluxDB), analytics, and WebSocket command handling. Includes API routes, config, and docs.

---

## Learning from Mistakes

### 1. UI Lag Due to Excessive Local Storage Data on Raspberry Pi

**Problem:**  
We encountered significant UI lag on the Raspberry Pi when the local storage accumulated large volumes of data. This led to delayed response times, particularly while switching between tabs, resulting in a poor user experience.

**Solution Implemented:**

- **Data Limitation:** We limited local data storage to only one day's worth of energy data to prevent database bloat and ensure smoother real-time operations.
- **Historical Data Handling:** For the "History" tab, we retained only a single representative energy data point from the previous day. This allowed for historical trend analysis with minimal storage overhead.
- **Improved UI Feedback:** A loading screen was introduced when switching tabs to:
  - Indicate the system is processing,
  - Discourage excessive button tapping,
  - Improve overall user satisfaction and interface intuitiveness.

**Outcome:**  
The optimizations resulted in a significantly more responsive and user-friendly interface with better resource management on the Raspberry Pi.

---

### 2. Power Backup System Failure

**Problem:**  
The power backup system failed to operate as intended during initial testing. Despite proper wiring and configuration, the battery did not charge, leading to a complete failure of backup functionality during power outages.

**Diagnosis and Root Cause:**  
After thorough inspection, we discovered that enclosing the circuitry between two tightly fitted acrylic sheets had introduced mechanical stress. This stress likely caused certain solder joints or connectors to either loosen or become overly compressed, ultimately disrupting the battery charging pathway.

**Solution Implemented:**

- **Mechanical Redesign:** We removed one of the acrylic sheets from the enclosure to relieve the internal stress and allow for natural ventilation and movement.
- **Post-Modification Testing:** After this adjustment, the charging system began functioning correctly, indicating that the issue was indeed related to physical strain affecting circuit integrity.

**Outcome:**  
Since this mechanical modification, the backup system has consistently charged without failure. This incident highlighted the critical importance of allowing tolerance for mechanical flexibility in compact hardware designs, especially when working with sensitive analog and power electronics.

---

## Future Scope

To further enhance the system’s functionality, usability, and sustainability, future contributors can explore the following improvements:

### 1. Sound Alerts for Power Failure

Implementing audio alerts during power failures can significantly improve user responsiveness and system awareness. Key aspects of this feature include:

- **Immediate Notifications:** Sound alerts ensure that users are informed of outages even when they are not actively monitoring the screen.
- **Severity-based Tones:** Different tones can indicate varying levels of urgency, such as battery low, power cut, or system reboot.
- **Remote Deployment Advantage:** Especially beneficial for systems installed in remote or unattended locations.

### 2. Integration with Solar Energy

Adding solar energy support can make the system more eco-friendly and independent of the grid. Potential features include:

- **Real-Time Monitoring:** Track solar power input and battery charge levels live.
- **Smart Source Switching:** Automatically switch between grid and solar based on availability and efficiency.
- **Analytics and Optimization:** Log and compare energy generation versus consumption to inform sustainable usage patterns.

**Impact:**  
These enhancements will improve system reliability, promote green energy adoption, and make the solution more adaptable to diverse deployment scenarios including smart homes, rural areas, and energy-conscious environments.

---
