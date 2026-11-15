"""Unit and API tests for request validation rules in app/schemas.py."""

import pytest
from pydantic import ValidationError

from app.schemas import PostingRequest


def test_valid_message_extracts_link() -> None:
    req = PostingRequest(
        message="Check out our latest business platform https://example.com/launch"
    )
    assert req.link == "https://example.com/launch"


def test_valid_message_with_trailing_period() -> None:
    req = PostingRequest(
        message="Read our documentation at https://docs.example.com/v1."
    )
    assert req.link == "https://docs.example.com/v1"


def test_boundary_exactly_200_characters_succeeds() -> None:
    url = " https://example.com"  # 20 chars
    prefix = "A" * (200 - len(url))
    message = prefix + url
    assert len(message) == 200
    req = PostingRequest(message=message)
    assert req.link == "https://example.com"


def test_boundary_201_characters_fails() -> None:
    url = " https://example.com"  # 20 chars
    prefix = "A" * (201 - len(url))
    message = prefix + url
    assert len(message) == 201
    with pytest.raises(ValidationError) as exc_info:
        PostingRequest(message=message)
    assert "exceeds the maximum allowed limit of 200 characters" in str(exc_info.value)


@pytest.mark.parametrize(
    "empty_msg",
    ["", "   ", "\n\t  "],
)
def test_empty_or_whitespace_message_fails(empty_msg: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        PostingRequest(message=empty_msg)
    assert "must not be empty or whitespace only" in str(exc_info.value)


def test_message_without_link_fails() -> None:
    with pytest.raises(ValidationError) as exc_info:
        PostingRequest(message="This announcement has no link at all!")
    assert "exactly one valid http:// or https:// CTA link (found 0)" in str(
        exc_info.value
    )


def test_message_with_two_links_fails() -> None:
    with pytest.raises(ValidationError) as exc_info:
        PostingRequest(
            message="Visit https://example.com and also https://second.example.org"
        )
    assert "exactly one CTA link, but found 2" in str(exc_info.value)


@pytest.mark.parametrize(
    "bad_message,expected_substring",
    [
        ("Click here javascript:alert(1)", "Invalid URL scheme 'javascript:'"),
        ("Download from ftp://files.example.com/archive.zip", "Invalid URL scheme 'ftp:'"),
        ("Visit example.com for details", "missing explicit 'http://' or 'https://' scheme"),
        ("Visit www.example.com for details", "missing explicit 'http://' or 'https://' scheme"),
        ("Broken host https://invalid_host_no_tld", "invalid hostname"),
    ],
)
def test_invalid_url_or_scheme_rejected(
    bad_message: str,
    expected_substring: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        PostingRequest(message=bad_message)
    assert expected_substring in str(exc_info.value)