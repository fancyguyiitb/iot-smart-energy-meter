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

We developed an IoT-based 3-phase smart energy meter that allows users to monitor power parameters, analyze power quality, and remotely control the power supply. The system supports real-time data logging, mobile access, and predictive maintenance insights through harmonics analysis.

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
