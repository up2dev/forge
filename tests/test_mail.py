from forge.mail.base import BaseMail


def _welcome_mail(name="Franz"):
    return BaseMail(
        template="welcome.html",
        context={"greeting": f"Bonjour {name},", "body": "Votre compte a été créé."},
        to=["franz@exemple.fr"],
        subject="Bienvenue sur Forge",
    )


def test_html_declares_utf8_charset(client):
    """Régression : sans <meta charset="utf-8">, un client mail qui se
    fie au HTML plutôt qu'à l'en-tête MIME affiche les accents en
    mojibake (Ã©tÃ© au lieu de été)."""
    html = _welcome_mail().render()

    assert '<meta charset="utf-8">' in html


def test_accented_characters_survive_rendering(client):
    html = _welcome_mail().render()

    assert "Votre compte a été créé." in html
    assert "Ã©" not in html  # signature du mojibake, ne doit jamais apparaître


def test_logo_embedded_in_layout(client):
    html = _welcome_mail().render()

    assert "data:image/png;base64," in html


def test_brand_color_still_applied_to_header(client, monkeypatch):
    """Régression : le logo a bien failli remplacer FORGE_BRAND_COLOR
    par une couleur fixe dans le bandeau — la variable reste appliquée."""
    from forge import config

    monkeypatch.setenv("FORGE_BRAND_COLOR", "#123456")
    config.get_settings.cache_clear()

    html = _welcome_mail().render()

    assert "#123456" in html

    config.get_settings.cache_clear()
