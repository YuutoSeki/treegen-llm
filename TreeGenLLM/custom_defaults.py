CUSTOM_DEFAULTS = {
    "Socket_3": 4.0,  "Socket_4": 3.0,  "Socket_5": 2.0,  "Socket_6": 2.0, "Socket_7": 1.0,  "Socket_8": 1.0,
    "Socket_9": 12,   "Socket_10": 8,  "Socket_11": 5,   "Socket_12": 3, "Socket_13": 3,   "Socket_14": 3,
    "Socket_15": 1.0, "Socket_16": 1.0, "Socket_17": 1.0, "Socket_18": 1.0, "Socket_19": 1.0, "Socket_20": 1.0,
    "Socket_21": 2.5, "Socket_22": (0.0, 0.0, 0.0),
    "Socket_23": 1.0472, "Socket_24": 1.0472, "Socket_25": 1.0472, "Socket_26": 1.0472, "Socket_27": 1.0472,
    "Socket_28": 1.5708, "Socket_29": 0.2, "Socket_30": 0.99, "Socket_31": 0.3, "Socket_32": 0.9, "Socket_33": 0, "Socket_34": 5,
    "Socket_35": True,
    "Socket_36": 0.2, "Socket_37": 0.1, "Socket_38": 1.0, "Socket_39": 2.5, "Socket_40": 6, "Socket_41": 3,
    "Socket_42": True,
    "Socket_44": 200.0, "Socket_45": 0.5, "Socket_46": 4, "Socket_47": -0.349066, "Socket_48": 0.785398,"Socket_49": 1.0,
    "Socket_50": False,
    "Socket_51": 0.02, "Socket_52": 2, "Socket_53": 0.4, "Socket_54": 2.0, "Socket_55": 1.0
}

BOOL_CHILDREN = {
    "Socket_35": [f"Socket_{i}" for i in range(36, 42)],
    "Socket_42": [f"Socket_{i}" for i in range(43, 50)],
    "Socket_50": [f"Socket_{i}" for i in range(51, 56)],
}

SECTION_LABELS = {
    "Socket_3":  "Length",
    "Socket_9":  "Curve Resolution",
    "Socket_15": "Noise Offset",
    "Socket_21": "noise parameter",
    "Socket_23": "Branch Angle",
    "Socket_28": "Branch Parameters",
    "Socket_35": "Radius",
    "Socket_42": "Leaves",
    "Socket_50": "Curve Resample",
}
