"""PCB design classifiers — net classification, interface detection, and design type analysis."""

from .design_classifier import DesignClassificationResult, DesignClassifier
from .interface_detector import DetectedInterface, InterfaceDetectionResult, InterfaceDetector
from .net_classifier import DifferentialPair, NetClassification, NetClassificationResult, NetClassifier

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
