from __future__ import annotations

import cv2
import numpy as np

from app.models import ImageMetrics


class ImageFeatureExtractor:
    @staticmethod
    def load_image_bytes(file_bytes: bytes) -> np.ndarray:
        np_arr = np.frombuffer(file_bytes, np.uint8)
        image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Unable to decode image. Please upload a JPG or PNG file.")
        return image

    @staticmethod
    def extract_metrics(image: np.ndarray) -> ImageMetrics:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        glare_ratio = float((gray > 240).sum() / gray.size)
        saturation = float(hsv[:, :, 1].mean())
        contrast = float(gray.std())

        edges = cv2.Canny(gray, 80, 180)
        edge_density = float((edges > 0).sum() / edges.size)

        h, w = image.shape[:2]
        aspect_ratio = float(w / h) if h else 0.0
        face_count = ImageFeatureExtractor._detect_faces(gray)

        return ImageMetrics(
            blur_score=round(blur_score, 3),
            brightness=round(brightness, 3),
            glare_ratio=round(glare_ratio, 5),
            saturation=round(saturation, 3),
            contrast=round(contrast, 3),
            edge_density=round(edge_density, 5),
            width=int(w),
            height=int(h),
            aspect_ratio=round(aspect_ratio, 3),
            face_count=int(face_count),
        )

    @staticmethod
    def _detect_faces(gray: np.ndarray) -> int:
        try:
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            detector = cv2.CascadeClassifier(cascade_path)
            faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
            return 0 if faces is None else len(faces)
        except Exception:
            return 0
