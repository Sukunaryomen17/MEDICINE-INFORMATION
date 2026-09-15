import re

LAB_PATTERNS = [
    r"\bCBC\b", r"\bCRP\b", r"\bLFT\b", r"\bKFT\b", r"\bWIDAL\b",
    r"\bASSAY\b", r"\bTEST\b", r"\bLAB\b", r"\bPATHOLOGY\b",
    r"\bMRI\b", r"\bCT\s*SCAN\b", r"\bX-?RAY\b", r"\bULTRASOUND\b",
    r"\bUSG\b", r"\bECG\b", r"\bECHO\b", r"\bBIOPSY\b", r"\bCULTURE\b",
    r"\bURINE\s+R/E\b", r"\bBLOOD\s+SUGAR\b", r"\bSEROLOGY\b", r"\bLIPID\s+PROFILE\b"
]

SERVICE_PATTERNS = [
    r"\bROOM\b", r"\bBED\s+CHARGE\b", r"\bBED\b", r"\bNURSING\b",
    r"\bDOCTOR\b", r"\bCONSULTATION\b", r"\bVISIT\b", r"\bCHARGE\b",
    r"\bADMISSION\b", r"\bSURGERY\b", r"\bICU\b", r"\bOT\s+CHARGES\b",
    r"\bOPERATION\b", r"\bANESTHESIA\b", r"\bAMBULANCE\b", r"\bDIET\b",
    r"\bREGISTRATION\b", r"\bMAINTENANCE\b"
]

DEVICE_PATTERNS = [
    r"\bIV\s*FIX\b", r"\bSTOPCOCK\b", r"\bEXTENSION\s*LINE\b",
    r"\bCATHETER\b", r"\bCANNULA\b", r"\bURO\s*BAG\b", r"\bIV\s*SET\b",
    r"\bSAFESET\b", r"\bSYRINGE\b", r"\bNEEDLE\b", r"\bRAZOR\b",
    r"\bIMPLANT\b", r"\bSCREW\b", r"\bBONE\s+PLATE\b", r"\bFIXATOR\b",
    r"\bSURGICAL\s+MESH\b", r"\bSUTURE\b", r"\bGLOVES\b", r"\bBANDAGE\b",
    r"\bCOTTON\b", r"\bGAUZE\b", r"\bTHERMOMETER\b", r"\bMASK\b",
    r"\bINFUSION\s+SET\b", r"\bDRAIN\s*BAG\b"
]

_lab_regex = re.compile("|".join(LAB_PATTERNS), re.IGNORECASE)
_service_regex = re.compile("|".join(SERVICE_PATTERNS), re.IGNORECASE)
_device_regex = re.compile("|".join(DEVICE_PATTERNS), re.IGNORECASE)


def classify_item(item_name):
    if not item_name:
        return "UNKNOWN"

    name = str(item_name).strip()

    if _lab_regex.search(name):
        return "LAB_TEST"

    if _service_regex.search(name):
        return "HOSPITAL_SERVICE"

    if _device_regex.search(name):
        return "MEDICAL_DEVICE"

    return "MEDICINE"