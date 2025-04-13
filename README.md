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

All source code files should be organized under the `/src` directory. If your project involves multiple microcontrollers or processors, create respective subfolders for each and provide clear descriptions about their purpose and functionality. Every subfolder should have a README.MD file which should explain the purpose of the code and all the commands used.

### Folder Structure

```plaintext
/Project-Root
├── /src # Source code folder (Add your source files here)
  ├── /microcontroller1 # Code for Microcontroller 1
    ├── file1.c # General source file
    ├── file2.c
  ├── /microcontroller2 # Code for Microcontroller 2 (if applicable)
    ├── file1.c # General source file
    ├── file2.c
```

### Guidelines for Organizing Code

1. **Microcontroller-specific code**:  
   If your project involves multiple microcontrollers, create a folder for each one under `/src`. Provide the following details:

   - **Folder Name**: Name it according to the microcontroller, e.g., `Microcontroller1`, `Microcontroller2`.
   - **Description**: A brief description of what each microcontroller’s source code does and its role in the project in a README.md file.

Example:

```plaintext
/src
  ├── /<microcontroller_name1>
    ├── <relevant_sources.c>  # All source codes
    ├── README.md  # Clear Documentation on the usage of board along with the commands and steps performed
  ├── /<microcontroller_name2>
    ├── <relevant_sources.c>  # All source codes
    ├── README.md  # Clear Documentation on the usage of board along with the commands and steps performed
......
......
```

2. **Running the Application**:

- If your project is based on microcontroller code, provide detailed instructions on how to upload and run the code on the microcontroller. This should include:
  - The microcontroller model (e.g. STM32, RPi Pico).
  - The Integrated Development Environment (IDE) used for programming (e.g., STM32CubeIDE, VSCode, Thonny IDE).
  - Steps for compiling and uploading the code to the device.
  - Example command to upload (if applicable).

3. **Code Comments**:

- Every source file should be properly commented to describe the purpose and function of each section of code.
- If you have made modifications to an existing code template or framework, comment clearly with your team name and indicate what changes were made.

---

## 2. PCB Design (If Applicable)

If your project involves designing a printed circuit board (PCB), provide the design files in the `/pcb` folder. If you have multiple PCBs, create separate subfolders for each design. Mention the tool used to design the PCB. (KiCAD, Altium, EAGLE). Include the picture of your final PCB Layout (With visibility of all the layers) under the `/pcb/<PCB_X>/pictures` folder with the layer names along with the picture of the Printed PCB which you've obtained.

### Folder Structure

```plaintext
/Project-Root
├── /pcb
  ├── /PCB1 # First PCB Design
    ├── design.kicad_pcb # PCB Design in KiCAD format
    ├── schematic.sch # KiCAD Schematic
  ├── /PCB2 # Second PCB Design (if applicable)
    ├── design.sch # PCB Schematic
    ├── design.kicad_pcb # PCB Design in KiCAD format
```

Include all relevant design files such as schematics, board layouts, custom schematic and footprints used and imported if applicable.

---

## 3. 3D Models / Laser Cuts

If your project includes 3D models or components that require laser cutting, place these files in the `/3d_models` directory. Create separate subfolders for different models and provide a description of the design process and tools used.

### Folder Structure

```plaintext
/Project-Root
├── /3d_models
  ├── /component1 # 3D Model for Component 1
    ├── model.stl # 3D model file
    ├── picture.png # Rendered image of the 3D model
  ├── /component2
    ├── model.obj
    ├── picture.jpg
```

Make sure to also include images (e.g., PNG, JPG) of the components that were laser cut or 3D printed.

---

## 4. Bill of Materials (BOM)

Provide a complete Bill of Materials (BOM) listing all the hardware components used in your project. This should include both parts obtained from the lab and parts ordered from external vendors or purchased locally.

### Folder Structure

```plaintext
/Project-Root
├── bom.xls # Excel sheet listing components
```

### BOM Details

The `bom.xls` file should include the following columns:

- **Component Name**
- **Type** (3D Model / Modules / IC / Consumables / Sensors & Actuators)
- **Quantity**
- **Part Number** (if applicable)
- **Supplier/Manufacturer/Vendor/Purchased Place**
- **Cost**
- **Description**

---

## 5. Reports and Presentations

Provide your project presentation and reports in either `.pptx`, `.ppt`, or `.pdf` format. This should include a brief overview of your project, objectives, design process, results, and conclusions. This should include all the milestone submission presentations.

### Folder Structure

```plaintext
/Project-Root
  ├── /reports
    ├── presentation.pptx # PowerPoint presentation file
    ├── milestone_reports.pdf # Milestone Reports in PDF file
```

## 6. Other Documents

Provide the wiring diagram of your components, attach pictures of your final project on how did you assemble the design. Place these files in the `/others` directory.
Any other important information regarding your project if it doesn't fit into any of the above categories, add it into this subfolder along with a proper README.md file to explain the same.

## Final Notes

- **Documentation**: Ensure that all your files are well-documented. This includes commenting your code, describing your designs, and providing detailed instructions in your README file.

By following these instructions, your project will be well-organized, easy to understand, and reproducible by others, including professors or staff members who might need to verify or recreate your project in the future.

Thank you, and best of luck with your project!

---
