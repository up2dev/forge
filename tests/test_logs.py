import logging

from forge import config


def test_file_backend_writes_to_log_file(tmp_path, monkeypatch):
    import forge.logs as logs_module

    monkeypatch.setenv("FORGE_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("FORGE_LOG_BACKEND", "file")
    config.get_settings.cache_clear()
    logs_module._configured = False

    logs_module.setup_logging()
    logging.getLogger("forge.test_logs").info("hello file backend")

    log_file = tmp_path / "forge.log"
    assert log_file.exists()
    assert "hello file backend" in log_file.read_text()

    logs_module._configured = False
    config.get_settings.cache_clear()


def test_mongo_backend_writes_documents(monkeypatch):
    import mongomock
    import pymongo

    monkeypatch.setattr(pymongo, "MongoClient", mongomock.MongoClient)

    import forge.logs as logs_module

    monkeypatch.setenv("FORGE_LOG_BACKEND", "mongo")
    monkeypatch.setenv("FORGE_LOG_MONGO_DB", "test_logs_db")
    monkeypatch.setenv("FORGE_LOG_MONGO_COLLECTION", "test_logs_col")
    config.get_settings.cache_clear()
    logs_module._configured = False

    logs_module.setup_logging()
    logging.getLogger("forge.test_logs").warning("hello mongo backend")

    handler = next(
        h for h in logging.getLogger("forge").handlers if isinstance(h, logs_module.MongoLogHandler)
    )
    docs = list(handler._collection.find())

    assert len(docs) == 1
    assert docs[0]["message"] == "hello mongo backend"
    assert docs[0]["level"] == "WARNING"

    logs_module._configured = False
    config.get_settings.cache_clear()
