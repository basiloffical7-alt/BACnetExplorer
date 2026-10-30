"""
BACnet constants and enumerations (ASHRAE 135).

Only the standard values are listed; anything else is shown as
"proprietary-<n>" / "unknown-<n>" by the helper functions at the bottom.
"""

BACNET_PORT = 0xBAC0  # 47808

# --------------------------------------------------------------------------
# BVLC (Annex J)
# --------------------------------------------------------------------------
BVLC_TYPE = 0x81
BVLC_RESULT = 0x00
BVLC_WRITE_BDT = 0x01
BVLC_READ_BDT = 0x02
BVLC_READ_BDT_ACK = 0x03
BVLC_FORWARDED_NPDU = 0x04
BVLC_REGISTER_FOREIGN_DEVICE = 0x05
BVLC_READ_FDT = 0x06
BVLC_READ_FDT_ACK = 0x07
BVLC_DELETE_FDT_ENTRY = 0x08
BVLC_DISTRIBUTE_BROADCAST = 0x09
BVLC_ORIGINAL_UNICAST = 0x0A
BVLC_ORIGINAL_BROADCAST = 0x0B

BVLC_RESULT_CODES = {
    0x0000: "Successful completion",
    0x0010: "Write-BDT NAK",
    0x0020: "Read-BDT NAK",
    0x0030: "Register-Foreign-Device NAK",
    0x0040: "Read-FDT NAK",
    0x0050: "Delete-FDT-Entry NAK",
    0x0060: "Distribute-Broadcast-To-Network NAK",
}

# --------------------------------------------------------------------------
# APDU types
# --------------------------------------------------------------------------
PDU_CONFIRMED_REQUEST = 0x0
PDU_UNCONFIRMED_REQUEST = 0x1
PDU_SIMPLE_ACK = 0x2
PDU_COMPLEX_ACK = 0x3
PDU_SEGMENT_ACK = 0x4
PDU_ERROR = 0x5
PDU_REJECT = 0x6
PDU_ABORT = 0x7

# Confirmed services
SERVICE_ACKNOWLEDGE_ALARM = 0
SERVICE_CONFIRMED_COV_NOTIFICATION = 1
SERVICE_CONFIRMED_EVENT_NOTIFICATION = 2
SERVICE_SUBSCRIBE_COV = 5
SERVICE_ATOMIC_READ_FILE = 6
SERVICE_READ_PROPERTY = 12
SERVICE_READ_PROPERTY_MULTIPLE = 14
SERVICE_WRITE_PROPERTY = 15
SERVICE_WRITE_PROPERTY_MULTIPLE = 16
SERVICE_DEVICE_COMMUNICATION_CONTROL = 17
SERVICE_REINITIALIZE_DEVICE = 20
SERVICE_READ_RANGE = 26

# Unconfirmed services
SERVICE_I_AM = 0
SERVICE_I_HAVE = 1
SERVICE_UNCONFIRMED_COV_NOTIFICATION = 2
SERVICE_UNCONFIRMED_EVENT_NOTIFICATION = 3
SERVICE_TIME_SYNCHRONIZATION = 6
SERVICE_WHO_HAS = 7
SERVICE_WHO_IS = 8
SERVICE_UTC_TIME_SYNCHRONIZATION = 9

CONFIRMED_SERVICE_NAMES = {
    0: "acknowledgeAlarm", 1: "confirmedCOVNotification", 2: "confirmedEventNotification",
    3: "getAlarmSummary", 4: "getEnrollmentSummary", 5: "subscribeCOV", 6: "atomicReadFile",
    7: "atomicWriteFile", 8: "addListElement", 9: "removeListElement", 10: "createObject",
    11: "deleteObject", 12: "readProperty", 13: "readPropertyConditional",
    14: "readPropertyMultiple", 15: "writeProperty", 16: "writePropertyMultiple",
    17: "deviceCommunicationControl", 18: "confirmedPrivateTransfer", 19: "confirmedTextMessage",
    20: "reinitializeDevice", 21: "vtOpen", 22: "vtClose", 23: "vtData", 26: "readRange",
    27: "lifeSafetyOperation", 28: "subscribeCOVProperty", 29: "getEventInformation",
}

UNCONFIRMED_SERVICE_NAMES = {
    0: "i-Am", 1: "i-Have", 2: "unconfirmedCOVNotification", 3: "unconfirmedEventNotification",
    4: "unconfirmedPrivateTransfer", 5: "unconfirmedTextMessage", 6: "timeSynchronization",
    7: "who-Has", 8: "who-Is", 9: "utcTimeSynchronization", 10: "writeGroup",
}

# Bit positions of Protocol_Services_Supported
SERVICES_SUPPORTED_BITS = [
    "acknowledgeAlarm", "confirmedCOVNotification", "confirmedEventNotification",
    "getAlarmSummary", "getEnrollmentSummary", "subscribeCOV", "atomicReadFile",
    "atomicWriteFile", "addListElement", "removeListElement", "createObject", "deleteObject",
    "readProperty", "readPropertyConditional", "readPropertyMultiple", "writeProperty",
    "writePropertyMultiple", "deviceCommunicationControl", "confirmedPrivateTransfer",
    "confirmedTextMessage", "reinitializeDevice", "vtOpen", "vtClose", "vtData",
    "authenticate", "requestKey", "i-Am", "i-Have", "unconfirmedCOVNotification",
    "unconfirmedEventNotification", "unconfirmedPrivateTransfer", "unconfirmedTextMessage",
    "timeSynchronization", "who-Has", "who-Is", "readRange", "utcTimeSynchronization",
    "lifeSafetyOperation", "subscribeCOVProperty", "getEventInformation", "writeGroup",
    "subscribeCOVPropertyMultiple", "confirmedCOVNotificationMultiple",
    "unconfirmedCOVNotificationMultiple", "confirmedAuditNotification", "auditLogQuery",
    "unconfirmedAuditNotification", "who-Am-I", "you-Are",
]

# Max-APDU-length-accepted encoding (Clause 20.1.2.5)
MAX_APDU_CODES = {0: 50, 1: 128, 2: 206, 3: 480, 4: 1024, 5: 1476}
MAX_SEGMENTS_CODES = {0: None, 1: 2, 2: 4, 3: 8, 4: 16, 5: 32, 6: 64, 7: 65}

# --------------------------------------------------------------------------
# Object types
# --------------------------------------------------------------------------
OBJECT_TYPES = {
    0: "analog-input", 1: "analog-output", 2: "analog-value", 3: "binary-input",
    4: "binary-output", 5: "binary-value", 6: "calendar", 7: "command", 8: "device",
    9: "event-enrollment", 10: "file", 11: "group", 12: "loop", 13: "multi-state-input",
    14: "multi-state-output", 15: "notification-class", 16: "program", 17: "schedule",
    18: "averaging", 19: "multi-state-value", 20: "trend-log", 21: "life-safety-point",
    22: "life-safety-zone", 23: "accumulator", 24: "pulse-converter", 25: "event-log",
    26: "global-group", 27: "trend-log-multiple", 28: "load-control", 29: "structured-view",
    30: "access-door", 31: "timer", 32: "access-credential", 33: "access-point",
    34: "access-rights", 35: "access-user", 36: "access-zone", 37: "credential-data-input",
    38: "network-security", 39: "bitstring-value", 40: "characterstring-value",
    41: "date-pattern-value", 42: "date-value", 43: "datetime-pattern-value",
    44: "datetime-value", 45: "integer-value", 46: "large-analog-value",
    47: "octetstring-value", 48: "positive-integer-value", 49: "time-pattern-value",
    50: "time-value", 51: "notification-forwarder", 52: "alert-enrollment", 53: "channel",
    54: "lighting-output", 55: "binary-lighting-output", 56: "network-port",
    57: "elevator-group", 58: "escalator", 59: "lift", 60: "staging", 61: "audit-log",
    62: "audit-reporter", 63: "color", 64: "color-temperature",
}
OBJECT_TYPE_IDS = {v: k for k, v in OBJECT_TYPES.items()}

OBJ_ANALOG_INPUT = 0
OBJ_ANALOG_OUTPUT = 1
OBJ_ANALOG_VALUE = 2
OBJ_BINARY_INPUT = 3
OBJ_BINARY_OUTPUT = 4
OBJ_BINARY_VALUE = 5
OBJ_DEVICE = 8
OBJ_MULTI_STATE_INPUT = 13
OBJ_MULTI_STATE_OUTPUT = 14
OBJ_MULTI_STATE_VALUE = 19

ANALOG_TYPES = {0, 1, 2, 23, 24, 46}
BINARY_TYPES = {3, 4, 5, 55}
MULTISTATE_TYPES = {13, 14, 19}
COMMANDABLE_TYPES = {1, 4, 14, 2, 5, 19, 45, 46, 48, 40, 54, 55}

# Short prefixes used in the tree (similar to YABE / common BMS tools)
OBJECT_TYPE_SHORT = {
    0: "AI", 1: "AO", 2: "AV", 3: "BI", 4: "BO", 5: "BV", 6: "CAL", 7: "CMD", 8: "DEV",
    9: "EE", 10: "FILE", 11: "GRP", 12: "LOOP", 13: "MI", 14: "MO", 15: "NC", 16: "PRG",
    17: "SCH", 18: "AVG", 19: "MV", 20: "TL", 23: "ACC", 25: "EL", 27: "TLM", 29: "SV",
    31: "TMR", 40: "CSV", 45: "IV", 46: "LAV", 48: "PIV", 53: "CH", 54: "LO", 56: "NP",
}

# --------------------------------------------------------------------------
# Property identifiers
# --------------------------------------------------------------------------
PROPERTIES = {
    0: "acked-transitions", 1: "ack-required", 2: "action", 3: "action-text", 4: "active-text",
    5: "active-vt-sessions", 6: "alarm-value", 7: "alarm-values", 8: "all",
    9: "all-writes-successful", 10: "apdu-segment-timeout", 11: "apdu-timeout",
    12: "application-software-version", 13: "archive", 14: "bias", 15: "change-of-state-count",
    16: "change-of-state-time", 17: "notification-class", 19: "controlled-variable-reference",
    20: "controlled-variable-units", 21: "controlled-variable-value", 22: "cov-increment",
    23: "date-list", 24: "daylight-savings-status", 25: "deadband", 26: "derivative-constant",
    27: "derivative-constant-units", 28: "description", 29: "description-of-halt",
    30: "device-address-binding", 31: "device-type", 32: "effective-period",
    33: "elapsed-active-time", 34: "error-limit", 35: "event-enable", 36: "event-state",
    37: "event-type", 38: "exception-schedule", 39: "fault-values", 40: "feedback-value",
    41: "file-access-method", 42: "file-size", 43: "file-type", 44: "firmware-revision",
    45: "high-limit", 46: "inactive-text", 47: "in-process", 48: "instance-of",
    49: "integral-constant", 50: "integral-constant-units", 52: "limit-enable",
    53: "list-of-group-members", 54: "list-of-object-property-references", 56: "local-date",
    57: "local-time", 58: "location", 59: "low-limit", 60: "manipulated-variable-reference",
    61: "maximum-output", 62: "max-apdu-length-accepted", 63: "max-info-frames",
    64: "max-master", 65: "max-pres-value", 66: "minimum-off-time", 67: "minimum-on-time",
    68: "minimum-output", 69: "min-pres-value", 70: "model-name", 71: "modification-date",
    72: "notify-type", 73: "number-of-apdu-retries", 74: "number-of-states",
    75: "object-identifier", 76: "object-list", 77: "object-name",
    78: "object-property-reference", 79: "object-type", 80: "optional", 81: "out-of-service",
    82: "output-units", 83: "event-parameters", 84: "polarity", 85: "present-value",
    86: "priority", 87: "priority-array", 88: "priority-for-writing", 89: "process-identifier",
    90: "program-change", 91: "program-location", 92: "program-state",
    93: "proportional-constant", 94: "proportional-constant-units",
    96: "protocol-object-types-supported", 97: "protocol-services-supported",
    98: "protocol-version", 99: "read-only", 100: "reason-for-halt", 102: "recipient-list",
    103: "reliability", 104: "relinquish-default", 105: "required", 106: "resolution",
    107: "segmentation-supported", 108: "setpoint", 109: "setpoint-reference",
    110: "state-text", 111: "status-flags", 112: "system-status", 113: "time-delay",
    114: "time-of-active-time-reset", 115: "time-of-state-count-reset",
    116: "time-synchronization-recipients", 117: "units", 118: "update-interval",
    119: "utc-offset", 120: "vendor-identifier", 121: "vendor-name",
    122: "vt-classes-supported", 123: "weekly-schedule", 124: "attempted-samples",
    125: "average-value", 126: "buffer-size", 127: "client-cov-increment",
    128: "cov-resubscription-interval", 130: "event-time-stamps", 131: "log-buffer",
    132: "log-device-object-property", 133: "enable", 134: "log-interval",
    135: "maximum-value", 136: "minimum-value", 137: "notification-threshold",
    139: "protocol-revision", 140: "records-since-notification", 141: "record-count",
    142: "start-time", 143: "stop-time", 144: "stop-when-full", 145: "total-record-count",
    146: "valid-samples", 147: "window-interval", 148: "window-samples",
    149: "maximum-value-timestamp", 150: "minimum-value-timestamp", 151: "variance-value",
    152: "active-cov-subscriptions", 153: "backup-failure-timeout", 154: "configuration-files",
    155: "database-revision", 156: "direct-reading", 157: "last-restore-time",
    158: "maintenance-required", 159: "member-of", 160: "mode", 161: "operation-expected",
    162: "setting", 163: "silenced", 164: "tracking-value", 165: "zone-members",
    166: "life-safety-alarm-values", 167: "max-segments-accepted", 168: "profile-name",
    169: "auto-slave-discovery", 170: "manual-slave-address-binding",
    171: "slave-address-binding", 172: "slave-proxy-enable", 173: "last-notify-record",
    174: "schedule-default", 175: "accepted-modes", 176: "adjust-value", 177: "count",
    178: "count-before-change", 179: "count-change-time", 180: "cov-period",
    181: "input-reference", 182: "limit-monitoring-interval", 183: "logging-object",
    184: "logging-record", 185: "prescale", 186: "pulse-rate", 187: "scale",
    188: "scale-factor", 189: "update-time", 190: "value-before-change", 191: "value-set",
    192: "value-change-time", 193: "align-intervals", 195: "interval-offset",
    196: "last-restart-reason", 197: "logging-type", 202: "restart-notification-recipients",
    203: "time-of-device-restart", 204: "time-synchronization-interval", 205: "trigger",
    206: "utc-time-synchronization-recipients", 207: "node-subtype", 208: "node-type",
    209: "structured-object-list", 210: "subordinate-annotations", 211: "subordinate-list",
    212: "actual-shed-level", 213: "duty-window", 214: "expected-shed-level",
    215: "full-duty-baseline", 218: "requested-shed-level", 219: "shed-duration",
    220: "shed-level-descriptions", 221: "shed-levels", 222: "state-description",
    371: "property-list",
}
PROPERTY_IDS = {v: k for k, v in PROPERTIES.items()}

PROP_ALL = 8
PROP_DESCRIPTION = 28
PROP_EVENT_STATE = 36
PROP_MAX_APDU = 62
PROP_MODEL_NAME = 70
PROP_OBJECT_IDENTIFIER = 75
PROP_OBJECT_LIST = 76
PROP_OBJECT_NAME = 77
PROP_OBJECT_TYPE = 79
PROP_OUT_OF_SERVICE = 81
PROP_PRESENT_VALUE = 85
PROP_PRIORITY_ARRAY = 87
PROP_PROTOCOL_OBJECT_TYPES_SUPPORTED = 96
PROP_PROTOCOL_SERVICES_SUPPORTED = 97
PROP_RELIABILITY = 103
PROP_RELINQUISH_DEFAULT = 104
PROP_SEGMENTATION_SUPPORTED = 107
PROP_STATE_TEXT = 110
PROP_STATUS_FLAGS = 111
PROP_SYSTEM_STATUS = 112
PROP_UNITS = 117
PROP_VENDOR_ID = 120
PROP_VENDOR_NAME = 121
PROP_PROPERTY_LIST = 371

# --------------------------------------------------------------------------
# Enumerations used for pretty-printing
# --------------------------------------------------------------------------
ENGINEERING_UNITS = {
    0: "square-meters", 1: "square-feet", 2: "milliamperes", 3: "amperes", 4: "ohms",
    5: "volts", 6: "kilovolts", 7: "megavolts", 8: "volt-amperes", 9: "kilovolt-amperes",
    10: "megavolt-amperes", 11: "volt-amperes-reactive", 12: "kilovolt-amperes-reactive",
    13: "megavolt-amperes-reactive", 14: "degrees-phase", 15: "power-factor", 16: "joules",
    17: "kilojoules", 18: "watt-hours", 19: "kilowatt-hours", 20: "btus", 21: "therms",
    22: "ton-hours", 23: "joules-per-kilogram-dry-air", 24: "btus-per-pound-dry-air",
    25: "cycles-per-hour", 26: "cycles-per-minute", 27: "hertz",
    28: "grams-of-water-per-kilogram-dry-air", 29: "percent-relative-humidity",
    30: "millimeters", 31: "meters", 32: "inches", 33: "feet", 34: "watts-per-square-foot",
    35: "watts-per-square-meter", 36: "lumens", 37: "luxes", 38: "foot-candles",
    39: "kilograms", 40: "pounds-mass", 41: "tons", 42: "kilograms-per-second",
    43: "kilograms-per-minute", 44: "kilograms-per-hour", 45: "pounds-mass-per-minute",
    46: "pounds-mass-per-hour", 47: "watts", 48: "kilowatts", 49: "megawatts",
    50: "btus-per-hour", 51: "horsepower", 52: "tons-refrigeration", 53: "pascals",
    54: "kilopascals", 55: "bars", 56: "pounds-force-per-square-inch",
    57: "centimeters-of-water", 58: "inches-of-water", 59: "millimeters-of-mercury",
    60: "centimeters-of-mercury", 61: "inches-of-mercury", 62: "degrees-celsius",
    63: "degrees-kelvin", 64: "degrees-fahrenheit", 65: "degree-days-celsius",
    66: "degree-days-fahrenheit", 67: "years", 68: "months", 69: "weeks", 70: "days",
    71: "hours", 72: "minutes", 73: "seconds", 74: "meters-per-second",
    75: "kilometers-per-hour", 76: "feet-per-second", 77: "feet-per-minute",
    78: "miles-per-hour", 79: "cubic-feet", 80: "cubic-meters", 81: "imperial-gallons",
    82: "liters", 83: "us-gallons", 84: "cubic-feet-per-minute", 85: "cubic-meters-per-second",
    86: "imperial-gallons-per-minute", 87: "liters-per-second", 88: "liters-per-minute",
    89: "us-gallons-per-minute", 90: "degrees-angular", 91: "degrees-celsius-per-hour",
    92: "degrees-celsius-per-minute", 93: "degrees-fahrenheit-per-hour",
    94: "degrees-fahrenheit-per-minute", 95: "no-units", 96: "parts-per-million",
    97: "parts-per-billion", 98: "percent", 99: "percent-per-second", 100: "per-minute",
    101: "per-second", 102: "psi-per-degree-fahrenheit", 103: "radians",
    104: "revolutions-per-minute",
}

UNIT_SYMBOLS = {
    62: "°C", 63: "K", 64: "°F", 98: "%", 29: "%RH", 5: "V", 3: "A", 2: "mA", 47: "W",
    48: "kW", 19: "kWh", 53: "Pa", 54: "kPa", 55: "bar", 56: "psi", 84: "cfm", 87: "l/s",
    88: "l/min", 89: "gpm", 27: "Hz", 104: "rpm", 73: "s", 72: "min", 71: "h", 96: "ppm",
    74: "m/s", 58: "inH2O", 85: "m³/s",
}

EVENT_STATE = {0: "normal", 1: "fault", 2: "offnormal", 3: "high-limit", 4: "low-limit",
               5: "life-safety-alarm"}

RELIABILITY = {
    0: "no-fault-detected", 1: "no-sensor", 2: "over-range", 3: "under-range", 4: "open-loop",
    5: "shorted-loop", 6: "no-output", 7: "unreliable-other", 8: "process-error",
    9: "multi-state-fault", 10: "configuration-error", 12: "communication-failure",
    13: "member-fault", 14: "monitored-object-fault", 15: "tripped",
}

BINARY_PV = {0: "inactive", 1: "active"}
POLARITY = {0: "normal", 1: "reverse"}
SEGMENTATION = {0: "segmented-both", 1: "segmented-transmit", 2: "segmented-receive",
                3: "no-segmentation"}
DEVICE_STATUS = {0: "operational", 1: "operational-read-only", 2: "download-required",
                 3: "download-in-progress", 4: "non-operational", 5: "backup-in-progress"}
NOTIFY_TYPE = {0: "alarm", 1: "event", 2: "ack-notification"}
PROGRAM_STATE = {0: "idle", 1: "loading", 2: "running", 3: "waiting", 4: "halted",
                 5: "unloading"}
RESTART_REASON = {0: "unknown", 1: "coldstart", 2: "warmstart", 3: "detected-power-lost",
                  4: "detected-powered-off", 5: "hardware-watchdog", 6: "software-watchdog",
                  7: "suspended"}
FILE_ACCESS = {0: "record-access", 1: "stream-access"}
LOGGING_TYPE = {0: "polled", 1: "cov", 2: "triggered"}
NODE_TYPE = {0: "unknown", 1: "system", 2: "network", 3: "device", 4: "organizational",
             5: "area", 6: "equipment", 7: "point", 8: "collection", 9: "property",
             10: "functional", 11: "other"}

STATUS_FLAGS_BITS = ["in-alarm", "fault", "overridden", "out-of-service"]
EVENT_TRANSITION_BITS = ["to-offnormal", "to-fault", "to-normal"]
LIMIT_ENABLE_BITS = ["low-limit-enable", "high-limit-enable"]

ERROR_CLASS = {0: "device", 1: "object", 2: "property", 3: "resources", 4: "security",
               5: "services", 6: "vt", 7: "communication"}
ERROR_CODE = {
    0: "other", 2: "configuration-in-progress", 3: "device-busy", 9: "invalid-data-type",
    25: "operational-problem", 26: "password-failure", 27: "read-access-denied",
    29: "service-request-denied", 30: "timeout", 31: "unknown-object",
    32: "unknown-property", 37: "value-out-of-range", 40: "write-access-denied",
    42: "invalid-array-index", 44: "not-cov-property",
    45: "optional-functionality-not-supported", 50: "property-is-not-an-array",
}
REJECT_REASON = {
    0: "other", 1: "buffer-overflow", 2: "inconsistent-parameters",
    3: "invalid-parameter-data-type", 4: "invalid-tag", 5: "missing-required-parameter",
    6: "parameter-out-of-range", 7: "too-many-arguments", 8: "undefined-enumeration",
    9: "unrecognized-service",
}
ABORT_REASON = {
    0: "other", 1: "buffer-overflow", 2: "invalid-apdu-in-this-state",
    3: "preempted-by-higher-priority-task", 4: "segmentation-not-supported",
    5: "security-error", 6: "insufficient-security", 7: "window-size-out-of-range",
    8: "application-exceeded-reply-time", 9: "out-of-resources", 10: "tsm-timeout",
    11: "apdu-too-long",
}

# Names of the 16 command priorities (ASHRAE 135 clause 19.2.2)
PRIORITY_NAMES = [
    "Manual Life Safety", "Automatic Life Safety", "Unspecified Level 3", "Unspecified Level 4",
    "Critical Equipment Control", "Minimum On Off", "Unspecified Level 7", "Manual Operator",
    "Unspecified Level 9", "Unspecified Level 10", "Unspecified Level 11", "Unspecified Level 12",
    "Unspecified Level 13", "Unspecified Level 14", "Unspecified Level 15", "Lowest And Default",
]

DAYS_OF_WEEK = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}

# A reasonable default property set per object family, used when a device
# supports neither ReadPropertyMultiple(ALL) nor Property_List.
COMMON_PROPS = [75, 77, 79, 28, 85, 111, 36, 103, 81]
DEFAULT_PROPS = {
    "analog": COMMON_PROPS + [117, 22, 65, 69, 106, 87, 104, 45, 59, 25],
    "binary": COMMON_PROPS + [84, 4, 46, 87, 104, 15, 16, 33, 66, 67],
    "multistate": COMMON_PROPS + [74, 110, 87, 104],
    "device": [75, 77, 79, 112, 121, 120, 70, 44, 12, 58, 28, 98, 139, 97, 96, 76, 62, 107,
               167, 11, 73, 155, 30, 56, 57, 119, 24],
    "other": COMMON_PROPS,
}


# --------------------------------------------------------------------------
# Name helpers
# --------------------------------------------------------------------------
def object_type_name(t: int) -> str:
    if t in OBJECT_TYPES:
        return OBJECT_TYPES[t]
    return f"proprietary-{t}" if t >= 128 else f"unknown-{t}"


def property_name(p: int) -> str:
    if p in PROPERTIES:
        return PROPERTIES[p]
    return f"proprietary-{p}" if p >= 512 else f"property-{p}"


def lookup_object_type(text: str) -> int:
    text = text.strip().lower().replace("_", "-").replace(" ", "-")
    if text.isdigit():
        return int(text)
    if text in OBJECT_TYPE_IDS:
        return OBJECT_TYPE_IDS[text]
    for k, v in OBJECT_TYPE_SHORT.items():
        if v.lower() == text:
            return k
    raise ValueError(f"Unknown object type: {text}")


def lookup_property(text: str) -> int:
    text = text.strip().lower().replace("_", "-").replace(" ", "-")
    if text.isdigit():
        return int(text)
    if text in PROPERTY_IDS:
        return PROPERTY_IDS[text]
    raise ValueError(f"Unknown property: {text}")


def object_family(obj_type: int) -> str:
    if obj_type in ANALOG_TYPES:
        return "analog"
    if obj_type in BINARY_TYPES:
        return "binary"
    if obj_type in MULTISTATE_TYPES:
        return "multistate"
    if obj_type == OBJ_DEVICE:
        return "device"
    return "other"


def enum_table_for(obj_type: int, prop_id: int):
    """Return the enumeration dictionary used to pretty-print a property, or None."""
    if prop_id == 36:
        return EVENT_STATE
    if prop_id == 103:
        return RELIABILITY
    if prop_id in (117, 82, 20, 27, 50, 94):
        return ENGINEERING_UNITS
    if prop_id == 107:
        return SEGMENTATION
    if prop_id == 112:
        return DEVICE_STATUS
    if prop_id == 84:
        return POLARITY
    if prop_id == 72:
        return NOTIFY_TYPE
    if prop_id == 79:
        return OBJECT_TYPES
    if prop_id == 92:
        return PROGRAM_STATE
    if prop_id == 196:
        return RESTART_REASON
    if prop_id == 41:
        return FILE_ACCESS
    if prop_id == 197:
        return LOGGING_TYPE
    if prop_id == 208:
        return NODE_TYPE
    if obj_type in BINARY_TYPES and prop_id in (85, 104, 6, 40, 190, 191):
        return BINARY_PV
    return None


def bitstring_names_for(prop_id: int):
    if prop_id == 111:
        return STATUS_FLAGS_BITS
    if prop_id in (0, 35, 1):
        return EVENT_TRANSITION_BITS
    if prop_id == 52:
        return LIMIT_ENABLE_BITS
    if prop_id == 97:
        return SERVICES_SUPPORTED_BITS
    if prop_id == 96:
        return [OBJECT_TYPES.get(i, f"type-{i}") for i in range(max(OBJECT_TYPES) + 1)]
    return None
