# /*
#   ADE9000API.h - Library for ADE9000/ADE9078 - Energy and PQ monitoring AFE
#   Author:nchandra
#   Date: 3-16-2017
# */
# #ifndef ADE9000API_h
# #define ADE9000API_h
from dataclasses import dataclass
from typing import List

from ADE9000RegMap import *

"""
/****************************************************************************************************************
 Includes
***************************************************************************************************************/

#include "Arduino.h"
#include  "ADE9000RegMap.h"

/****************************************************************************************************************
 Definitions
****************************************************************************************************************/
/*Configuration registers*/
"""
ADE9000_PGA_GAIN = 0x0000  # PGA@0x0000. Gain of all channels=1*/
ADE9000_CONFIG0 = 0x00000000  # Integrator disabled*/
ADE9000_CONFIG1 = 0x0002  # CFF/ZX pin outputs Zero crossing */
ADE9000_CONFIG2 = 0x0C00  # Default High pass corner frequency of 1.25Hz*/
ADE9000_CONFIG3 = 0x0000  # Peak and overcurrent detection disabled*/
ADE9000_ACCMODE = (
    0x0000  # 60Hz operation, 3P4W Wye configuration, signed accumulation*/
)
# Clear bit 8 i.e. ACCMODE=0x00xx for 50Hz operation*/
# ACCMODE=0x0x9x for 3Wire delta when phase B is used as reference*/
ADE9000_TEMP_CFG = 0x000C  # Temperature sensor enabled*/
ADE9000_ZX_LP_SEL = 0x001E  # Line period and zero crossing obtained from combined signals VA,VB and VC*/
ADE9000_MASK0 = 0x00000001  # Enable EGYRDY interrupt*/
ADE9000_MASK1 = 0x00000000  # MASK1 interrupts disabled*/
ADE9000_EVENT_MASK = 0x00000000  # Events disabled */
ADE9000_VLEVEL = 0x0022EA28  # Assuming Vnom=1/2 of full scale.
# Refer Technical reference manual for detailed calculations.*/
ADE9000_DICOEFF = 0x00000000  # Set DICOEFF= 0xFFFFE000 when integrator is enabled*/

# Constant Definitions***/
ADE90xx_FDSP = 8000  # ADE9000 FDSP: 8000sps, ADE9078 FDSP: 4000sps*/
ADE9000_RUN_ON = 0x0001  # DSP ON*/
# Energy Accumulation Settings*/
ADE9000_EP_CFG = 0x0011  # Enable energy accumulation, accumulate samples at 8ksps*/
# latch energy accumulation after EGYRDY*/
# If accumulation is changed to half line cycle mode, change EGY_TIME*/
ADE9000_EGY_TIME = 0x1F3F  # Accumulate 8000 samples*/

# Waveform buffer Settings*/
ADE9000_WFB_CFG = 0x1000  # Neutral current samples enabled, Resampled data enabled*/
# Burst all channels*/
WFB_ELEMENT_ARRAY_SIZE = (
    512  # size of buffer to read. 512 Max.Each element IA,VA...IN has max 512 points
)
# [Size of waveform buffer/number of sample sets = 2048/4 = 512]*/
# (Refer ADE9000 technical reference manual for more details)*/

# /*Full scale Codes referred from Datasheet.Respective digital codes are produced when ADC inputs are at full scale. Donot Change. */
ADE9000_RMS_FULL_SCALE_CODES = 52702092
ADE9000_WATT_FULL_SCALE_CODES = 20694066
ADE9000_RESAMPLED_FULL_SCALE_CODES = 18196
ADE9000_PCF_FULL_SCALE_CODES = 74532013

# /*Size of array reading calibration constants from EEPROM*/
CALIBRATION_CONSTANTS_ARRAY_SIZE = 13
ADE9000_EEPROM_ADDRESS = (
    0x54  # //1010xxxy xxx---> 100(A2,A1,A0 defined by hardware). y (1: Read, 0:Write)
)
EEPROM_WRITTEN = 0x01

# /*Address of registers stored in EEPROM.Calibration data is 4 bytes*/
ADDR_CHECKSUM_EEPROM = 0x0800  # // Simple checksum to verify data transmission errors. Add all the registers upto CPGAIN. The lower 32 bits should match data starting @ADDR_CHECKSUM_EEPROM
ADDR_EEPROM_WRITTEN_BYTE = (
    0x0804  # 1--> EEPROM Written, 0--> Not written. One byte only
)

ADDR_AIGAIN_EEPROM = 0x0004
ADDR_BIGAIN_EEPROM = 0x000C
ADDR_CIGAIN_EEPROM = 0x0010
ADDR_NIGAIN_EEPROM = 0x0014
ADDR_AVGAIN_EEPROM = 0x0018
ADDR_BVGAIN_EEPROM = 0x001C
ADDR_CVGAIN_EEPROM = 0x0020
ADDR_APHCAL0_EEPROM = 0x0024
ADDR_BPHCAL0_EEPROM = 0x0028
ADDR_CPHCAL0_EEPROM = 0x002C
ADDR_APGAIN_EEPROM = 0x0030
ADDR_BPGAIN_EEPROM = 0x0034
ADDR_CPGAIN_EEPROM = 0x0038

"""
/****************************************************************************************************************
 EEPROM Global Variables
****************************************************************************************************************/
"""

# extern uint32_t calibrationDatafromEEPROM[CALIBRATION_CONSTANTS_ARRAY_SIZE];
# extern uint32_t ADE9000_CalibrationRegAddress[CALIBRATION_CONSTANTS_ARRAY_SIZE];
# extern uint32_t ADE9000_Eeprom_CalibrationRegAddress[CALIBRATION_CONSTANTS_ARRAY_SIZE];

# Global lists to store calibration data
calibrationDatafromEEPROM: List[int] = [0] * CALIBRATION_CONSTANTS_ARRAY_SIZE
ADE9000_CalibrationRegAddress: List[int] = [0] * CALIBRATION_CONSTANTS_ARRAY_SIZE
ADE9000_Eeprom_CalibrationRegAddress: List[int] = [0] * CALIBRATION_CONSTANTS_ARRAY_SIZE


"""
/****************************************************************************************************************
 Structures and Global Variables
****************************************************************************************************************/
"""


@dataclass
class ResampledWfbData:
    VA_Resampled: List[int] = None
    IA_Resampled: List[int] = None
    VB_Resampled: List[int] = None
    IB_Resampled: List[int] = None
    VC_Resampled: List[int] = None
    IC_Resampled: List[int] = None
    IN_Resampled: List[int] = None

    def __post_init__(self):
        # Initialize arrays with zeros
        self.VA_Resampled = [0] * WFB_ELEMENT_ARRAY_SIZE
        self.IA_Resampled = [0] * WFB_ELEMENT_ARRAY_SIZE
        self.VB_Resampled = [0] * WFB_ELEMENT_ARRAY_SIZE
        self.IB_Resampled = [0] * WFB_ELEMENT_ARRAY_SIZE
        self.VC_Resampled = [0] * WFB_ELEMENT_ARRAY_SIZE
        self.IC_Resampled = [0] * WFB_ELEMENT_ARRAY_SIZE
        self.IN_Resampled = [0] * WFB_ELEMENT_ARRAY_SIZE


@dataclass
class ActivePowerRegs:
    ActivePowerReg_A: int
    ActivePowerReg_B: int
    ActivePowerReg_C: int


@dataclass
class ReactivePowerRegs:
    ReactivePowerReg_A: int
    ReactivePowerReg_B: int
    ReactivePowerReg_C: int


@dataclass
class ApparentPowerRegs:
    ApparentPowerReg_A: int
    ApparentPowerReg_B: int
    ApparentPowerReg_C: int


@dataclass
class VoltageRMSRegs:
    VoltageRMSReg_A: int
    VoltageRMSReg_B: int
    VoltageRMSReg_C: int


@dataclass
class CurrentRMSRegs:
    CurrentRMSReg_A: int
    CurrentRMSReg_B: int
    CurrentRMSReg_C: int
    CurrentRMSReg_N: int


@dataclass
class FundActivePowerRegs:
    FundActivePowerReg_A: int
    FundActivePowerReg_B: int
    FundActivePowerReg_C: int


@dataclass
class FundReactivePowerRegs:
    FundReactivePowerReg_A: int
    FundReactivePowerReg_B: int
    FundReactivePowerReg_C: int


@dataclass
class FundApparentPowerRegs:
    FundApparentPowerReg_A: int
    FundApparentPowerReg_B: int
    FundApparentPowerReg_C: int


@dataclass
class FundVoltageRMSRegs:
    FundVoltageRMSReg_A: int
    FundVoltageRMSReg_B: int
    FundVoltageRMSReg_C: int


@dataclass
class FundCurrentRMSRegs:
    FundCurrentRMSReg_A: int
    FundCurrentRMSReg_B: int
    FundCurrentRMSReg_C: int


@dataclass
class HalfVoltageRMSRegs:
    HalfVoltageRMSReg_A: int
    HalfVoltageRMSReg_B: int
    HalfVoltageRMSReg_C: int


@dataclass
class HalfCurrentRMSRegs:
    HalfCurrentRMSReg_A: int
    HalfCurrentRMSReg_B: int
    HalfCurrentRMSReg_C: int
    HalfCurrentRMSReg_N: int


@dataclass
class Ten12VoltageRMSRegs:
    Ten12VoltageRMSReg_A: int
    Ten12VoltageRMSReg_B: int
    Ten12VoltageRMSReg_C: int


@dataclass
class Ten12CurrentRMSRegs:
    Ten12CurrentRMSReg_A: int
    Ten12CurrentRMSReg_B: int
    Ten12CurrentRMSReg_C: int
    Ten12CurrentRMSReg_N: int


@dataclass
class VoltageTHDRegs:
    VoltageTHDReg_A: int
    VoltageTHDReg_B: int
    VoltageTHDReg_C: int
    VoltageTHDValue_A: float
    VoltageTHDValue_B: float
    VoltageTHDValue_C: float


@dataclass
class CurrentTHDRegs:
    CurrentTHDReg_A: int
    CurrentTHDReg_B: int
    CurrentTHDReg_C: int
    CurrentTHDValue_A: float
    CurrentTHDValue_B: float
    CurrentTHDValue_C: float


@dataclass
class PowerFactorRegs:
    PowerFactorReg_A: int
    PowerFactorReg_B: int
    PowerFactorReg_C: int
    PowerFactorValue_A: float
    PowerFactorValue_B: float
    PowerFactorValue_C: float


@dataclass
class PeriodRegs:
    PeriodReg_A: int
    PeriodReg_B: int
    PeriodReg_C: int
    FrequencyValue_A: float
    FrequencyValue_B: float
    FrequencyValue_C: float


@dataclass
class AngleRegs:
    AngleReg_VA_VB: int
    AngleReg_VB_VC: int
    AngleReg_VA_VC: int
    AngleReg_VA_IA: int
    AngleReg_VB_IB: int
    AngleReg_VC_IC: int
    AngleReg_IA_IB: int
    AngleReg_IB_IC: int
    AngleReg_IA_IC: int
    AngleValue_VA_VB: float
    AngleValue_VB_VC: float
    AngleValue_VA_VC: float
    AngleValue_VA_IA: float
    AngleValue_VB_IB: float
    AngleValue_VC_IC: float
    AngleValue_IA_IB: float
    AngleValue_IB_IC: float
    AngleValue_IA_IC: float


@dataclass
class TemperatureRegnValue:
    Temperature_Reg: int
    Temperature: float


# class ADE9000:
#     def __init__(self):
#         self._chipSelect_Pin = None  # Private attribute for chip select pin

#     def setup_ADE9000(self):
#         pass  # Implementation of setup logic

#     # SPI Functions
#     def spi_init(self, spi_speed: int, chip_select_pin: int):
#         self._chipSelect_Pin = chip_select_pin
#         pass  # Implement SPI initialization logic

#     def spi_write_16(self, address: int, data: int):
#         pass  # Implement 16-bit SPI write

#     def spi_write_32(self, address: int, data: int):
#         pass  # Implement 32-bit SPI write

#     def spi_read_16(self, address: int) -> int:
#         pass  # Implement 16-bit SPI read
#         return 0

#     def spi_read_32(self, address: int) -> int:
#         pass  # Implement 32-bit SPI read
#         return 0

#     def spi_burst_read_resampled_wfb(
#         self, address: int, read_element_length: int, resampled_data
#     ):
#         pass  # Implement SPI burst read for resampled waveform data

#     # ADE9000 Calculated Parameter Read Functions
#     def read_active_power_regs(self, data):
#         pass

#     def read_reactive_power_regs(self, data):
#         pass

#     def read_apparent_power_regs(self, data):
#         pass

#     def read_voltage_rms_regs(self, data):
#         pass

#     def read_current_rms_regs(self, data):
#         pass

#     def read_fund_active_power_regs(self, data):
#         pass

#     def read_fund_reactive_power_regs(self, data):
#         pass

#     def read_fund_apparent_power_regs(self, data):
#         pass

#     def read_fund_voltage_rms_regs(self, data):
#         pass

#     def read_fund_current_rms_regs(self, data):
#         pass

#     def read_half_voltage_rms_regs(self, data):
#         pass

#     def read_half_current_rms_regs(self, data):
#         pass

#     def read_ten12_voltage_rms_regs(self, data):
#         pass

#     def read_ten12_current_rms_regs(self, data):
#         pass

#     def read_voltage_thd_regs_values(self, data):
#         pass

#     def read_current_thd_regs_values(self, data):
#         pass

#     def read_power_factor_regs_values(self, data):
#         pass

#     def read_period_regs_values(self, data):
#         pass

#     def read_angle_regs_values(self, data):
#         pass

#     def read_temp_reg_value(self, data):
#         pass

#     # EEPROM Functions
#     def write_byte_to_eeprom(self, data_address: int, data: int):
#         pass

#     def read_byte_from_eeprom(self, data_address: int) -> int:
#         pass
#         return 0

#     def write_word_to_eeprom(self, address: int, data: int):
#         pass

#     def read_word_from_eeprom(self, address: int) -> int:
#         pass
#         return 0
