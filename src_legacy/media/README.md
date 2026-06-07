# media

Local media and artifact storage for uploads, generated files, generated images,
and extracted attachment text.

## Files

- `__init__.py`: Public exports for media store and artifact types.
- `attachment_extractors.py`: Extracts text from supported uploaded/generated attachments.
- `image.py`: Image validation, resizing, MIME handling, and data URL helpers.
- `store.py`: Registers, stores, resolves, and serves media artifacts under `.paper-notes/media/`.
- `types.py`: Dataclasses for public media artifacts and image artifact metadata.
