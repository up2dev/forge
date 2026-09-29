from forge.generator.render import singularize
from scripts.make_crud import pluralize


def test_pluralize_common_cases():
    assert pluralize("category") == "categories"
    assert pluralize("book") == "books"
    assert pluralize("author") == "authors"
    assert pluralize("box") == "boxes"
    assert pluralize("dish") == "dishes"
    assert pluralize("bus") == "buses"


def test_singularize_common_cases():
    assert singularize("categories") == "category"
    assert singularize("books") == "book"
    assert singularize("authors") == "author"
    assert singularize("boxes") == "box"
    assert singularize("dishes") == "dish"
    assert singularize("buses") == "bus"


def test_pluralize_and_singularize_are_inverse_for_common_cases():
    for word in ["category", "book", "author", "box", "dish", "bus", "tag"]:
        assert singularize(pluralize(word)) == word
