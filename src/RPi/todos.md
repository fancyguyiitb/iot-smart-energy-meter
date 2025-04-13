### **1. Registers for Accumulated Energy (Wh, VARh, VAh)**

| Energy Type                | Phase A        | Phase B        | Phase C        | Total (All Phases) |
| -------------------------- | -------------- | -------------- | -------------- | ------------------ |
| **Active Energy (Wh)**     | `ADDR_AWATTHR` | `ADDR_BWATTHR` | `ADDR_CWATTHR` | `ADDR_TOTAWATTHR`  |
| **Reactive Energy (VARh)** | `ADDR_AVARHR`  | `ADDR_BVARHR`  | `ADDR_CVARHR`  | `ADDR_TOTVARHR`    |
| **Apparent Energy (VAh)**  | `ADDR_AVAHR`   | `ADDR_BVAHR`   | `ADDR_CVAHR`   | `ADDR_TOTVAHR`     |

---

### **2. Registers for Continuous Graph Data (Waveform Capture)**

| Waveform Data        | Phase A        | Phase B        | Phase C        |
| -------------------- | -------------- | -------------- | -------------- |
| **Voltage Waveform** | `ADDR_AVWFORM` | `ADDR_BVWFORM` | `ADDR_CVWFORM` |
| **Current Waveform** | `ADDR_AIWFORM` | `ADDR_BIWFORM` | `ADDR_CIWFORM` |

---

### **3. Registers for Real-Time Power (W, VAR, VA)**

| Power Type               | Phase A      | Phase B      | Phase C      | Total (All Phases) |
| ------------------------ | ------------ | ------------ | ------------ | ------------------ |
| **Active Power (W)**     | `ADDR_AWATT` | `ADDR_BWATT` | `ADDR_CWATT` | `ADDR_TOTWATT`     |
| **Reactive Power (VAR)** | `ADDR_AVAR`  | `ADDR_BVAR`  | `ADDR_CVAR`  | `ADDR_TOTVAR`      |
| **Apparent Power (VA)**  | `ADDR_AVA`   | `ADDR_BVA`   | `ADDR_CVA`   | `ADDR_TOTVA`       |

---

### **4. Registers for Power Factor (PF)**

| Power Factor     | Phase A    | Phase B    | Phase C    | Total (All Phases) |
| ---------------- | ---------- | ---------- | ---------- | ------------------ |
| **Power Factor** | `ADDR_APF` | `ADDR_BPF` | `ADDR_CPF` | `ADDR_TOTPF`       |

---

### **5. Registers for THD (Total Harmonic Distortion)**

| THD Type            | Phase A      | Phase B      | Phase C      |
| ------------------- | ------------ | ------------ | ------------ |
| **Voltage THD (%)** | `ADDR_AVTHD` | `ADDR_BVTHD` | `ADDR_CVTHD` |
| **Current THD (%)** | `ADDR_AITHD` | `ADDR_BITHD` | `ADDR_CITHD` |
