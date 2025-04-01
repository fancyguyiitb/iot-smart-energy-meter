# Project Documentation and Submission Guide

This document serves as a comprehensive guide for submitting your project. By following the instructions below, you will ensure that the project is properly organized, documented, and easy for others (such as professors or staff members) to understand and replicate.

Your entire project is graded based on this submission and so please adhere to this properly. DEADLINE is on 12th April, 2025.

## Project Overview

### Project Name: [Insert Project Name Here]
### Team Members:
- [Name 1]
- [Name 2]
- [Name 3]
- [Name 4]
- [Name 5] (if applicable)

Provide a description about the project and what you've achieved in this.

Make sure to add all the below properly as given and if it's applicable.

## 1. Source Code

All source code files should be organized under the `/src` directory. If your project involves multiple microcontrollers or processors, create respective subfolders for each and provide clear descriptions about their purpose and functionality.

### Folder Structure:
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

### Guidelines for Organizing Code:
1. **Microcontroller-specific code**:  
   If your project involves multiple microcontrollers, create a folder for each one under `/src`. Provide the following details:
   
   - **Folder Name**: Name it according to the microcontroller, e.g., `Microcontroller1`, `Microcontroller2`.
   - **Description**: A brief description of what each microcontroller’s source code does and its role in the project.

Example:
```plaintext
/src 
  ├── /<microcontroller_name1> 
    ├── <relevant_sources.c>  # All source codes
  ├── /<microcontroller_name2> 
    ├── <relevant_sources.c>  # All source codes
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

If your project involves designing a printed circuit board (PCB), provide the design files in the `/pcb` folder. If you have multiple PCBs, create separate subfolders for each design. Mention the tool used to design the PCB. (KiCAD, Altium, EAGLE)

### Folder Structure:
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

### Folder Structure:
```plaintext
/Project-Root 
├── /3d_models 
  ├── /component1 # 3D Model for Component 1 
    ├── model.stl # 3D model file 
    ├── picture.png # Rendered image of the 3D model #
  ├── /component2 
    ├── model.obj 
    ├── picture.jpg
```
Make sure to also include images (e.g., PNG, JPG) of the components that were laser cut or 3D printed.

---

## 4. Bill of Materials (BOM)

Provide a complete Bill of Materials (BOM) listing all the hardware components used in your project. This should include both parts obtained from the lab and parts ordered from external vendors or purchased locally.

### Folder Structure:
```plaintext
/Project-Root 
├── bom.xls # Excel sheet listing components
```

### BOM Details:
The `bom.xls` file should include the following columns:
- **Component Name**
- **Quantity**
- **Part Number** (if applicable)
- **Supplier/Manufacturer/Vendor**
- **Cost** (optional)
- **Description**

---

## 5. Presentation

Provide your project presentation in either `.pptx`, `.ppt`, or `.pdf` format. This should include a brief overview of your project, objectives, design process, results, and conclusions.

### Folder Structure:
```plaintext
/Project-Root 
├── presentation.pptx # PowerPoint presentation file
```

---

## Final Notes:
- **Documentation**: Ensure that all your files are well-documented. This includes commenting your code, describing your designs, and providing detailed instructions in your README file.

By following these instructions, your project will be well-organized, easy to understand, and reproducible by others, including professors or staff members who might need to verify or recreate your project.

Thank you, and best of luck with your project!

---
