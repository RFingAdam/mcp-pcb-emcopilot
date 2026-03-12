"""PCB design classifiers — net classification, interface detection, and design type analysis."""

from .net_classifier import NetClassifier, NetClassificationResult, NetClassification, DifferentialPair
from .interface_detector import InterfaceDetector, InterfaceDetectionResult, DetectedInterface
from .design_classifier import DesignClassifier, DesignClassificationResult

__all__ = [
    "NetClassifier",
    "NetClassificationResult",
    "NetClassification",
    "DifferentialPair",
    "InterfaceDetector",
    "InterfaceDetectionResult",
    "DetectedInterface",
    "DesignClassifier",
    "DesignClassificationResult",
]
