# IoT Enabled 3-Phase Energy Meter - PCB Design

This folder contains the KiCAD schematic and PCB design files for the **IoT Enabled 3-Phase Energy Meter** project. The energy meter is designed to measure and monitor three-phase electrical parameters and transmit data to a Raspberry Pi for further processing and control.

## Folder Structure

```
.
├── PCB.kicad_sch
├── Current_Sense_Block.kicad_sch
├── Voltage_Sense_Block.kicad_sch
├── Relay_Drive.kicad_sch
└── energy_meter_pcb.kicad_pcb
```

## Overview

The PCB integrates multiple blocks to accurately measure electrical parameters using the ADE9000 IC, isolate the high-voltage and low-voltage domains, and interface with a Raspberry Pi for data communication and relay control.

---

## Block Description

### Voltage and Current Sensing Blocks

- **Input:**
  - 3 Phase Voltages (Line to Neutral) and Neutral connected to the **Voltage Sensing Block**
  - Current Transformers (CTs) connected to the **Current Sensing Block**
- **Function:**  
  These blocks scale down voltage and current to ranges compatible with the **ADE9000** IC.

### ADE9000 Measurement IC

- Measures:
  - Voltage, Current, Power, Energy, THD, etc.
- Communicates with Raspberry Pi using **SPI interface**
- Receives scaled-down signals from the sensing blocks

### Isolation Block

- **ICs Used:**
  - `ADUM6404` – Power and signal isolation
  - `ADUM4151` – SPI digital isolation
- Provides isolation between the high-voltage side (connected to mains) and low-voltage control logic (Raspberry Pi)

### Relay Control Block

- Controls 3 individual relays for 3-phase control
- Each relay is driven using a **TIP41C** NPN transistor
- Controlled through Raspberry Pi GPIO pins

### Power Supply

- **5V** supplied from RPI\*\*
- Appropriate headers and connectors included on the PCB for all connections

---

## Status

- PCB designed and tested
- All blocks working as intended

---

## Tools Used

- **KiCAD** for schematic and PCB design
