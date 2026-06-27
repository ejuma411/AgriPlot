"""
utils/firebase.py
-----------------
Firebase Admin SDK initialisation for AgriPlot.

Usage anywhere in Django:

    from utils.firebase import get_firestore_client

    db = get_firestore_client()

    # Write a document
    db.collection("plots").document(str(plot_id)).set({
        "title": plot.title,
        "county": plot.county,
        "market_status": plot.market_status,
        "updated_at": firestore.SERVER_TIMESTAMP,
    })

    # Read a document
    doc = db.collection("plots").document(str(plot_id)).get()
    if doc.exists:
        data = doc.to_dict()

    # Query a collection
    docs = db.collection("plots").where("market_status", "==", "available").stream()
    for doc in docs:
        print(doc.id, doc.to_dict())
"""

import logging
import os

import firebase_admin
from firebase_admin import credentials, firestore
from django.conf import settings

logger = logging.getLogger(__name__)

_firebase_app = None


def _initialise_firebase() -> firebase_admin.App:
    """
    Initialise the Firebase Admin SDK exactly once per process.

    Reads configuration from Django settings:
        FIREBASE_CREDENTIALS_PATH  – absolute path to the service account JSON
        FIREBASE_PROJECT_ID        – Firebase project ID (e.g. "agriplot-connect")

    Falls back to Application Default Credentials (ADC) when no credentials
    file path is configured, which is useful for Google Cloud environments.
    """
    global _firebase_app

    if _firebase_app is not None:
        return _firebase_app

    # Check if an app is already initialised (e.g. in tests or reloads)
    try:
        _firebase_app = firebase_admin.get_app()
        return _firebase_app
    except ValueError:
        pass  # No app yet — continue with initialisation

    project_id: str = getattr(settings, "FIREBASE_PROJECT_ID", "") or os.environ.get(
        "FIREBASE_PROJECT_ID", ""
    )
    credentials_path: str = getattr(
        settings, "FIREBASE_CREDENTIALS_PATH", ""
    ) or os.environ.get("FIREBASE_CREDENTIALS_PATH", "")

    options: dict = {}
    if project_id:
        options["projectId"] = project_id

    if credentials_path and os.path.isfile(credentials_path):
        cred = credentials.Certificate(credentials_path)
        logger.info("Firebase: initialising with service account from %s", credentials_path)
    else:
        if credentials_path:
            logger.warning(
                "Firebase: credentials file not found at '%s'. "
                "Falling back to Application Default Credentials.",
                credentials_path,
            )
        else:
            logger.info("Firebase: no credentials path set — using Application Default Credentials.")
        cred = credentials.ApplicationDefault()

    _firebase_app = firebase_admin.initialize_app(cred, options)
    logger.info("Firebase: app initialised (project=%s)", project_id or "unset")
    return _firebase_app


def get_firestore_client() -> firestore.Client:
    """
    Return an initialised Firestore client.

    The Firebase app is initialised on first call and reused for all
    subsequent calls within the same process.

    Example::

        from utils.firebase import get_firestore_client
        db = get_firestore_client()
        db.collection("notifications").add({"message": "Hello"})
    """
    _initialise_firebase()
    return firestore.client()


def get_firebase_app() -> firebase_admin.App:
    """Return the initialised Firebase App instance (for Auth, FCM, etc.)."""
    return _initialise_firebase()
