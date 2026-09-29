from forge.i18n import trans


def test_known_key_returns_translation():
    assert trans("auth.invalid_credentials", "fr") == "Identifiants invalides"
    assert trans("auth.invalid_credentials", "en") == "Invalid credentials"


def test_unknown_locale_falls_back_to_default():
    assert trans("auth.invalid_credentials", "de") == "Invalid credentials"


def test_unknown_key_returns_the_key_itself():
    assert trans("this.key.does.not.exist") == "this.key.does.not.exist"


def test_interpolation():
    assert trans("mail.welcome.greeting", "en", name="Franz") == "Hi Franz,"
